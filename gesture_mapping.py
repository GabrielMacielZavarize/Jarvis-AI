"""Gestos personalizáveis: o que cada gesto livre faz, guardado no gestos.json.

O motor (gesture_engine) só reconhece o gesto e diz o nome dele ("ok", "rock", "joinha"...);
aqui fica o mapeamento gesto → ação, com padrões sensatos e as trocas pedidas por voz
("quando eu fizer joinha, pausa a música"). O gestos.json fica ao lado do projeto (ignorado
pelo git) e só guarda o que o usuário mudou; o resto vem dos padrões.

Tipos de ação: uma ação interna (mídia, volume, microfone do Jarvis, janela em foco), um layout
salvo, abrir um app, abrir um site ou um atalho de teclado. Fechar e digitar nunca ficam num
gesto: fechar já tem o polegar para baixo, que pede confirmação segurando; atalhos que fecham
(Alt+F4, Ctrl+W...) e teclas soltas (que digitariam) são recusados, também no arquivo.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis-gestures")

GESTURES_FILE = Path(__file__).resolve().parent / "gestos.json"


class MappingError(Exception):
    """A gesture binding that is not allowed or not understood (message is user-facing)."""


@dataclass(frozen=True)
class GestureInfo:
    name: str  # como falar dele
    how: str  # como fazer
    default: dict[str, str] | None
    aliases: tuple[str, ...] = ()


GESTURES: dict[str, GestureInfo] = {
    "ok": GestureInfo(
        "OK (👌)",
        "polegar e indicador em círculo, os outros dedos esticados, parado por quase 1 s",
        {"tipo": "acao", "acao": "play_pause"},
        ("👌", "okay", "sinal de ok", "circulo"),
    ),
    "pinca_sobe": GestureInfo(
        "pinça subindo", "pinça (polegar no indicador) e subir a mão", {"tipo": "acao", "acao": "volume_up"},
        ("pinca para cima", "pinca cima", "subir a pinca"),
    ),
    "pinca_desce": GestureInfo(
        "pinça descendo", "pinça (polegar no indicador) e descer a mão", {"tipo": "acao", "acao": "volume_down"},
        ("pinca para baixo", "pinca baixo", "descer a pinca"),
    ),
    "rock": GestureInfo(
        "rock (🤘)", "indicador e mindinho esticados, parado por quase 1 s", {"tipo": "layout", "nome": "trabalho"},
        ("🤘", "chifrinho", "chifre", "metal", "rock and roll", "rock n roll", "hang loose"),
    ),
    "joinha": GestureInfo(
        "joinha (👍)", "polegar para cima com a mão fechada, parado por quase 1 s", None,
        ("👍", "polegar para cima", "positivo", "like", "legal"),
    ),
    "tapar_camera": GestureInfo(
        "tapar a câmera", "palma cobrindo a webcam por 1 s (vale mesmo desarmado)", {"tipo": "acao", "acao": "mic_toggle"},
        ("tampar a camera", "cobrir a camera", "mao na camera", "palma na camera", "shh", "silencio", "🤫"),
    ),
    "maos_afastam": GestureInfo(
        "duas mãos se afastando", "as duas palmas abertas se afastando", {"tipo": "acao", "acao": "maximize"},
        ("afastar as maos", "abrir as maos", "maos se afastando", "esticar"),
    ),
    "maos_aproximam": GestureInfo(
        "duas mãos se aproximando", "as duas palmas abertas se aproximando", {"tipo": "acao", "acao": "restore"},
        ("aproximar as maos", "juntar as maos", "maos se aproximando", "fechar as maos"),
    ),
}

# Gestos que não mudam (fazem parte do controle de janelas e da segurança).
FIXED_GESTURES = (
    ("mão aberta parada", "arma os gestos"),
    ("punho", "pega a janela em foco; mova e abra a mão para jogá-la no monitor daquele lado, ou abra parado para estender"),
    ("janela pega + 1, 2 ou 3 dedos parados", "manda a janela para a tela 1, 2 ou 3 (números do Identificar do Windows)"),
    ("polegar para baixo segurado", "fecha a janela ou a aba em foco, com contagem para confirmar"),
    ("palma descendo", "minimiza"),
    ("palma de um lado para o outro", "desfaz o último movimento"),
    ("dois dedos para o lado", "troca de aba"),
    ("indicador parado", "liga o mouse no ar"),
)

ACTIONS: dict[str, str] = {
    "play_pause": "tocar/pausar a mídia",
    "next": "próxima faixa",
    "previous": "faixa anterior",
    "volume_up": "aumentar o volume",
    "volume_down": "baixar o volume",
    "mute": "silenciar o som",
    "unmute": "reativar o som",
    "mic_toggle": "mutar/desmutar o microfone do Jarvis",
    "maximize": "estender a janela em foco",
    "restore": "restaurar a janela em foco",
    "minimize": "minimizar a janela em foco",
    "undo": "desfazer o último movimento de janela",
    "show_desktop": "mostrar a área de trabalho",
    "next_tab": "próxima aba",
    "previous_tab": "aba anterior",
}
ACTION_ALIASES = {
    "pausar": "play_pause", "pausa": "play_pause", "tocar": "play_pause", "play": "play_pause",
    "pause": "play_pause", "pausar a musica": "play_pause", "pausa a musica": "play_pause",
    "tocar pausar": "play_pause", "proxima": "next", "proxima musica": "next", "pular": "next",
    "anterior": "previous", "musica anterior": "previous", "aumentar volume": "volume_up",
    "mais volume": "volume_up", "aumentar o volume": "volume_up", "baixar volume": "volume_down",
    "menos volume": "volume_down", "baixar o volume": "volume_down", "silenciar": "mute",
    "mutar o som": "mute", "desmutar o som": "unmute", "mutar": "mic_toggle",
    "mutar o microfone": "mic_toggle", "microfone": "mic_toggle", "mutar o jarvis": "mic_toggle",
    "desligar o microfone": "mic_toggle", "desliga o microfone": "mic_toggle",
    "maximizar": "maximize", "estender": "maximize", "restaurar": "restore", "minimizar": "minimize",
    "desfazer": "undo", "area de trabalho": "show_desktop", "mostrar a area de trabalho": "show_desktop",
    "proxima aba": "next_tab", "aba anterior": "previous_tab",
}  # fmt: skip
DANGEROUS_ACTIONS = re.compile(
    r"\b(?:fech\w*|close|digit\w*|type|escrev\w*|apag\w*|delet\w*|exclu\w*|deslig\w*|shutdown|reinici\w*|formatar)\b"
)
DANGEROUS_REFUSAL = (
    "Fechar, apagar ou digitar não ficam ligados a gesto, porque um gesto pode sair sem querer. "
    "Para fechar já existe o polegar para baixo, que pede confirmação segurando."
)

KIND_NAMES = {"acao": "action", "layout": "layout", "app": "app", "site": "site", "atalho": "keys", "nada": "none"}
VOICE_KINDS = {value: key for key, value in KIND_NAMES.items()}

# ───────────────────────── teclas ─────────────────────────

MODIFIERS = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
KEY_ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "controle": "ctrl", "windows": "win", "super": "win",
    "cmd": "win", "meta": "win", "escape": "esc", "return": "enter", "espaco": "space",
    "del": "delete", "pgup": "pageup",
    "pgdn": "pagedown", "esquerda": "left", "direita": "right", "cima": "up", "baixo": "down",
    "print": "printscreen", "prtsc": "printscreen",
}  # fmt: skip
NAMED_KEYS = {
    "tab": 0x09, "esc": 0x1B, "space": 0x20, "enter": 0x0D, "backspace": 0x08, "delete": 0x2E,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C, "volumemute": 0xAD,
    "volumedown": 0xAE, "volumeup": 0xAF, "nexttrack": 0xB0, "prevtrack": 0xB1, "playpause": 0xB3,
}  # fmt: skip
NAMED_KEYS.update({f"f{n}": 0x6F + n for n in range(1, 13)})
NAMED_KEYS.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})
NAMED_KEYS.update({str(d): 0x30 + d for d in range(10)})
STANDALONE_KEYS = {*(f"f{n}" for n in range(1, 13)), "volumemute", "volumedown", "volumeup", "nexttrack", "prevtrack", "playpause", "printscreen"}
# Atalhos que fecham, apagam ou saem: nunca num gesto.
DANGEROUS_KEYS = {
    frozenset({"alt", "f4"}), frozenset({"ctrl", "w"}), frozenset({"ctrl", "f4"}), frozenset({"ctrl", "q"}),
    frozenset({"ctrl", "shift", "w"}), frozenset({"ctrl", "shift", "q"}), frozenset({"shift", "delete"}),
    frozenset({"ctrl", "delete"}), frozenset({"ctrl", "alt", "delete"}), frozenset({"ctrl", "shift", "esc"}),
}  # fmt: skip


def plain(text: str) -> str:
    """Lowercase, no accents, single spaces (emoji are kept)."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s+🤘👍👌🤫]", " ", text).split())


def parse_keys(text: str) -> tuple[tuple[int, ...], str]:
    """'ctrl+shift+m' → (virtual-key codes, 'Ctrl+Shift+M'); refuses shortcuts that close or type."""
    parts = [part for part in re.split(r"\s*[+\-]\s*|\s+", plain(text).replace(" mais ", "+")) if part]
    names = [KEY_ALIASES.get(part, part) for part in parts]
    if not names:
        raise MappingError("Diga o atalho, por exemplo 'ctrl+shift+m'.")
    unknown = [name for name in names if name not in MODIFIERS and name not in NAMED_KEYS]
    if unknown:
        raise MappingError(f"Não conheço a tecla '{unknown[0]}'. Use nomes como ctrl, shift, alt, win, f5, m.")
    if len(set(names)) != len(names):
        raise MappingError("O atalho repete uma tecla.")
    keys = [name for name in names if name not in MODIFIERS]
    mods = [name for name in names if name in MODIFIERS]
    if frozenset(names) in DANGEROUS_KEYS or ("alt" in mods and "f4" in keys):
        raise MappingError(f"O atalho {'+'.join(names)} fecha ou apaga algo. {DANGEROUS_REFUSAL}")
    if len(keys) != 1:
        raise MappingError("Um atalho de gesto tem uma tecla principal, com ou sem ctrl/shift/alt/win.")
    if not (set(mods) - {"shift"}) and keys[0] not in STANDALONE_KEYS:
        raise MappingError("Uma tecla sozinha (ou só com shift) digitaria algo; use com ctrl, alt ou win, ou uma tecla F.")
    ordered = sorted(mods, key=list(MODIFIERS).index) + keys
    codes = tuple(MODIFIERS.get(name) or NAMED_KEYS[name] for name in ordered)
    label = "+".join(name.capitalize() if len(name) > 1 else name.upper() for name in ordered)
    return codes, label


# ───────────────────────── ligações ─────────────────────────


@dataclass(frozen=True)
class Binding:
    kind: str  # acao | layout | app | site | atalho
    value: str  # id da ação, nome do layout/app, endereço do site ou o atalho já formatado
    keys: tuple[int, ...] = ()

    @property
    def label(self) -> str:
        if self.kind == "acao":
            return ACTIONS[self.value]
        if self.kind == "layout":
            return f"aplicar o layout '{self.value}'"
        if self.kind == "app":
            return f"abrir o app {self.value}"
        if self.kind == "site":
            return f"abrir o site {self.value}"
        return f"apertar {self.value}"

    def to_json(self) -> dict[str, str]:
        field = {"acao": "acao", "layout": "nome", "app": "nome", "site": "url", "atalho": "teclas"}[self.kind]
        return {"tipo": self.kind, field: self.value}


def find_action(text: str) -> str:
    key = plain(text).replace(" ", "_")
    if key in ACTIONS:
        return key
    spoken = plain(text)
    if spoken in ACTION_ALIASES:
        return ACTION_ALIASES[spoken]
    if DANGEROUS_ACTIONS.search(spoken):
        raise MappingError(DANGEROUS_REFUSAL)
    words = set(spoken.split())
    for alias, action in sorted(ACTION_ALIASES.items(), key=lambda item: -len(item[0])):
        if set(alias.split()) <= words:
            return action
    options = ", ".join(ACTIONS)
    raise MappingError(f"Não conheço a ação '{text}'. Ações: {options}.")


def parse_binding(entry: Any) -> Binding | None:
    """One gestos.json entry → Binding (None for 'nada'); MappingError when it is not allowed."""
    if not isinstance(entry, dict):
        raise MappingError("Cada gesto precisa de um objeto com 'tipo'.")
    kind = plain(entry.get("tipo", ""))
    kind = VOICE_KINDS.get(kind, kind)
    if kind == "nada":
        return None
    if kind == "acao":
        return Binding("acao", find_action(str(entry.get("acao") or "")))
    if kind == "atalho":
        codes, label = parse_keys(str(entry.get("teclas") or ""))
        return Binding("atalho", label, codes)
    if kind in ("layout", "app", "site"):
        value = " ".join(str(entry.get("url" if kind == "site" else "nome") or "").split())
        if not value:
            raise MappingError(f"Diga o {'endereço do site' if kind == 'site' else 'nome do ' + kind}.")
        if len(value) > 120:
            raise MappingError("Nome longo demais.")
        if kind == "app":
            from pc_control import is_blocked_app  # o mesmo bloqueio de instaladores da voz

            if is_blocked_app(value) or DANGEROUS_ACTIONS.search(plain(value)):
                raise MappingError(f"'{value}' não pode ficar num gesto.")
        return Binding(kind, value)
    raise MappingError("Tipo de ação desconhecido: use acao, layout, app, site, atalho ou nada.")


def find_gesture(text: str | None) -> str:
    spoken = plain(text or "")
    if not spoken:
        raise MappingError("Diga qual gesto, por exemplo 'joinha' ou 'rock'.")
    key = spoken.replace(" ", "_")
    if key in GESTURES:
        return key
    names = {
        gesture: {plain(info.name), plain(info.name.split(" (")[0]), *(plain(alias) for alias in info.aliases)}
        for gesture, info in GESTURES.items()
    }
    exact = [gesture for gesture, options in names.items() if spoken in options]
    if exact:
        return exact[0]
    loose = [
        gesture
        for gesture, options in names.items()
        if any(len(name) > 2 and (name in spoken or spoken in name) for name in options)
    ]
    if len(loose) == 1:
        return loose[0]
    if loose:
        raise MappingError(f"Qual deles: {' ou '.join(GESTURES[gesture].name for gesture in loose)}?")
    fixed = [name for name, _ in FIXED_GESTURES if plain(name) in spoken or spoken in plain(name)]
    if fixed:
        raise MappingError(
            f"'{fixed[0]}' é um gesto fixo do controle de janelas e não muda. "
            f"Os personalizáveis são: {', '.join(info.name for info in GESTURES.values())}."
        )
    raise MappingError(f"Não conheço o gesto '{text}'. Os personalizáveis são: {', '.join(info.name for info in GESTURES.values())}.")


_CACHE: dict[Path, tuple[float, dict[str, Binding | None]]] = {}


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("O %s está ilegível; usando os gestos padrão.", path.name)
        return {}
    return data if isinstance(data, dict) else {}


def load_bindings(path: Path | None = None) -> dict[str, Binding | None]:
    """Every customizable gesture → its binding (defaults + gestos.json, invalid entries skipped)."""
    path = path or GESTURES_FILE
    try:
        stamp = path.stat().st_mtime
    except OSError:
        stamp = -1.0
    cached = _CACHE.get(path)
    if cached and cached[0] == stamp:
        return dict(cached[1])
    bindings = {gesture: parse_binding(info.default) if info.default else None for gesture, info in GESTURES.items()}
    for gesture, entry in _read(path).items():
        if gesture not in GESTURES:
            logger.warning("gestos.json: gesto desconhecido '%s' ignorado.", gesture)
            continue
        try:
            bindings[gesture] = parse_binding(entry)
        except MappingError as exc:
            logger.warning("gestos.json: '%s' ignorado (%s)", gesture, exc)
    _CACHE[path] = (stamp, bindings)
    return dict(bindings)


def binding_for(gesture: str, path: Path | None = None) -> Binding | None:
    return load_bindings(path).get(gesture)


def _write(data: dict[str, Any], path: Path) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    _CACHE.pop(path, None)


def _action_text(binding: Binding | None) -> str:
    return binding.label if binding else "nada (livre para personalizar)"


def describe(gesture: str, binding: Binding | None) -> str:
    return f"{GESTURES[gesture].name}: {_action_text(binding)}"


def set_binding(gesture: str, kind: str, value: str | None, path: Path | None = None) -> str:
    path = path or GESTURES_FILE
    gesture = find_gesture(gesture)
    kind = VOICE_KINDS.get(kind, kind)
    field = {"acao": "acao", "layout": "nome", "app": "nome", "site": "url", "atalho": "teclas"}.get(kind, "valor")
    binding = parse_binding({"tipo": kind, field: value or ""})
    data = _read(path)
    data[gesture] = binding.to_json() if binding else {"tipo": "nada"}
    _write(data, path)
    info = GESTURES[gesture]
    if binding is None:
        return f"Pronto: {info.name} não faz mais nada."
    note = " Se esse layout ainda não existir, salve um com esse nome." if kind == "layout" else ""
    return f"Pronto: {info.name} agora vai {binding.label}.{note}"


def reset_binding(gesture: str | None, path: Path | None = None) -> str:
    path = path or GESTURES_FILE
    if not (gesture or "").strip():
        if path.exists():
            _write({}, path)
        return "Todos os gestos voltaram ao padrão."
    gesture = find_gesture(gesture)
    data = _read(path)
    data.pop(gesture, None)
    _write(data, path)
    return f"{GESTURES[gesture].name} voltou ao padrão: {_action_text(binding_for(gesture, path))}."


def explain(gesture: str | None, path: Path | None = None) -> str:
    gesture = find_gesture(gesture)
    info = GESTURES[gesture]
    binding = binding_for(gesture, path)
    action = binding.label if binding else "nada por enquanto (dá para ligar a uma ação)"
    return f"{info.name[0].upper()}{info.name[1:]} ({info.how}): {action}."


def list_gestures(path: Path | None = None) -> str:
    bindings = load_bindings(path)
    custom = "; ".join(describe(gesture, bindings[gesture]) for gesture in GESTURES)
    fixed = "; ".join(f"{name}: {what}" for name, what in FIXED_GESTURES)
    return f"Gestos personalizáveis — {custom}. Fixos — {fixed}."


# ───────────────────────── painel Gestos do HUD ─────────────────────────


def catalog(path: Path | None = None) -> dict[str, Any]:
    """Everything the HUD's Gestos panel shows and edits: each customizable gesture with how to do
    it, what it does now and by default, which ones do the same thing, and the reference lists."""
    bindings = load_bindings(path)
    owners: dict[Binding, list[str]] = {}
    for gesture, binding in bindings.items():
        if binding is not None:
            owners.setdefault(binding, []).append(gesture)
    gestures = []
    for gesture, info in GESTURES.items():
        binding = bindings[gesture]
        default = parse_binding(info.default) if info.default else None
        twins = [GESTURES[other].name for other in owners.get(binding, []) if other != gesture] if binding else []
        gestures.append(
            {
                "id": gesture,
                "name": info.name,
                "how": info.how,
                "binding": binding.to_json() if binding else {"tipo": "nada"},
                "label": _action_text(binding),
                "default": _action_text(default),
                "custom": binding != default,
                "same_as": twins,
            }
        )
    return {
        "gestures": gestures,
        "fixed": [{"name": name, "what": what} for name, what in FIXED_GESTURES],
        "actions": [{"id": action, "label": label} for action, label in ACTIONS.items()],
    }
