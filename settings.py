from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv

load_dotenv()

SUPPORTED_BACKENDS = (
    "gemini-realtime",
    "openai-realtime",
    "openai-compatible-pipeline",
)
GOOGLE_LIVE_MODEL_MARKERS = ("-live-", "-native-audio-")

RUNTIME_COMMANDS = {"console", "dev", "start", "connect"}
LIVEKIT_COMMANDS = {"dev", "start", "connect"}
HELP_FLAGS = {"-h", "--help"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}


class SettingsError(ValueError):
    """Raised when the environment configuration is invalid."""


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
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
    return any(marker in model_name for marker in GOOGLE_LIVE_MODEL_MARKERS)


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
    google_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    google_voice: str = "Charon"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_realtime_model: str = "gpt-realtime"
    openai_voice: str = "marin"
    openai_llm_model: str = "gpt-4.1"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "ash"
    email_tool_enabled: bool = False
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
                or "gemini-2.5-flash-native-audio-preview-12-2025"
            ),
            google_voice=_clean_optional(env_map.get("GOOGLE_VOICE")) or "Charon",
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
                "Use algo como 'gemini-2.5-flash-native-audio-preview-12-2025' ou um modelo com "
                "'-live-' / '-native-audio-' no nome."
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
