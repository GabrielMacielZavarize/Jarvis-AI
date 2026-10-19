from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv

load_dotenv()

SUPPORTED_BACKENDS = (
    "gemini-realtime",
    "openai-realtime",
    "openai-compatible-pipeline",
)
DEFAULT_GOOGLE_MODEL = "gemini-3.8-live"
# Servidor do HUD (server.py). O worker do agente pede a câmera a ele por HTTP;
# o jarvis.py passa a porta certa em JARVIS_HUD_URL.
DEFAULT_HUD_URL = "http://127.0.0.1:8000"
# Modelo de visão (API normal, não Live) que acha na tela o que o Jarvis vai clicar.
DEFAULT_COMPUTER_USE_MODEL = "gemini-3.8-flash"
# "gemini-3.8-live", "gemini-3.8-live-extended-thinking", "gemini-live-2.5-flash-native-audio",
# "gemini-2.5-flash-native-audio-preview-12-2025"...
GOOGLE_LIVE_MODEL_PATTERN = re.compile(r"(^|-)live(-|$)|-native-audio")
# Valores de exemplo do .env.example que ainda não foram trocados por credenciais reais.
PLACEHOLDER_PREFIXES = ("your-", "sua-", "seu-", "wss://your-project", "wss://seu-projeto")

RUNTIME_COMMANDS = {"console", "dev", "start", "connect"}
LIVEKIT_COMMANDS = {"dev", "start", "connect"}
HELP_FLAGS = {"-h", "--help"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}
DEFAULT_WAKE_THRESHOLD = 0.5
DEFAULT_WAKE_SILENCE_SECONDS = 30
# Voz do Gemini Live: grave e calma, a mais parecida com o Jarvis do filme (lista em voices.py).
DEFAULT_VOICE = "Charon"
DEFAULT_CALENDAR_REMINDER_MINUTES = 10
# Horário de silêncio dos avisos proativos (PRO-28): só o crítico fala.
DEFAULT_QUIET_HOURS = "23:00-07:00"
CLOCK_RANGE = re.compile(r"^\s*(\d{1,2})(?:[:h](\d{2}))?h?\s*(?:-|a|as|às|até|ate)\s*(\d{1,2})(?:[:h](\d{2}))?h?\s*$", re.IGNORECASE)
DEFAULT_PRESENCE_AWAY_MINUTES = 5


class SettingsError(ValueError):
    """Raised when the environment configuration is invalid."""


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if cleaned.lower().startswith(PLACEHOLDER_PREFIXES):
        return None
    return cleaned or None


def _parse_bool(raw_value: str | None, env_name: str, default: bool = False) -> bool:
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False

    raise SettingsError(
        f"Valor inválido em {env_name}: {raw_value!r}. "
        "Use true/false, yes/no, on/off ou 1/0."
    )


def _parse_number(
    raw_value: str | None, env_name: str, default: float, minimum: float, maximum: float
) -> float:
    cleaned = _clean_optional(raw_value)
    if cleaned is None:
        return default
    try:
        value = float(cleaned.replace(",", "."))
    except ValueError:
        raise SettingsError(f"Valor inválido em {env_name}: {raw_value!r}. Use um número.") from None
    if not minimum <= value <= maximum:
        raise SettingsError(f"{env_name} precisa estar entre {minimum:g} e {maximum:g} (veio {value:g}).")
    return value


def _parse_wake_silence(raw_value: str | None) -> int:
    """0 keeps the link open until "tchau, Jarvis" or the button, as without the wake word."""
    env_name = "JARVIS_WAKE_SILENCE_SECONDS"
    seconds = int(_parse_number(raw_value, env_name, DEFAULT_WAKE_SILENCE_SECONDS, 0, 3600))
    if 0 < seconds < 10:
        raise SettingsError(f"{env_name} precisa ser 0 (nunca encerrar) ou pelo menos 10 segundos.")
    return seconds


def _parse_voice(env_map: Mapping[str, str]) -> str:
    """JARVIS_VOICE (VOZ-30) wins over the older GOOGLE_VOICE; names are fixed to the exact case."""
    raw = _clean_optional(env_map.get("JARVIS_VOICE")) or _clean_optional(env_map.get("GOOGLE_VOICE"))
    if raw is None:
        return DEFAULT_VOICE
    from voices import canonical_voice

    return canonical_voice(raw) or raw


def parse_clock_range(raw_value: str) -> tuple[int, int] | None:
    """"23:00-07:00", "23h-7h" or "23-7" -> (1380, 420) in minutes; None when it is not a range."""
    match = CLOCK_RANGE.match(raw_value)
    if not match:
        return None
    start_h, start_m, end_h, end_m = (int(group or 0) for group in match.groups())
    if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
        return None
    start, end = start_h * 60 + start_m, end_h * 60 + end_m
    return (start, end) if start != end else None


def _parse_quiet_hours(raw_value: str | None) -> tuple[int, int] | None:
    """None turns the quiet hours off ("off", "false", "0")."""
    env_name = "JARVIS_QUIET_HOURS"
    cleaned = _clean_optional(raw_value)
    if cleaned is None:
        cleaned = DEFAULT_QUIET_HOURS
    if cleaned.lower() in FALSY_VALUES or cleaned.lower() in {"nenhum", "desligado"}:
        return None
    window = parse_clock_range(cleaned)
    if window is None:
        raise SettingsError(f"Valor inválido em {env_name}: {raw_value!r}. Use algo como 23:00-07:00 ou off.")
    return window


def _parse_csv(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None:
        return ()

    values = []
    seen = set()
    for part in raw_value.split(","):
        normalized = part.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
    return tuple(values)


def _is_google_live_model(model_name: str | None) -> bool:
    if not model_name:
        return True
    return GOOGLE_LIVE_MODEL_PATTERN.search(model_name) is not None


def get_cli_command(argv: list[str]) -> str | None:
    for arg in argv:
        if not arg.startswith("-"):
            return arg
    return None


def should_validate_runtime_command(argv: list[str]) -> bool:
    if any(arg in HELP_FLAGS for arg in argv):
        return False

    return get_cli_command(argv) in RUNTIME_COMMANDS


@dataclass(frozen=True, slots=True)
class Settings:
    backend: str = "gemini-realtime"
    google_api_key: str | None = None
    google_model: str = DEFAULT_GOOGLE_MODEL
    google_voice: str = DEFAULT_VOICE
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_realtime_model: str = "gpt-realtime"
    openai_voice: str = "marin"
    openai_llm_model: str = "gpt-4.1"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "ash"
    email_tool_enabled: bool = False
    pc_control_enabled: bool = False
    app_install_enabled: bool = False
    camera_enabled: bool = False
    camera_device: str | None = None
    hud_url: str = DEFAULT_HUD_URL
    gestures_enabled: bool = False
    computer_use_enabled: bool = False
    computer_use_model: str = DEFAULT_COMPUTER_USE_MODEL
    memory_enabled: bool = True
    routines_enabled: bool = True
    calendar_enabled: bool = False
    calendar_reminder_minutes: int = DEFAULT_CALENDAR_REMINDER_MINUTES
    home_city: str | None = None
    transcription_hints: bool = False
    wake_word_enabled: bool = False
    wake_threshold: float = DEFAULT_WAKE_THRESHOLD
    wake_silence_seconds: int = DEFAULT_WAKE_SILENCE_SECONDS
    wake_mic: str | None = None
    proactive_enabled: bool = False
    quiet_hours: tuple[int, int] | None = (23 * 60, 7 * 60)
    downloads_dir: str | None = None
    presence_enabled: bool = False
    presence_away_minutes: float = DEFAULT_PRESENCE_AWAY_MINUTES
    presence_lock: bool = False
    lan_enabled: bool = False
    allowed_emails: tuple[str, ...] = ()
    gmail_user: str | None = None
    gmail_app_password: str | None = None
    livekit_url: str | None = None
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env_map = os.environ if env is None else env

        backend = _clean_optional(env_map.get("JARVIS_BACKEND")) or "gemini-realtime"
        if backend not in SUPPORTED_BACKENDS:
            supported = ", ".join(SUPPORTED_BACKENDS)
            raise SettingsError(
                f"JARVIS_BACKEND inválido: {backend!r}. Valores suportados: {supported}."
            )

        return cls(
            backend=backend,
            google_api_key=_clean_optional(env_map.get("GOOGLE_API_KEY")),
            google_model=(
                _clean_optional(env_map.get("GOOGLE_MODEL"))
                or DEFAULT_GOOGLE_MODEL
            ),
            google_voice=_parse_voice(env_map),
            openai_api_key=_clean_optional(env_map.get("OPENAI_API_KEY")),
            openai_base_url=_clean_optional(env_map.get("OPENAI_BASE_URL")),
            openai_realtime_model=(
                _clean_optional(env_map.get("OPENAI_REALTIME_MODEL")) or "gpt-realtime"
            ),
            openai_voice=_clean_optional(env_map.get("OPENAI_VOICE")) or "marin",
            openai_llm_model=_clean_optional(env_map.get("OPENAI_LLM_MODEL")) or "gpt-4.1",
            openai_stt_model=(
                _clean_optional(env_map.get("OPENAI_STT_MODEL")) or "gpt-4o-mini-transcribe"
            ),
            openai_tts_model=(
                _clean_optional(env_map.get("OPENAI_TTS_MODEL")) or "gpt-4o-mini-tts"
            ),
            openai_tts_voice=_clean_optional(env_map.get("OPENAI_TTS_VOICE")) or "ash",
            email_tool_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_EMAIL_TOOL"),
                "JARVIS_ENABLE_EMAIL_TOOL",
                default=False,
            ),
            allowed_emails=_parse_csv(env_map.get("JARVIS_ALLOWED_EMAILS")),
            pc_control_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_PC_CONTROL"),
                "JARVIS_ENABLE_PC_CONTROL",
                default=False,
            ),
            app_install_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_APP_INSTALL"),
                "JARVIS_ENABLE_APP_INSTALL",
                default=False,
            ),
            camera_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_CAMERA"),
                "JARVIS_ENABLE_CAMERA",
                default=False,
            ),
            camera_device=_clean_optional(env_map.get("JARVIS_CAMERA")),
            hud_url=(_clean_optional(env_map.get("JARVIS_HUD_URL")) or DEFAULT_HUD_URL).rstrip("/"),
            gestures_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_GESTURES"),
                "JARVIS_ENABLE_GESTURES",
                default=False,
            ),
            computer_use_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_COMPUTER_USE"),
                "JARVIS_ENABLE_COMPUTER_USE",
                default=False,
            ),
            computer_use_model=(
                _clean_optional(env_map.get("JARVIS_COMPUTER_USE_MODEL")) or DEFAULT_COMPUTER_USE_MODEL
            ),
            memory_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_MEMORY"),
                "JARVIS_ENABLE_MEMORY",
                default=True,
            ),
            routines_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_ROUTINES"),
                "JARVIS_ENABLE_ROUTINES",
                default=True,
            ),
            calendar_enabled=_parse_bool(
                env_map.get("JARVIS_ENABLE_CALENDAR"),
                "JARVIS_ENABLE_CALENDAR",
                default=False,
            ),
            calendar_reminder_minutes=int(
                _parse_number(
                    env_map.get("JARVIS_CALENDAR_REMINDER_MINUTES"),
                    "JARVIS_CALENDAR_REMINDER_MINUTES",
                    DEFAULT_CALENDAR_REMINDER_MINUTES,
                    0,
                    240,
                )
            ),
            home_city=_clean_optional(env_map.get("JARVIS_HOME_CITY")),
            transcription_hints=_parse_bool(
                env_map.get("JARVIS_TRANSCRIPTION_HINTS"),
                "JARVIS_TRANSCRIPTION_HINTS",
                default=False,
            ),
            wake_word_enabled=_parse_bool(env_map.get("JARVIS_WAKE_WORD"), "JARVIS_WAKE_WORD", default=False),
            wake_threshold=_parse_number(
                env_map.get("JARVIS_WAKE_THRESHOLD"), "JARVIS_WAKE_THRESHOLD", DEFAULT_WAKE_THRESHOLD, 0.05, 0.99
            ),
            wake_silence_seconds=_parse_wake_silence(env_map.get("JARVIS_WAKE_SILENCE_SECONDS")),
            wake_mic=_clean_optional(env_map.get("JARVIS_WAKE_MIC")),
            proactive_enabled=_parse_bool(env_map.get("JARVIS_PROACTIVE"), "JARVIS_PROACTIVE", default=False),
            quiet_hours=_parse_quiet_hours(env_map.get("JARVIS_QUIET_HOURS")),
            downloads_dir=_clean_optional(env_map.get("JARVIS_DOWNLOADS_DIR")),
            presence_enabled=_parse_bool(env_map.get("JARVIS_PRESENCE"), "JARVIS_PRESENCE", default=False),
            presence_away_minutes=_parse_number(
                env_map.get("JARVIS_PRESENCE_AWAY_MINUTES"),
                "JARVIS_PRESENCE_AWAY_MINUTES",
                DEFAULT_PRESENCE_AWAY_MINUTES,
                1,
                240,
            ),
            presence_lock=_parse_bool(env_map.get("JARVIS_PRESENCE_LOCK"), "JARVIS_PRESENCE_LOCK", default=False),
            lan_enabled=_parse_bool(env_map.get("JARVIS_LAN"), "JARVIS_LAN", default=False),
            gmail_user=_clean_optional(env_map.get("GMAIL_USER")),
            gmail_app_password=_clean_optional(env_map.get("GMAIL_APP_PASSWORD")),
            livekit_url=_clean_optional(env_map.get("LIVEKIT_URL")),
            livekit_api_key=_clean_optional(env_map.get("LIVEKIT_API_KEY")),
            livekit_api_secret=_clean_optional(env_map.get("LIVEKIT_API_SECRET")),
        )

    @property
    def effective_allowed_emails(self) -> tuple[str, ...]:
        if self.allowed_emails:
            return self.allowed_emails
        if self.gmail_user:
            return (self.gmail_user.lower(),)
        return ()

    def backend_validation_errors(self) -> list[str]:
        errors: list[str] = []

        if self.backend == "gemini-realtime" and not self.google_api_key:
            errors.append(
                "GOOGLE_API_KEY é obrigatório quando JARVIS_BACKEND=gemini-realtime."
            )
        if self.backend == "gemini-realtime" and not _is_google_live_model(self.google_model):
            errors.append(
                "GOOGLE_MODEL precisa ser um modelo compatível com Gemini Live API. "
                f"Use '{DEFAULT_GOOGLE_MODEL}' ou outro modelo com 'live' ou "
                "'-native-audio' no nome."
            )

        if self.backend == "gemini-realtime":
            from voices import GEMINI_VOICES, canonical_voice

            if canonical_voice(self.google_voice) is None:
                errors.append(
                    f"JARVIS_VOICE inválida: {self.google_voice!r}. Vozes do Gemini Live: "
                    f"{', '.join(GEMINI_VOICES)}."
                )

        if self.computer_use_enabled and not self.google_api_key:
            errors.append(
                "GOOGLE_API_KEY é obrigatório quando JARVIS_ENABLE_COMPUTER_USE=true "
                "(o Gemini enxerga a tela para achar onde clicar)."
            )

        if self.backend in {"openai-realtime", "openai-compatible-pipeline"}:
            if not self.openai_api_key:
                errors.append(
                    "OPENAI_API_KEY é obrigatório quando "
                    f"JARVIS_BACKEND={self.backend}."
                )

        return errors

    def email_validation_errors(self) -> list[str]:
        if not self.email_tool_enabled:
            return []

        errors: list[str] = []
        if not self.gmail_user:
            errors.append(
                "GMAIL_USER é obrigatório quando JARVIS_ENABLE_EMAIL_TOOL=true."
            )
        if not self.gmail_app_password:
            errors.append(
                "GMAIL_APP_PASSWORD é obrigatório quando JARVIS_ENABLE_EMAIL_TOOL=true."
            )
        if not self.effective_allowed_emails:
            errors.append(
                "Defina GMAIL_USER ou JARVIS_ALLOWED_EMAILS para liberar "
                "pelo menos um destinatário autorizado."
            )

        return errors

    def livekit_validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.livekit_url:
            errors.append("LIVEKIT_URL não está configurada.")
        if not self.livekit_api_key:
            errors.append("LIVEKIT_API_KEY não está configurada.")
        if not self.livekit_api_secret:
            errors.append("LIVEKIT_API_SECRET não está configurada.")
        return errors

    def validation_errors_for_command(self, command: str | None) -> list[str]:
        errors = [*self.backend_validation_errors(), *self.email_validation_errors()]

        if command in LIVEKIT_COMMANDS:
            errors.extend(self.livekit_validation_errors())

        return errors

    def validate_for_command(self, command: str | None) -> None:
        errors = self.validation_errors_for_command(command)
        if errors:
            raise SettingsError(self.format_errors(errors))

    def format_errors(self, errors: list[str]) -> str:
        details = "\n".join(f"- {error}" for error in errors)
        return (
            f"Configuração inválida para o backend '{self.backend}'.\n"
            f"{details}"
        )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    return Settings.from_env(env=env)
