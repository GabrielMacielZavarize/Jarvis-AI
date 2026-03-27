from __future__ import annotations

import logging
import re
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests
from ddgs import DDGS
from livekit.agents import RunContext, function_tool

from settings import Settings

logger = logging.getLogger("jarvis-tools")

PENDING_EMAIL_KEY = "pending_email"
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
WEATHER_CODES = {
    0: "Céu limpo",
    1: "Predominantemente limpo",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Névoa",
    48: "Névoa com geada",
    51: "Garoa leve",
    53: "Garoa moderada",
    55: "Garoa forte",
    61: "Chuva leve",
    63: "Chuva moderada",
    65: "Chuva forte",
    71: "Neve leve",
    73: "Neve moderada",
    75: "Neve forte",
    80: "Pancadas leves",
    81: "Pancadas moderadas",
    82: "Pancadas fortes",
    95: "Trovoada",
    96: "Trovoada com granizo leve",
    99: "Trovoada com granizo forte",
}


def _truncate(value: str, limit: int = 180) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3].rstrip()}..."


def _validate_email_address(email: str, field_name: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} não pode ser vazio.")
    if not EMAIL_PATTERN.match(normalized):
        raise ValueError(f"{field_name} precisa ser um email válido.")
    return normalized


def _get_session_state(context: RunContext) -> dict[str, Any]:
    userdata = context.userdata
    if userdata is None:
        userdata = {}
        context.session.userdata = userdata
    return userdata


def _get_last_user_message(context: RunContext) -> str | None:
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


def _format_weather(location_name: str, current: dict[str, Any]) -> str:
    required_fields = (
        "temperature_2m",
        "relative_humidity_2m",
        "weather_code",
        "wind_speed_10m",
    )
    missing = [field for field in required_fields if field not in current]
    if missing:
        missing_list = ", ".join(missing)
        raise KeyError(f"Dados do clima incompletos: {missing_list}")

    description = WEATHER_CODES.get(current["weather_code"], "Condição desconhecida")
    return (
        f"{location_name}: {description}, "
        f"{current['temperature_2m']}°C, "
        f"Umidade {current['relative_humidity_2m']}%, "
        f"Vento {current['wind_speed_10m']} km/h"
    )


@function_tool()
async def get_weather(
    context: RunContext,
    city: str,
) -> str:
    """Get the current weather for a given city.

    Args:
        city: The name of the city to get weather for.
    """
    try:
        geo_response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "pt"},
            timeout=15,
        )
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        results = geo_data.get("results")
        if not results:
            return f"Cidade '{city}' não encontrada."

        location = results[0]
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is None or lon is None:
            raise KeyError("Latitude/longitude ausentes na resposta da geocodificação.")

        city_name = location.get("name", city)
        country = location.get("country")
        location_name = f"{city_name}, {country}" if country else city_name

        weather_response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=15,
        )
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current = weather_data.get("current")
        if not isinstance(current, dict):
            raise KeyError("Resposta do clima sem bloco 'current'.")

        result = _format_weather(location_name, current)
        logger.info("Consulta de clima concluída para '%s'.", city)
        return result
    except requests.HTTPError:
        logger.warning("Falha HTTP ao consultar clima para '%s'.", city)
        return "O serviço de clima retornou um erro ao processar a consulta."
    except (KeyError, TypeError, ValueError):
        logger.warning("Resposta inválida ao consultar clima para '%s'.", city)
        return "O serviço de clima retornou dados incompletos ou inválidos."
    except requests.RequestException:
        logger.warning("Falha de rede ao consultar clima para '%s'.", city)
        return "Não foi possível consultar o clima por causa de uma falha de rede."
    except Exception:
        logger.exception("Erro inesperado ao consultar clima para '%s'.", city)
        return f"Ocorreu um erro ao buscar o clima para {city}."


@function_tool()
async def search_web(
    context: RunContext,
    query: str,
) -> str:
    """Search the web using DuckDuckGo.

    Args:
        query: The search query to look up on the web.
    """
    try:
        results = DDGS().text(query, max_results=5)
        if not results:
            return f"Nenhum resultado encontrado para '{query}'."

        lines = []
        for index, item in enumerate(results[:5], start=1):
            title = _truncate(str(item.get("title", "Sem título")))
            href = str(item.get("href", "Sem URL"))
            body = _truncate(str(item.get("body", "Sem resumo")), limit=220)
            lines.append(
                f"{index}. {title}\nURL: {href}\nResumo: {body}"
            )

        logger.info("Pesquisa web concluída para '%s'.", query)
        return "\n\n".join(lines)
    except Exception:
        logger.warning("Erro ao pesquisar na web por '%s'.", query)
        return f"Ocorreu um erro ao pesquisar na web por '{query}'."


def build_email_tools(settings: Settings) -> list[Any]:
    def _validate_recipient_policy(to_email: str, cc_email: str | None) -> None:
        allowed = set(settings.effective_allowed_emails)
        recipients = [to_email]
        if cc_email:
            recipients.append(cc_email)

        blocked = [email for email in recipients if email not in allowed]
        if blocked:
            blocked_list = ", ".join(blocked)
            raise PermissionError(
                "Envio bloqueado: destinatário fora da política permitida "
                f"({blocked_list})."
            )

    def _send_pending_email(payload: dict[str, Any]) -> None:
        msg = MIMEMultipart()
        msg["From"] = settings.gmail_user or ""
        msg["To"] = payload["to_email"]
        msg["Subject"] = payload["subject"]

        recipients = [payload["to_email"]]
        if payload.get("cc_email"):
            msg["Cc"] = payload["cc_email"]
            recipients.append(payload["cc_email"])

        msg.attach(MIMEText(payload["message"], "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.sendmail(settings.gmail_user, recipients, msg.as_string())

    @function_tool()
    async def draft_email(
        context: RunContext,
        to_email: str,
        subject: str,
        message: str,
        cc_email: str | None = None,
    ) -> str:
        """Prepare an email draft and require explicit user confirmation before sending."""
        try:
            normalized_to = _validate_email_address(to_email, "to_email")
            normalized_cc = (
                _validate_email_address(cc_email, "cc_email")
                if cc_email
                else None
            )
            trimmed_subject = subject.strip()
            trimmed_message = message.strip()

            if not trimmed_subject:
                return "Não foi possível criar o rascunho: o assunto está vazio."
            if not trimmed_message:
                return "Não foi possível criar o rascunho: a mensagem está vazia."

            _validate_recipient_policy(normalized_to, normalized_cc)

            code = f"{secrets.randbelow(1_000_000):06d}"
            state = _get_session_state(context)
            state[PENDING_EMAIL_KEY] = {
                "code": code,
                "to_email": normalized_to,
                "cc_email": normalized_cc,
                "subject": trimmed_subject,
                "message": trimmed_message,
            }

            preview_lines = [
                "Rascunho pronto.",
                f"Para: {normalized_to}",
            ]
            if normalized_cc:
                preview_lines.append(f"CC: {normalized_cc}")
            preview_lines.extend(
                [
                    f"Assunto: {trimmed_subject}",
                    f"Mensagem: {_truncate(trimmed_message, limit=240)}",
                    f"Código de confirmação: {code}",
                    f"Para enviar, o usuário precisa dizer exatamente: confirmar {code}",
                ]
            )
            logger.info("Rascunho de email criado para '%s'.", normalized_to)
            return "\n".join(preview_lines)
        except PermissionError as exc:
            logger.warning("Tentativa bloqueada de criar rascunho de email.")
            return str(exc)
        except ValueError as exc:
            logger.warning("Email rejeitado por validação: %s", exc)
            return f"Não foi possível criar o rascunho: {exc}"
        except Exception:
            logger.exception("Erro inesperado ao criar rascunho de email.")
            return "Ocorreu um erro ao criar o rascunho de email."

    @function_tool()
    async def confirm_email_send(
        context: RunContext,
        code: str,
    ) -> str:
        """Send the last drafted email only after explicit user confirmation."""
        state = _get_session_state(context)
        pending = state.get(PENDING_EMAIL_KEY)
        if not pending:
            return "Não há nenhum email pendente para envio."

        expected_code = pending.get("code")
        normalized_code = code.strip()
        if normalized_code != expected_code:
            logger.warning("Confirmação de email rejeitada por código inválido.")
            return "Código de confirmação inválido. O email não foi enviado."

        last_user_message = _get_last_user_message(context)
        expected_phrase = f"confirmar {expected_code}"
        if last_user_message != expected_phrase:
            logger.warning("Confirmação de email rejeitada por frase inválida.")
            return (
                "Envio bloqueado: o último comando do usuário precisa ser exatamente "
                f"'{expected_phrase}'."
            )

        try:
            _send_pending_email(pending)
            state[PENDING_EMAIL_KEY] = None
            logger.info("Email enviado para '%s'.", pending["to_email"])
            return f"Email enviado com sucesso para {pending['to_email']}."
        except smtplib.SMTPAuthenticationError:
            logger.exception("Falha de autenticação ao enviar email.")
            return (
                "Falha ao enviar email: erro de autenticação. "
                "Verifique as credenciais configuradas."
            )
        except smtplib.SMTPException as exc:
            logger.exception("Falha SMTP ao enviar email.")
            return f"Falha ao enviar email: erro SMTP - {exc}"
        except Exception:
            logger.exception("Erro inesperado ao enviar email.")
            return "Ocorreu um erro ao enviar o email."

    @function_tool()
    async def cancel_pending_email(
        context: RunContext,
    ) -> str:
        """Cancel the current pending email draft."""
        state = _get_session_state(context)
        if not state.get(PENDING_EMAIL_KEY):
            return "Não há nenhum email pendente para cancelar."

        state[PENDING_EMAIL_KEY] = None
        logger.info("Rascunho de email cancelado.")
        return "Rascunho de email cancelado com sucesso."

    return [draft_email, confirm_email_send, cancel_pending_email]


def build_tools(settings: Settings) -> list[Any]:
    tools = [get_weather, search_web]
    if settings.email_tool_enabled:
        tools.extend(build_email_tools(settings))
    return tools
