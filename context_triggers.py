"""Rotinas por contexto (ROT-24): a rotina roda sozinha quando algo acontece no PC.

"Quando eu abrir o PhpStorm, roda o modo foco"; "quando eu conectar o fone, põe o lo-fi";
"quando eu voltar para o PC, roda o bom dia". Os gatilhos ficam em ``rotinas.json``, no campo
``triggers`` de cada rotina, e são criados por voz com ``set_routine_trigger``:

    "triggers": [{"when": "app", "value": "PhpStorm", "enabled": true, "cooldown_minutes": 30}]

O ``ContextWatcher`` roda no processo do servidor do HUD, ao lado do agendador. A cada poucos
segundos ele consulta só as sondas que algum gatilho usa (processos, janela em foco, aparelhos
de áudio, Wi-Fi e a presença da webcam) e dispara a rotina na borda, quando a condição passa de
falsa para verdadeira. A rotina segue o mesmo caminho das agendadas: fica pendente no
``RoutineScheduler`` e o link abre pelo ``wake_hub``; com a conversa aberta, ela roda nela.

Proteções:
- Borda, não estado: o que já estava aberto quando o Jarvis ligou não dispara nada, e uma
  condição que continua verdadeira não dispara de novo.
- Intervalo mínimo por rotina (``JARVIS_CONTEXT_COOLDOWN_MINUTES`` ou ``cooldown_minutes``) e
  um intervalo global entre duas rotinas por contexto, para uma rotina que abre um app não
  disparar outra em cadeia.
- Desligável por gatilho (``"enabled": false``) e de uma vez (``JARVIS_CONTEXT_TRIGGERS=false``).
- A rotina roda por ``execute_routine``: passos perigosos continuam esperando o "sim".
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from livekit.agents import RunContext, function_tool

from routines import NOT_ASKED, RoutineError, _asks_about, _plain, _wait_for_user, find_routine, load_routines, save_routines

logger = logging.getLogger("jarvis-context")

MAX_TRIGGERS = 4
MAX_VALUE_CHARS = 60
DEFAULT_COOLDOWN_MINUTES = 30.0
# Entre duas rotinas por contexto quaisquer: corta cadeias (uma rotina abre o app que dispara outra).
GLOBAL_GAP_S = 90.0
WATCH_TICK_S = 3.0
# De quanto em quanto tempo cada sonda é consultada (o resto do tempo vale a última leitura).
PROBE_INTERVALS = {"processes": 5.0, "foreground": 3.0, "presence": 3.0, "audio": 15.0, "wifi": 30.0}
PROBE_TIMEOUT_S = 5.0

TriggerKind = Literal["app", "foco", "audio", "chegar", "sair", "wifi"]


@dataclass(frozen=True, slots=True)
class Kind:
    probe: str
    needs_value: bool
    example: str


KINDS: dict[str, Kind] = {
    "app": Kind("processes", True, "app: PhpStorm (quando o app abrir)"),
    "foco": Kind("foreground", True, "foco: PhpStorm (quando a janela dele ficar em primeiro plano)"),
    "audio": Kind("audio", False, "audio: WH-1000XM4 (ou vazio: qualquer fone)"),
    "chegar": Kind("presence", False, "chegar (quando você volta para a frente do PC)"),
    "sair": Kind("presence", False, "sair (quando você sai da frente do PC)"),
    "wifi": Kind("wifi", True, "wifi: NomeDaRede"),
}
KIND_ALIASES = {
    "abrir": "app", "abre": "app", "aberto": "app", "open": "app", "processo": "app", "programa": "app",
    "focus": "foco", "primeiro_plano": "foco", "janela": "foco", "em_foco": "foco",
    "fone": "audio", "fones": "audio", "headset": "audio", "bluetooth": "audio", "som": "audio", "dispositivo_de_audio": "audio",
    "chegada": "chegar", "voltar": "chegar", "volta": "chegar", "arrive": "chegar", "presenca": "chegar",
    "saida": "sair", "sai": "sair", "leave": "sair", "ausente": "sair",
    "rede": "wifi", "wi_fi": "wifi", "wlan": "wifi",
}
# Sem nome de aparelho, "audio" vale para o que parece fone.
HEADPHONE_WORDS = ("fone", "headphone", "headset", "earbud", "airpods", "buds", "hands-free", "handsfree", "bluetooth")
# Nome que o usuário fala -> começo do nome do processo.
APP_PROCESSES = {
    "visualstudiocode": ("code",),
    "vscode": ("code",),
    "googlechrome": ("chrome",),
    "microsoftedge": ("msedge",),
    "edge": ("msedge",),
    "word": ("winword",),
    "powerpoint": ("powerpnt",),
    "teams": ("msteams", "ms-teams", "teams"),
    "intellij": ("idea",),
    "intellijidea": ("idea",),
    "androidstudio": ("studio",),
    "obs": ("obs",),
    "obsstudio": ("obs",),
}


def _app_key(text: str) -> str:
    plain = _plain(text)
    plain = re.sub(r"\.exe$", "", plain)
    return re.sub(r"[^a-z0-9]", "", plain)


def parse_kind(when: str) -> str:
    key = re.sub(r"[\s-]+", "_", _plain(when or ""))
    kind = key if key in KINDS else KIND_ALIASES.get(key)
    if kind is None:
        raise RoutineError(f"Não conheço o gatilho '{when}'. Use: {', '.join(KINDS)}.")
    return kind


def parse_trigger(when: str, value: str | None = None, *, cooldown_minutes: float | None = None, enabled: bool = True) -> dict[str, Any]:
    """ "app", "PhpStorm" -> {"when": "app", "value": "PhpStorm", "enabled": True}."""
    kind = parse_kind(when)
    value = re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_VALUE_CHARS]
    if kind in {"chegar", "sair"}:
        value = ""
    if KINDS[kind].needs_value and not value:
        raise RoutineError(f"O gatilho '{kind}' precisa de um nome, por exemplo '{KINDS[kind].example}'.")
    trigger: dict[str, Any] = {"when": kind, "value": value, "enabled": bool(enabled)}
    if cooldown_minutes is not None:
        if not 1 <= float(cooldown_minutes) <= 24 * 60:
            raise RoutineError("O intervalo mínimo de um gatilho fica entre 1 minuto e 24 horas.")
        trigger["cooldown_minutes"] = float(cooldown_minutes)
    return trigger


def valid_triggers(raw: Any) -> list[dict[str, Any]]:
    """The valid triggers of a routine read from the file (the broken ones are left out)."""
    triggers: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            trigger = parse_trigger(
                str(item.get("when", "")),
                item.get("value"),
                cooldown_minutes=item.get("cooldown_minutes"),
                enabled=item.get("enabled", True) is not False,
            )
        except (RoutineError, TypeError, ValueError):
            logger.warning("Gatilho ignorado: %r", item)
            continue
        if not any(_same(trigger, other) for other in triggers):
            triggers.append(trigger)
    return triggers[:MAX_TRIGGERS]


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["when"] == b["when"] and _plain(a["value"]) == _plain(b["value"])


def describe_trigger(trigger: dict[str, Any]) -> str:
    kind, value = trigger["when"], trigger["value"]
    text = {
        "app": f"quando o {value} abrir",
        "foco": f"quando o {value} ficar em foco",
        "audio": f"quando o aparelho de áudio {value} conectar" if value else "quando um fone conectar",
        "chegar": "quando você voltar para a frente do PC",
        "sair": "quando você sair da frente do PC",
        "wifi": f"quando o PC entrar na rede Wi-Fi {value}",
    }[kind]
    return text if trigger.get("enabled", True) else text + " (desligado)"


def describe_triggers(routine: dict[str, Any]) -> str | None:
    triggers = routine.get("triggers") or []
    return "; ".join(describe_trigger(trigger) for trigger in triggers) or None


# ───────────────────────── sondas ─────────────────────────


class Probes(Protocol):
    def processes(self) -> set[str] | None: ...

    def foreground(self) -> str | None: ...

    def audio_devices(self) -> set[str] | None: ...

    def wifi(self) -> str | None: ...


def _run(command: list[str]) -> str | None:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        done = subprocess.run(command, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


class SystemProbes:
    """The real probes. Processes work everywhere; focus and audio only on Windows."""

    def processes(self) -> set[str] | None:
        import psutil

        names = set()
        for process in psutil.process_iter(["name"]):
            name = process.info.get("name")
            if name:
                names.add(name)
        return names

    def foreground(self) -> str | None:
        if sys.platform != "win32":
            return None
        import ctypes
        from ctypes import wintypes

        import psutil

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            return psutil.Process(pid.value).name()
        except psutil.Error:
            return ""

    def audio_devices(self) -> set[str] | None:
        if sys.platform != "win32":
            return None
        import comtypes
        from pycaw.pycaw import AudioUtilities

        comtypes.CoInitialize()
        try:
            names = set()
            for device in AudioUtilities.GetAllDevices():
                state = getattr(device, "state", None)
                # DEVICE_STATE_ACTIVE = 1: aparelho conectado e pronto.
                if getattr(state, "value", state) == 1 and device.FriendlyName:
                    names.add(str(device.FriendlyName))
            return names
        finally:
            comtypes.CoUninitialize()

    def wifi(self) -> str | None:
        if sys.platform == "win32":
            output = _run(["netsh", "wlan", "show", "interfaces"])
            if output is None:
                return None
            match = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", output, re.MULTILINE)
            return match.group(1) if match else ""
        if sys.platform.startswith("linux"):
            output = _run(["iwgetid", "-r"])
            return output.strip() if output is not None else None
        return None


# ───────────────────────── condições ─────────────────────────


def app_matches(value: str, process: str) -> bool:
    wanted = _app_key(value)
    name = _app_key(process)
    if not wanted or not name:
        return False
    starts = APP_PROCESSES.get(wanted, (wanted,))
    return any(name == start.replace("-", "") or name.startswith(start.replace("-", "")) for start in starts)


def audio_matches(value: str, device: str) -> bool:
    plain = _plain(device)
    if value:
        return _plain(value) in plain
    return any(word in plain for word in HEADPHONE_WORDS)


def condition(trigger: dict[str, Any], snapshot: dict[str, Any]) -> bool | None:
    """Whether the trigger's situation holds now; None when the probe could not tell."""
    kind, value = trigger["when"], trigger["value"]
    reading = snapshot.get(KINDS[kind].probe)
    if reading is None:
        return None
    if kind == "app":
        return any(app_matches(value, name) for name in reading)
    if kind == "foco":
        return bool(reading) and app_matches(value, reading)
    if kind == "audio":
        return any(audio_matches(value, name) for name in reading)
    if kind == "wifi":
        return _plain(reading) == _plain(value)
    if reading not in {"present", "away"}:
        return None  # presença desligada ou ainda verificando
    return reading == ("present" if kind == "chegar" else "away")


def reason_text(trigger: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Why the routine ran, for Jarvis to say ("o PhpStorm abriu")."""
    kind, value = trigger["when"], trigger["value"]
    if kind == "audio":
        devices = sorted(name for name in snapshot.get("audio") or () if audio_matches(value, name))
        return f"o aparelho de áudio {devices[0] if devices else value} conectou"
    return {
        "app": f"o {value} abriu",
        "foco": f"o {value} ficou em foco",
        "chegar": "você voltou para a frente do computador",
        "sair": "você saiu da frente do computador",
        "wifi": f"o computador entrou na rede Wi-Fi {value}",
    }[kind]


# ───────────────────────── vigia ─────────────────────────


class ContextWatcher:
    """Runs in the HUD server: watches what the triggers need and fires routines on the edge.

    ``fire(key, reason)`` hands the routine to the same path as the scheduled ones; ``presence()``
    returns the PresenceService state ("present", "away", "unknown" or "off"); ``clock`` is a
    monotonic clock (tests pass a fake one).
    """

    def __init__(
        self,
        *,
        fire: Callable[[str, str], Any] | None = None,
        load: Callable[[], dict[str, dict[str, Any]]] = load_routines,
        probes: Probes | None = None,
        presence: Callable[[], str | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cooldown_minutes: Callable[[], float] | float = DEFAULT_COOLDOWN_MINUTES,
        gap_s: float = GLOBAL_GAP_S,
    ) -> None:
        self.fire = fire
        self._load = load
        self.probes = probes or SystemProbes()
        self.presence = presence
        self._clock = clock
        self._cooldown = cooldown_minutes
        self.gap_s = gap_s
        self.readings: dict[str, Any] = {}
        self._read_at: dict[str, float] = {}
        self.states: dict[tuple[str, str, str], bool | None] = {}
        self.last_fired: dict[str, float] = {}
        self.last_any = -math.inf

    def reset(self) -> None:
        """Forget what was seen: turning it back on takes a new baseline (nothing fires at once)."""
        self.readings.clear()
        self._read_at.clear()
        self.states.clear()

    def trigger_count(self) -> int:
        try:
            return sum(1 for routine in self._load().values() for trigger in routine.get("triggers") or [] if trigger.get("enabled", True))
        except Exception:
            return 0

    def _default_cooldown_s(self) -> float:
        value = self._cooldown() if callable(self._cooldown) else self._cooldown
        return float(value) * 60

    def _read(self, probe: str) -> Any:
        if probe == "presence":
            return self.presence() if self.presence is not None else None
        method = {"processes": "processes", "foreground": "foreground", "audio": "audio_devices", "wifi": "wifi"}[probe]
        return getattr(self.probes, method)()

    def _snapshot(self, probes: set[str], now: float) -> dict[str, Any]:
        for probe in list(self.readings):
            if probe not in probes:
                self.readings.pop(probe, None)
                self._read_at.pop(probe, None)
        for probe in probes:
            if probe in self._read_at and now - self._read_at[probe] < PROBE_INTERVALS[probe]:
                continue
            try:
                self.readings[probe] = self._read(probe)
            except Exception:
                logger.debug("Sonda '%s' falhou.", probe, exc_info=True)
                self.readings[probe] = None
            self._read_at[probe] = now
        return dict(self.readings)

    def check(self) -> list[tuple[str, str]]:
        """Routines whose trigger fired now, as (key, reason). Reads the probes; fires nothing."""
        now = self._clock()
        try:
            routines = self._load()
        except Exception:
            logger.exception("Não foi possível ler as rotinas com gatilho.")
            return []
        active = [
            (key, routine, trigger)
            for key, routine in routines.items()
            for trigger in routine.get("triggers") or []
            if trigger.get("enabled", True)
        ]
        snapshot = self._snapshot({KINDS[trigger["when"]].probe for _, _, trigger in active}, now)
        seen: set[tuple[str, str, str]] = set()
        edges: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for key, routine, trigger in active:
            ident = (key, trigger["when"], _plain(trigger["value"]))
            seen.add(ident)
            current = condition(trigger, snapshot)
            previous = self.states.get(ident)
            self.states[ident] = current
            # Só a passagem de falso para verdadeiro dispara; a primeira leitura é a base.
            if previous is False and current is True and key not in edges:
                edges[key] = (routine, trigger)
        for ident in list(self.states):
            if ident not in seen:
                del self.states[ident]

        fired: list[tuple[str, str]] = []
        for key, (routine, trigger) in edges.items():
            cooldown = float(trigger.get("cooldown_minutes") or 0) * 60 or self._default_cooldown_s()
            if now - self.last_fired.get(key, -math.inf) < cooldown:
                logger.info("Gatilho de '%s' ignorado: a rotina rodou há pouco.", routine["name"])
                continue
            if now - self.last_any < self.gap_s:
                logger.info("Gatilho de '%s' ignorado: outra rotina por contexto acabou de rodar.", routine["name"])
                continue
            reason = reason_text(trigger, snapshot)
            self.last_fired[key] = now
            self.last_any = now
            fired.append((key, reason))
            logger.info("Rotina '%s' disparada por contexto: %s.", routine["name"], reason)
        return fired

    def deliver(self, fired: list[tuple[str, str]]) -> None:
        for key, reason in fired:
            if self.fire is None:
                return
            try:
                self.fire(key, reason)
            except Exception:
                logger.exception("Falha ao disparar a rotina '%s'.", key)

    def tick(self) -> list[tuple[str, str]]:
        fired = self.check()
        self.deliver(fired)
        return fired

    async def run_forever(self, enabled: Callable[[], bool], interval: float = WATCH_TICK_S) -> None:
        was_on = False
        while True:
            try:
                on = enabled()
                if on:
                    # As sondas chamam processos e APIs do sistema: fora do laço de eventos. A entrega
                    # fica no laço, porque vai para as filas asyncio das abas do HUD.
                    self.deliver(await asyncio.to_thread(self.check))
                elif was_on:
                    self.reset()
                was_on = on
            except Exception:
                logger.exception("Falha no vigia das rotinas por contexto.")
            await asyncio.sleep(interval)


# ───────────────────────── ferramenta ─────────────────────────


@function_tool()
async def set_routine_trigger(
    context: RunContext,
    name: str,
    when: TriggerKind,
    value: str | None = None,
    action: Literal["add", "remove", "disable", "enable"] = "add",
    cooldown_minutes: float | None = None,
) -> str:
    """Make a routine run by itself when something happens on the PC, or undo that.

    Examples: "quando eu abrir o PhpStorm, roda o modo foco" -> name="modo foco", when="app",
    value="PhpStorm"; "quando o Spotify ficar em foco" -> when="foco"; "quando eu conectar o fone,
    põe o lo-fi" -> when="audio" (value = device name, or empty for any headphone); "quando eu
    voltar para o PC" -> when="chegar"; "quando eu sair" -> when="sair"; "quando entrar na rede
    Casa" -> when="wifi", value="Casa". The routine opens the link like a scheduled one.

    Args:
        name: The routine, e.g. "modo foco".
        when: app (an app opened), foco (its window came to the front), audio (an audio device
            connected), chegar (the user sat back down), sair (the user left), wifi (joined a network).
        value: App, device or network name; empty for chegar/sair.
        action: add, remove, disable (keep it but off) or enable.
        cooldown_minutes: Minimum time between two runs by this trigger (default from the .env).
    """
    if not await _wait_for_user(context, lambda text: _asks_about(text, (name,))):
        return NOT_ASKED
    try:
        routines = await asyncio.to_thread(load_routines)
        key = find_routine(name, routines)
        routine = routines[key]
        triggers = list(routine.get("triggers") or [])
        if action == "add":
            trigger = parse_trigger(when, value, cooldown_minutes=cooldown_minutes)
            triggers = [item for item in triggers if not _same(item, trigger)]
            if len(triggers) >= MAX_TRIGGERS:
                raise RoutineError(f"Uma rotina tem no máximo {MAX_TRIGGERS} gatilhos; tire um antes.")
            triggers.append(trigger)
            matching = [trigger]
        else:
            # Sem nome ("para de rodar quando eu sair", "tira o gatilho do app"): vale para todos daquele tipo.
            wanted = {"when": parse_kind(when), "value": str(value or "").strip()}
            matching = [item for item in triggers if item["when"] == wanted["when"] and (not wanted["value"] or _same(item, wanted))]
            if not matching:
                raise RoutineError(f"A rotina '{routine['name']}' não tem esse gatilho.")
            if action == "remove":
                triggers = [item for item in triggers if item not in matching]
            for item in matching:
                item["enabled"] = action != "disable"
        routine["triggers"] = triggers
        await asyncio.to_thread(save_routines, routines)
    except RoutineError as exc:
        return f"NADA foi mudado: {exc}"
    what = " nem ".join(describe_trigger(item) for item in matching)
    if action == "remove":
        return f"Pronto: a rotina '{routine['name']}' não roda mais {what}."
    if action == "disable":
        what = " nem ".join(describe_trigger({**item, "enabled": True}) for item in matching)
        return f"Gatilho desligado: ele fica guardado, mas a rotina '{routine['name']}' não roda {what}."
    return f"Pronto: a rotina '{routine['name']}' roda sozinha {' e '.join(describe_trigger(item) for item in matching)}. {_limits_note(matching[0])}"


def _limits_note(trigger: dict[str, Any]) -> str:
    from settings import load_settings

    notes = []
    try:
        settings = load_settings()
    except Exception:
        settings = None
    if settings is not None and not settings.context_triggers_enabled:
        notes.append("Os gatilhos estão desligados no .env (JARVIS_CONTEXT_TRIGGERS=false).")
    if trigger["when"] in {"chegar", "sair"} and settings is not None and not settings.presence_enabled:
        notes.append("Esse gatilho usa a presença pela webcam: ligue JARVIS_PRESENCE=true.")
    if trigger["when"] in {"foco", "audio"} and sys.platform != "win32":
        notes.append("Esse gatilho só funciona no Windows.")
    notes.append("Ela não repete antes do intervalo mínimo e passos perigosos ainda pedem o seu sim.")
    return " ".join(notes)
