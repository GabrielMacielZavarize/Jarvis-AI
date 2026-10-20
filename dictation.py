"""Modo ditado (protocolo DIT-29): o Jarvis escreve o que o usuário fala no campo em foco.

"Jarvis, modo ditado" liga; tudo o que ele falar vira texto no campo com foco (Bloco de
Notas, WhatsApp Web, PhpStorm, Discord...) até "fim do ditado". No meio do ditado valem os
comandos falados "vírgula", "ponto", "ponto de interrogação", "nova linha", "novo
parágrafo", "apaga a última palavra/frase", "desfaz" e "tudo maiúsculo". A variante de uma
frase só é "escreve aqui: chego em 10 minutos" (write_here).

De onde vem o texto (a escolha do DIT-29): um hook direto nas transcrições da fala do
usuário (evento ``user_input_transcribed`` do LiveKit, que o Gemini Live alimenta), e não o
modelo repetindo o texto numa ferramenta. Assim o que é digitado são as palavras que o
usuário disse, sem o modelo resumir, traduzir ou "corrigir", e sem uma chamada de ferramenta
por frase. O modelo só liga o modo (start_dictation). Enquanto o ditado está ligado:

- toda fala que o modelo começar é interrompida no ``speech_created``, antes de tocar áudio
  ou rodar ferramenta: o Jarvis não responde falando, só toca um bipe curto por frase;
- as ferramentas de mouse e teclado (computer_use.py) recusam, porque a fala é texto, não
  ordem;
- o Gemini só manda a transcrição final quando termina a resposta dele, então o texto sai das
  transcrições parciais assim que o usuário faz uma pausa (DICTATION_SETTLE_SECONDS); a
  final, quando chega, só completa o que faltou.

A digitação é a do MOU-20 (tecla por tecla no layout ativo, com conferência por UI
Automation) e passa pelas mesmas travas: nada de senhas, cartões, documentos, comandos,
campos de senha, UAC, terminais ou Configurações; ESC ou mexer no mouse durante a digitação
param tudo (o ditado desliga). Em apps de conversa a "nova linha" vira Shift+Enter, para não
enviar a mensagem: enviar fica com o usuário.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from livekit.agents import RunContext, function_tool

import computer_use as cu
from computer_use import ComputerUseError, UserTookOver, WindowInfo
from confirmation import last_user_message, strip_accents
from hud import publish_hud_event, tool_status

logger = logging.getLogger("jarvis-dictation")

PROTOCOL = "DIT-29"
STATE_KEY = cu.DICTATION_KEY
HUD_EVENT = "dictation"

# Pausa na fala que encerra uma frase do ditado (as parciais pararam de chegar).
DICTATION_SETTLE_SECONDS = 1.2
# Sem nenhuma fala por esse tempo o ditado desliga sozinho (o Jarvis voltaria a ficar mudo).
DICTATION_IDLE_SECONDS = 180.0
# Logo depois do "fim do ditado" a resposta do modelo àquela fala ainda pode começar.
STOP_GRACE_SECONDS = 2.0
START_WAIT_SECONDS = 2.5
WATCH_POLL_SECONDS = 0.1
HISTORY_LIMIT = 50
TAIL_CHARS = 280

# ───────────────────────── normalização: fala → texto (pura) ─────────────────────────

PUNCT_CHARS = ".,;:!?…"
EDGE_CHARS = PUNCT_CHARS + "\"'()«»“”"
SENTENCE_END = ".!?…"

DELETE_VERBS = "apaga|apague|apagar|deleta|delete|deletar|remove|remova|tira|tire"
END_VERBS = "encerra|encerrar|encerre|termina|terminar|termine|para|parar|pare|sai|sair|desliga|desligar|fecha|fechar"
CAPS_WORDS = "maiusculo|maiuscula|maiusculos|maiusculas"
LOWER_WORDS = "minusculo|minuscula|minusculos|minusculas"

# Gramática fechada: palavras sem acento; "a|b" alterna, "[a|b]" é opcional.
COMMAND_SPECS: tuple[tuple[str, str, str], ...] = (
    ("end", "", "fim [do|de] [modo] ditado"),
    ("end", "", f"{END_VERBS} [o|do] [modo] ditado"),
    ("punct", "?", "ponto [de] interrogacao"),
    ("punct", "!", "ponto [de] exclamacao"),
    ("punct", ";", "ponto e virgula"),
    ("punct", ":", "dois pontos"),
    ("punct", ".", "ponto final"),
    ("punct", "...", "reticencias"),
    ("punct", ".", "ponto"),
    ("punct", ",", "virgula"),
    ("newline", "\n", "nova|proxima linha"),
    ("newline", "\n", "pula|pular|quebra [uma|a|de] linha"),
    ("paragraph", "\n\n", "novo|proximo paragrafo"),
    ("delete_word", "", f"{DELETE_VERBS} [a|essa|esta] [ultima] palavra"),
    ("delete_sentence", "", f"{DELETE_VERBS} [a|essa|esta] [ultima] frase"),
    ("undo", "", "desfaz|desfazer|desfaca"),
    ("caps_on", "", f"tudo|caixa [em] {CAPS_WORDS}|alta"),
    ("caps_off", "", f"tudo|caixa [em] {LOWER_WORDS}|baixa"),
    ("caps_off", "", f"fim [do|da|dos|das] {CAPS_WORDS}"),
)
# "no ponto", "um ponto", "uma vírgula": a palavra, não a pontuação.
LITERAL_AFTER = {
    "ponto": {"o", "um", "no", "num", "ao", "do", "de", "esse", "este", "nesse", "neste", "aquele", "naquele", "cada", "pelo", "bom", "mesmo", "meu", "seu"},
    "virgula": {"a", "uma", "sem", "com", "essa", "esta", "da", "na", "cada"},
}
INTERROGATIVES = {"quem", "como", "onde", "aonde", "quando", "qual", "quais", "quanto", "quanta", "quantos", "quantas", "cade"}
INTERROGATIVE_PAIRS = {("por", "que"), ("o", "que"), ("sera", "que"), ("pra", "que")}
# Nomes que a transcrição escreve com maiúscula e que continuam assim no meio da frase.
KEEP_CAPITALIZED = {
    "jarvis", "gabriel", "claude", "gemini", "google", "criciuma", "satc", "phpstorm", "edge", "whatsapp",
    "youtube", "discord", "windows", "brasil", "deus",
}


COMMAND_LABELS = {
    "punct": "pontuação",
    "newline": "nova linha",
    "paragraph": "novo parágrafo",
    "delete_word": "apaga a última palavra",
    "delete_sentence": "apaga a última frase",
    "undo": "desfaz",
    "caps_on": "tudo maiúsculo",
    "caps_off": "fim do maiúsculo",
    "end": "fim do ditado",
}


@dataclass(frozen=True)
class Op:
    """One step of an utterance: a word to write or a spoken command."""

    kind: str  # word, punct, newline, paragraph, delete_word, delete_sentence, undo, caps_on, caps_off, end
    value: str = ""
    spoken: bool = True  # punct: dita pelo usuário (False: a transcrição pôs sozinha)


def _phrase(spec: str) -> tuple[tuple[frozenset[str], bool], ...]:
    return tuple((frozenset(item.strip("[]").split("|")), item.startswith("[")) for item in spec.split())


COMMANDS = tuple((kind, value, _phrase(spec)) for kind, value, spec in COMMAND_SPECS)


def norm_token(token: str) -> str:
    return strip_accents(token).lower().strip(EDGE_CHARS)


def _match(parts: tuple[tuple[frozenset[str], bool], ...], tokens: list[str], start: int) -> int:
    """Tokens the phrase consumes at `start` (0: no match). Optional words are greedy."""
    index = start
    for words, optional in parts:
        if index < len(tokens) and tokens[index] in words:
            index += 1
        elif not optional:
            return 0
    return index - start


def _command_at(tokens: list[str], start: int) -> tuple[Op, int] | None:
    best: tuple[Op, int] | None = None
    for kind, value, parts in COMMANDS:
        length = _match(parts, tokens, start)
        if length and (best is None or length > best[1]):
            best = (Op(kind, value), length)
    if best is None:
        return None
    word = tokens[start]
    if best[1] == 1 and word in LITERAL_AFTER:
        before = tokens[start - 1] if start else ""
        after = tokens[start + 1] if start + 1 < len(tokens) else ""
        if before in LITERAL_AFTER[word] or (word == "ponto" and after in {"de", "do", "da"}):
            return None
    return best


def parse_utterance(transcript: str) -> tuple[list[Op], bool]:
    """Spoken words → operations, in order, and whether punctuation was dictated by voice.

    When the user dictates punctuation ("oi vírgula tudo bem"), the punctuation the
    transcriber added on its own is dropped, so "Oi, vírgula, tudo bem." is "Oi, tudo bem".
    """
    raw = transcript.split()
    tokens = [norm_token(token) for token in raw]
    ops: list[Op] = []
    index = 0
    for vocative in (["jarvis"], ["ok", "jarvis"]):
        if tokens[: len(vocative)] == vocative and _command_at(tokens, len(vocative)):
            index = len(vocative)  # "Jarvis, fim do ditado": vocativo, não texto
    while index < len(tokens):
        found = _command_at(tokens, index) if tokens[index] else None
        if found:
            ops.append(found[0])
            index += found[1]
            continue
        token = raw[index]
        if token.strip(PUNCT_CHARS):
            ops.append(Op("word", token))
        else:
            ops.append(Op("punct", token, spoken=False))  # pontuação solta da transcrição
        index += 1
    explicit = any(op.kind in {"newline", "paragraph"} or (op.kind == "punct" and op.spoken) for op in ops)
    if explicit:
        ops = [
            Op("word", op.value.strip(PUNCT_CHARS)) if op.kind == "word" else op
            for op in ops
            if not (op.kind == "punct" and not op.spoken)
        ]
    return ops, explicit


def edit_between(before: str, after: str) -> tuple[int, str]:
    """(Backspaces, text to type) that turn the field's `before` into `after`."""
    common = 0
    for old, new in zip(before, after):
        if old != new:
            break
        common += 1
    return len(before) - common, after[common:]


@dataclass(frozen=True)
class Snapshot:
    text: str
    caps: bool
    soft_end: bool


@dataclass(frozen=True)
class Outcome:
    before: str
    after: str
    ended: bool
    commands: tuple[str, ...]
    state: Snapshot
    history: tuple[Snapshot, ...]

    @property
    def edit(self) -> tuple[int, str]:
        return edit_between(self.before, self.after)


def _transcriber_capital(word: str) -> bool:
    """'Tudo' at the start of a new utterance: the transcriber's capital, not a name."""
    return (
        word[:1].isupper()
        and word[1:] == word[1:].lower()
        and not any(char.isdigit() for char in word)
        and norm_token(word) not in KEEP_CAPITALIZED
    )


def _is_question(sentence: str) -> bool:
    words = [norm_token(word) for word in sentence.split()]
    words = [word for word in words if word]
    return bool(words) and (words[0] in INTERROGATIVES or tuple(words[:2]) in INTERROGATIVE_PAIRS)


class DictationText:
    """What this dictation wrote in the field, and the state machine of the spoken commands.

    Pure: no keyboard here. ``feed`` takes one utterance and says how the text changes;
    the controller turns that into Backspaces and keys. Only text written by this dictation
    can be erased: "apaga a última palavra" never reaches what was already in the field.
    """

    def __init__(self) -> None:
        self.text = ""
        self.caps = False
        self.soft_end = False  # o último caractere é pontuação automática (troca pela falada)
        self.history: list[Snapshot] = []

    def snapshot(self) -> Snapshot:
        return Snapshot(self.text, self.caps, self.soft_end)

    def restore(self, snapshot: Snapshot) -> None:
        self.text, self.caps, self.soft_end = snapshot.text, snapshot.caps, snapshot.soft_end

    def rollback(self, outcome: Outcome) -> None:
        """Forget an utterance that could not be typed."""
        self.restore(outcome.state)
        self.history = list(outcome.history)

    def new_field(self) -> None:
        """Focus went to another field: nothing there was written by us, so nothing to erase."""
        self.text, self.soft_end, self.history = "", False, []

    def feed(self, transcript: str, *, auto_punctuation: bool = True) -> Outcome:
        before = self.snapshot()
        history = tuple(self.history)
        ops, explicit = parse_utterance(transcript)
        base = before
        heard: list[str] = []
        ended = False
        first_word = True
        last_kind = ""
        for op in ops:
            if op.kind == "end":
                ended = True
                heard.append(COMMAND_LABELS["end"])
                break
            if op.kind == "word":
                self._word(op.value, first_word)
                first_word = False
            elif op.kind == "punct":
                self._punct(op.value)
            elif op.kind in {"newline", "paragraph"}:
                self.text = self.text.rstrip(" ") + op.value
                self.soft_end = False
            elif op.kind == "delete_word":
                self.text = re.sub(r"\S+$", "", self.text.rstrip()).rstrip(" ")
                self.soft_end = False
            elif op.kind == "delete_sentence":
                self._delete_sentence()
            elif op.kind == "undo":
                if self.snapshot() != base:
                    self.restore(base)
                elif self.history:
                    base = self.history.pop()
                    self.restore(base)
            elif op.kind in {"caps_on", "caps_off"}:
                self.caps = op.kind == "caps_on"
            if op.kind != "word":
                heard.append(COMMAND_LABELS[op.kind] if op.kind != "punct" else repr(op.value))
            last_kind = op.kind
        if auto_punctuation and not explicit and last_kind == "word" and self.text[-1:] not in PUNCT_CHARS:
            sentence = re.split(r"[.!?…\n]", self.text)[-1]
            spoken = " ".join(op.value for op in ops if op.kind == "word")
            self.text += "?" if _is_question(sentence) or _is_question(spoken) else "."
            self.soft_end = True
        if self.snapshot() != base:
            self.history = [*self.history, base][-HISTORY_LIMIT:]
        return Outcome(before.text, self.text, ended, tuple(heard), before, history)

    def _at_sentence_start(self) -> bool:
        text = self.text.rstrip(" ")
        return not text or text[-1] in SENTENCE_END or text[-1] == "\n"

    def _word(self, word: str, first_in_utterance: bool) -> None:
        if self.caps:
            word = word.upper()
        elif self._at_sentence_start():
            word = word[:1].upper() + word[1:]
        elif first_in_utterance and _transcriber_capital(word):
            word = word[:1].lower() + word[1:]
        separator = "" if not self.text or self.text[-1] in " \n" else " "
        self.text += separator + word
        self.soft_end = False

    def _punct(self, mark: str) -> None:
        if self.soft_end:
            self.text = self.text[:-1]  # "vírgula" depois de uma pausa troca o ponto automático
        self.text = self.text.rstrip(" ") + mark
        self.soft_end = False

    def _delete_sentence(self) -> None:
        text = self.text.rstrip().rstrip(SENTENCE_END)
        cut = max(text.rfind(mark) for mark in SENTENCE_END + "\n")
        self.text = text[: cut + 1] if cut >= 0 else ""
        self.soft_end = False


def write_once(transcript: str) -> str:
    """Text for "escreve aqui: ...": same spoken commands, capitalized, no automatic period."""
    return DictationText().feed(transcript, auto_punctuation=False).after


# ───────────────────────── controlador: transcrições → teclado ─────────────────────────

BEEPS = {  # (frequência Hz, duração ms) do bipe local quando não há HUD para tocar
    "start": ((880, 70), (1320, 90)),
    "tick": ((1200, 40),),
    "error": ((330, 160),),
    "end": ((1320, 70), (880, 110)),
}


def _local_beep(kind: str) -> None:
    if sys.platform != "win32":
        return
    import winsound

    for frequency, duration in BEEPS.get(kind, ()):
        winsound.Beep(frequency, duration)


def _chunks(text: str, size: int) -> list[str]:
    return [text[start : start + size] for start in range(0, len(text), size)] or [text]


def apply_edit(window: WindowInfo | None, erase: int, insert: str) -> bool | None:
    """Erase and type in the focused field with every MOU-20 guard. Runs in a worker thread.

    Returns whether UI Automation saw the typed text in the field (None: the app does not
    tell). Raises ComputerUseError when refused and UserTookOver on ESC or mouse movement.
    """
    if cu.is_hud(window):
        raise ComputerUseError("o campo em foco é o próprio HUD; clique no campo onde quer escrever")
    if insert:
        for piece in _chunks(insert, cu.MAX_TYPE_CHARS):
            cu._check_typing(piece)
    elif erase:
        cu._check_keys("backspace")
    if erase:
        cu.erase(erase, watch_mouse=True)
    if not insert:
        return None
    cu.type_unicode(insert, soft_newlines=cu.is_messaging(window), watch_mouse=True)
    return cu.typed_text_landed(insert.strip()) if insert.strip() else None


class DictationController:
    """Dictation mode of one voice session: listens to the user's transcripts and types them.

    Attached at session start (``watch_dictation``) so it already knows which utterance
    turned the mode on and never types "modo ditado" itself.
    """

    def __init__(
        self,
        session: Any,
        *,
        publish: Callable[..., Any] = publish_hud_event,
        beeper: Callable[[str], None] = _local_beep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.publish = publish
        self.beeper = beeper
        self.clock = clock
        self.active = False
        self.text = DictationText()
        self.window: WindowInfo | None = None
        self.typed_total = 0
        self._recent_items: deque[str] = deque(maxlen=64)
        self._ignored: set[str] = set()
        self._pending: dict[str, str] = {}
        self._committed: dict[str, list[str]] = {}
        self._anonymous = 0
        self._timer: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._watch_task: asyncio.Task[None] | None = None
        self._typing = False
        self._last_heard = 0.0
        self._stopped_at = float("-inf")

    def attach(self) -> DictationController:
        self.session.on("user_input_transcribed", self._on_transcribed)
        self.session.on("speech_created", self._on_speech_created)
        return self

    # ── eventos da sessão ──

    def _on_speech_created(self, event: Any) -> None:
        """While dictating, Jarvis does not answer: stop the reply before audio or tools run."""
        if not self.active and self.clock() - self._stopped_at > STOP_GRACE_SECONDS:
            return
        handle = getattr(event, "speech_handle", None)
        if handle is None:
            return
        try:
            handle.interrupt(force=True)
        except Exception:
            logger.debug("Não consegui interromper a fala durante o ditado.", exc_info=True)

    def _on_transcribed(self, event: Any) -> None:
        text = (getattr(event, "transcript", "") or "").strip()
        item = getattr(event, "item_id", None)
        if item and item not in self._recent_items:
            self._recent_items.append(item)
        if not self.active or not text or (item and item in self._ignored):
            return
        final = bool(getattr(event, "is_final", False))
        if item is None:
            if not final:
                return  # sem id não dá para juntar as parciais; espera a final
            self._anonymous += 1
            item = f"final-{self._anonymous}"
        self._pending[item] = text
        self._last_heard = self.clock()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if final:
            self._spawn(self._flush())
        else:
            self._timer = asyncio.get_running_loop().call_later(DICTATION_SETTLE_SECONDS, lambda: self._spawn(self._flush()))

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_idle(self) -> None:
        """Wait for the pending commits (tests and stop)."""
        while self._tasks - {asyncio.current_task()}:
            await asyncio.gather(*(self._tasks - {asyncio.current_task()}), return_exceptions=True)

    # ── ligar e desligar ──

    async def start(self, first_text: str = "") -> str:
        if self.active:
            return "O modo ditado já está ligado."
        self.window = await asyncio.to_thread(cu.foreground_window)
        self.active = True
        self.text = DictationText()
        self.typed_total = 0
        self._ignored = set(self._recent_items)  # a fala "modo ditado" não é texto
        self._pending.clear()
        self._committed.clear()
        self._last_heard = self.clock()
        where = f"'{cu._truncate(self.window.title, 50)}'" if self.window else "o campo em foco"
        await self._notify("on", beep="start", message=f"Modo ditado ligado em {where}. Diga 'fim do ditado' para parar.")
        if cu.IS_WINDOWS:
            self._watch_task = asyncio.ensure_future(self._watch())
        if first_text.strip():
            async with self._lock:
                await self._commit(first_text)
        return where

    async def stop(self, reason: str = "fim do ditado", *, took_over: bool = False) -> str:
        if not self.active:
            return "O modo ditado não estava ligado."
        self.active = False
        self._stopped_at = self.clock()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._pending.clear()
        if self._watch_task is not None and self._watch_task is not asyncio.current_task():
            self._watch_task.cancel()
        self._watch_task = None
        message = f"Modo ditado desligado ({reason}). Escrevi {self.typed_total} caractere(s)."
        await self._notify("off", beep="error" if took_over else "end", message=message)
        return message

    async def _watch(self) -> None:
        """ESC (between utterances) or a long silence turn dictation off."""
        try:
            while self.active:
                await asyncio.sleep(WATCH_POLL_SECONDS)
                if not self.active:
                    return
                if not self._typing and await asyncio.to_thread(cu._escape_down):
                    await self.stop("ESC pressionado", took_over=True)
                    return
                if self.clock() - self._last_heard > DICTATION_IDLE_SECONDS:
                    await self.stop(f"{int(DICTATION_IDLE_SECONDS // 60)} minutos sem ouvir nada")
                    return
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Falha ao vigiar o ESC no ditado.", exc_info=True)

    # ── frases → teclado ──

    async def _flush(self) -> None:
        async with self._lock:
            while self._pending and self.active:
                item, raw = next(iter(self._pending.items()))
                del self._pending[item]
                chunk = self._new_words(item, raw)
                if chunk:
                    await self._commit(chunk)

    def _new_words(self, item: str, raw: str) -> str:
        """Part of an item's (cumulative) transcript not typed yet."""
        words = raw.split()
        done = self._committed.get(item, [])
        fresh = words[len(done) :]
        if done and len(words) >= len(done) and words[len(done) - 1] != done[-1] and words[len(done) - 1].startswith(done[-1]):
            tail = words[len(done) - 1][len(done[-1]) :]
            if tail.strip(PUNCT_CHARS) == "":
                fresh = [tail, *fresh]  # a final pôs pontuação na última palavra já digitada
        self._committed[item] = words
        return " ".join(fresh)

    async def _commit(self, chunk: str) -> None:
        window = await asyncio.to_thread(cu.foreground_window)
        if window is not None and self.window is not None and window.hwnd != self.window.hwnd:
            self.text.new_field()
            logger.info("[%s] Foco mudou para '%s'; continuo escrevendo lá.", PROTOCOL, window.title)
        self.window = window or self.window
        outcome = self.text.feed(chunk)
        erase, insert = outcome.edit
        landed: bool | None = None
        if erase or insert:
            self._typing = True
            try:
                landed = await asyncio.to_thread(apply_edit, window, erase, insert)
            except UserTookOver as exc:
                await self.stop(str(exc).rstrip("."), took_over=True)
                return
            except ComputerUseError as exc:
                self.text.rollback(outcome)
                await self._notify("warn", beep="error", message=f"Não escrevi: {exc}", heard=chunk)
                return
            except Exception as exc:
                logger.exception("[%s] Falha ao digitar o ditado.", PROTOCOL)
                self.text.rollback(outcome)
                await self._notify("warn", beep="error", message=f"Falha ao digitar: {exc}", heard=chunk)
                return
            finally:
                self._typing = False
            self.typed_total += len(insert)
        if landed is False:
            await self._notify("warn", beep="error", message="O campo não mostra o texto como deveria; confira.", heard=chunk, typed=insert)
        elif erase or insert or outcome.commands:
            await self._notify("typing", beep="tick", heard=chunk, typed=insert, erased=erase, commands=list(outcome.commands))
        if outcome.ended:
            await self.stop()

    async def _notify(self, state: str, *, beep: str | None = None, message: str = "", **extra: Any) -> None:
        if message:
            logger.log(logging.WARNING if state == "warn" else logging.INFO, "[%s] %s", PROTOCOL, message)
        payload = {
            "state": state,
            "active": self.active,
            "protocol": PROTOCOL,
            "message": message,
            "tail": self.text.text[-TAIL_CHARS:],
            "caps": self.text.caps,
            "window": self.window.title if self.window else None,
            "beep": beep,
            **extra,
        }
        try:
            shown = bool(await self.publish(HUD_EVENT, **payload))
        except Exception:
            shown = False
        if beep and not shown:  # sem HUD, o bipe sai pelo alto-falante do PC
            try:
                await asyncio.to_thread(self.beeper, beep)
            except Exception:
                logger.debug("Falha no bipe do ditado.", exc_info=True)


def controller_for(session: Any) -> DictationController:
    userdata = getattr(session, "userdata", None)
    if userdata is None:
        userdata = {}
        session.userdata = userdata
    controller = userdata.get(STATE_KEY)
    if not isinstance(controller, DictationController):
        controller = DictationController(session).attach()
        userdata[STATE_KEY] = controller
    return controller


def watch_dictation(session: Any) -> DictationController:
    """Hook the dictation mode on the session's transcripts (call before session.start)."""
    return controller_for(session)


def dictating(session: Any) -> bool:
    controller = (getattr(session, "userdata", None) or {}).get(STATE_KEY)
    return bool(getattr(controller, "active", False))


# ───────────────────────── ferramentas ─────────────────────────

DICTATION_REQUEST = re.compile(r"\b(ditad\w*|ditar|ditando|dita\b|dite\b|ditamos)")
WRITE_HERE = re.compile(
    r"\b(?:escrev\w*|digit\w*)\b(?:[\s,]+(?:aqui|a[ií]|ali|isso|isto|pra mim|para mim|no campo))*\s*[:,-]?\s*(?:que\s+)?(.+)$",
    re.I,
)


async def _heard_request(context: RunContext, pattern: re.Pattern[str]) -> str | None:
    """The user's latest utterance, waiting briefly for its transcript to reach the history."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + START_WAIT_SECONDS
    heard = last_user_message(context)
    while not (heard and pattern.search(cu.norm(heard))) and loop.time() < deadline:
        await asyncio.sleep(cu.REQUEST_POLL_SECONDS)
        heard = last_user_message(context)
    return heard if heard and pattern.search(cu.norm(heard)) else None


def said_after_write(heard: str | None) -> str | None:
    """'Escreve aqui: chego em 10 minutos' → 'chego em 10 minutos' (the user's own words)."""
    if not heard:
        return None
    match = WRITE_HERE.search(heard)
    if match is None:
        return None
    return match.group(1).strip() or None


@function_tool()
async def start_dictation(context: RunContext, first_text: str = "") -> str:
    """Turn on dictation mode: everything the user says from now on is typed into the focused field.

    Call it for "modo ditado", "ativa o ditado", "vou ditar", "começa o ditado". The words
    are typed straight from the user's speech (not by you) until they say "fim do ditado";
    meanwhile you stay silent. Spoken commands like "vírgula", "nova linha", "apaga a última
    palavra" and "desfaz" are handled by the dictation itself.

    Args:
        first_text: Words the user dictated right after "modo ditado" in the same sentence,
            exactly as said. Usually empty.
    """
    try:
        if not cu.IS_WINDOWS:
            raise ComputerUseError("O modo ditado só funciona no Windows por enquanto.")
        if await _heard_request(context, DICTATION_REQUEST) is None:
            raise ComputerUseError("Recusado: só ligo o ditado quando o senhor pede ('Jarvis, modo ditado').")
        await tool_status("start_dictation", "running", PROTOCOL)
        where = await controller_for(context.session).start(first_text)
        await tool_status("start_dictation", "done", PROTOCOL)
        return (
            f"Modo ditado ligado ({PROTOCOL}) em {where}. Tudo o que o usuário falar agora é digitado ali "
            "automaticamente, sem você. NÃO responda e não fale nada até ele dizer 'fim do ditado'; o bipe já avisou."
        )
    except Exception as exc:
        await tool_status("start_dictation", "error", str(exc)[:80])
        return f"Não liguei o ditado: {exc}"


@function_tool()
async def write_here(context: RunContext, text: str) -> str:
    """Write ONE dictated sentence into the focused field: "escreve aqui: chego em 10 minutos".

    Spoken punctuation works ("vírgula", "ponto de interrogação", "nova linha"). Nothing is
    sent: in chat apps a new line is Shift+Enter. For longer dictation use start_dictation.

    Args:
        text: What the user asked to write, exactly as said, without "escreve aqui".
    """
    pointed = cu.pointed_point()
    try:
        heard = await cu._authorize(context)
        spoken = said_after_write(heard) or text
        final = write_once(spoken)
        await tool_status("write_here", "running", f"{len(final)} caracteres")
        field_name = None
        if pointed is not None and cu.refers_here(heard):
            # "Escreve aqui" com o dedo apontando: o campo apontado, não o que já estava em foco.
            field_name = await cu.focus_pointed(context, pointed)
        window = await asyncio.to_thread(cu.foreground_window)
        landed = await asyncio.to_thread(apply_edit, window, 0, final)
        where = f"'{cu._truncate(window.title, 40)}'" if window else "no campo em foco"
        check = {True: " e conferi no campo", False: ", mas o campo não mostra o texto como deveria; peça para conferir"}.get(landed, "")
        message = f"Escrevi \"{cu._truncate(final, 60)}\" em {where}{check}. Nada foi enviado."
        if field_name:
            message += " Antes cliquei no campo onde o usuário apontou com o dedo."
        await publish_hud_event(
            HUD_EVENT, state="once", active=False, protocol=PROTOCOL, message=message, tail=final[-TAIL_CHARS:],
            typed=final, heard=spoken, window=window.title if window else None, beep="tick", caps=False,
        )
        await tool_status("write_here", "done" if landed is not False else "error", f"{len(final)} caracteres")
        logger.info("[%s] %s", PROTOCOL, message)
        return message
    except Exception as exc:
        await tool_status("write_here", "error", str(exc)[:80])
        return f"Não escrevi: {exc}"


def build_dictation_tools() -> list[Any]:
    return [start_dictation, write_here]
