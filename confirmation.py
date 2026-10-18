"""Confirmação por código para ações sensíveis (enviar email, instalar app, clique arriscado).

A barreira de segurança: a ação só roda quando a ÚLTIMA fala do próprio usuário
contém a frase de confirmação com o código de 6 dígitos. Texto de páginas, emails
ou do modelo nunca serve como confirmação.

Com voz, a transcrição chega como "Confirmar 482 913.", "confirma quatro oito dois
nove um três" ou "quatrocentos e oitenta e dois, novecentos e treze". Por isso a fala
é normalizada (minúsculas, sem acentos e pontuação, números por extenso viram dígitos)
e comparada com uma gramática fechada: verbo de confirmação, palavras de apoio
conhecidas e o número — nada além disso. "Não confirmar 482913" ou "confirmar 482913
e apaga tudo" não passam.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import unicodedata
from typing import Any, Literal

ConfirmAction = Literal["email", "install", "screen"]

# Quanto tempo esperar a transcrição da fala do usuário chegar ao histórico. O Gemini
# Live às vezes entrega a chamada de ferramenta antes do texto final da fala.
CONFIRMATION_WAIT_SECONDS = 3.0
CONFIRMATION_POLL_SECONDS = 0.2

CONFIRM_VERBS = {"confirmar", "confirma", "confirmo", "confirme"}
# Palavras de apoio aceitas entre o verbo e o número ("confirmar o código 482913").
FILLER_WORDS = {"o", "a", "do", "da", "de", "codigo", "numero"}
ACTION_WORDS: dict[ConfirmAction, set[str]] = {
    "email": {"envio", "email"},
    "install": {"instalacao", "instalar"},
    # Mouse e teclado (computer_use.py): "confirmar clique 482913".
    "screen": {"clique", "click", "acao", "tecla"},
}
LEADING_WORDS = {"jarvis", "ok"}
TRAILING_WORDS = {"jarvis", "por", "favor"}

UNITS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "meia": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
}
TEENS = {
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezasseis": 16,
    "dezessete": 17,
    "dezassete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "dezanove": 19,
}
TENS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "cincoenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
HUNDREDS = {
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}
NUMBER_WORDS = {"zero", "cem", "mil", "e", *UNITS, *TEENS, *TENS, *HUNDREDS}
DIGIT_NAMES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def speech_tokens(text: str) -> list[str]:
    """Lowercase words without accents or punctuation: "Confirmar 482.913!" -> [confirmar, 482, 913]."""
    cleaned = strip_accents(text).lower().replace("e-mail", "email")
    return re.findall(r"[a-z0-9]+", cleaned)


class _NumberGroup:
    """One spoken number ("quatrocentos e oitenta e dois") being assembled word by word."""

    def __init__(self) -> None:
        self.value = 0
        self.thousands: int | None = None
        self.hundreds = self.tens = self.units = False

    @property
    def empty(self) -> bool:
        return not (self.hundreds or self.tens or self.units) and self.thousands is None

    def add(self, word: str) -> bool:
        """Add a number word; False means it starts a new number."""
        if word == "cem":
            if self.hundreds or self.tens or self.units:
                return False
            self.value += 100
            self.hundreds = self.tens = self.units = True
        elif word in HUNDREDS:
            if self.hundreds or self.tens or self.units:
                return False
            self.value += HUNDREDS[word]
            self.hundreds = True
        elif word in TEENS:
            if self.tens or self.units:
                return False
            self.value += TEENS[word]
            self.tens = self.units = True
        elif word in TENS:
            if self.tens or self.units:
                return False
            self.value += TENS[word]
            self.tens = True
        elif word in UNITS:
            if self.units:
                return False
            self.value += UNITS[word]
            self.units = True
        return True

    def add_thousand(self) -> bool:
        if self.thousands is not None:
            return False
        self.thousands = (self.value or 1) * 1000
        self.value = 0
        self.hundreds = self.tens = self.units = False
        return True

    def digits(self) -> str:
        return str((self.thousands or 0) + self.value)


def digits_from_tokens(tokens: list[str]) -> str | None:
    """Turn spoken/written number tokens into one digit string.

    "482 913", "quatro oito dois nove um tres", "quarenta e oito vinte e nove treze"
    and "quatrocentos e oitenta e dois mil novecentos e treze" all give "482913".
    Returns None if any token is not part of a number.
    """
    if not tokens:
        return None

    parts: list[str] = []
    group: _NumberGroup | None = None

    def flush() -> None:
        nonlocal group
        if group is not None and not group.empty:
            parts.append(group.digits())
        group = None

    for token in tokens:
        if token.isdigit():
            flush()
            parts.append(token)
        elif token == "e":
            continue
        elif token == "zero":
            flush()
            parts.append("0")
        elif token == "mil":
            group = group or _NumberGroup()
            if not group.add_thousand():
                return None
        elif token in NUMBER_WORDS:
            group = group or _NumberGroup()
            if not group.add(token):
                flush()
                group = _NumberGroup()
                group.add(token)
        else:
            return None
    flush()
    return "".join(parts) or None


def normalize_code(value: str) -> str | None:
    """Normalize a code given by the model ("482 913", "quatro oito dois...")."""
    return digits_from_tokens(speech_tokens(value))


def parse_confirmation(text: str | None, action: ConfirmAction) -> str | None:
    """Return the code in a confirmation phrase, or None if the phrase is not one.

    email:   "confirmar <código>" (aceita "confirma", "confirmar o envio", "confirmar código").
    install: "confirmar instalação <código>" (a palavra instalação é obrigatória).
    screen:  "confirmar clique <código>" (a palavra clique é obrigatória).
    """
    if not text:
        return None
    tokens = speech_tokens(text)
    while tokens and tokens[0] in LEADING_WORDS:
        tokens.pop(0)
    while tokens and tokens[-1] in TRAILING_WORDS:
        tokens.pop()
    if not tokens or tokens[0] not in CONFIRM_VERBS:
        return None

    index = 1
    action_words = ACTION_WORDS[action]
    saw_action = False
    while index < len(tokens) and (tokens[index] in FILLER_WORDS or tokens[index] in action_words):
        saw_action = saw_action or tokens[index] in action_words
        index += 1
    if action in {"install", "screen"} and not saw_action:
        return None
    return digits_from_tokens(tokens[index:])


def confirmation_phrase(action: ConfirmAction, code: str) -> str:
    if action == "install":
        return f"confirmar instalação {code}"
    if action == "screen":
        return f"confirmar clique {code}"
    return f"confirmar {code}"


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def spoken_digits(code: str) -> str:
    """"482913" -> "quatro, oito, dois, nove, um, três" (para o Jarvis falar com clareza)."""
    return ", ".join(DIGIT_NAMES[int(digit)] for digit in code if digit.isdigit())


def session_state(context: Any) -> dict[str, Any]:
    userdata = context.userdata
    if userdata is None:
        userdata = {}
        context.session.userdata = userdata
    return userdata


def last_user_message(context: Any) -> str | None:
    history = getattr(context.session, "history", None)
    if history is None or not hasattr(history, "messages"):
        return None

    for message in reversed(history.messages()):
        role = str(getattr(message, "role", "")).lower()
        if role == "user" or role.endswith(".user"):
            text_content = getattr(message, "text_content", None)
            if isinstance(text_content, str):
                return text_content.strip()
    return None


async def wait_for_user_confirmation(
    context: Any,
    action: ConfirmAction,
    code: str,
    timeout: float | None = None,
) -> tuple[bool, str | None]:
    """Check that the user's latest message is the confirmation phrase with this code.

    The transcript of the user's speech may land in the history a moment after the tool
    call, so this waits briefly for it. It only ever looks at the latest user message.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (CONFIRMATION_WAIT_SECONDS if timeout is None else timeout)
    while True:
        heard = last_user_message(context)
        if parse_confirmation(heard, action) == code:
            return True, heard
        if loop.time() >= deadline:
            return False, heard
        await asyncio.sleep(CONFIRMATION_POLL_SECONDS)
