from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

import requests

from settings import load_settings
from tools import PENDING_EMAIL_KEY, build_email_tools, get_weather, search_web


class FakeResponse:
    def __init__(self, payload, *, status_error: Exception | None = None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


@dataclass
class FakeMessage:
    role: str
    text_content: str


class FakeHistory:
    def __init__(self, messages: list[FakeMessage] | None = None):
        self._messages = messages or []

    def messages(self) -> list[FakeMessage]:
        return self._messages


class FakeSession:
    def __init__(
        self,
        *,
        messages: list[FakeMessage] | None = None,
        userdata: dict | None = None,
    ):
        self.history = FakeHistory(messages)
        self.userdata = userdata if userdata is not None else {PENDING_EMAIL_KEY: None}


class FakeRunContext:
    def __init__(
        self,
        *,
        messages: list[FakeMessage] | None = None,
        userdata: dict | None = None,
    ):
        self.session = FakeSession(messages=messages, userdata=userdata)

    @property
    def userdata(self):
        return self.session.userdata


class FakeSMTP:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        FakeSMTP.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def sendmail(self, sender, recipients, message):
        self.sent = (sender, recipients, message)


class WeatherToolTests(unittest.IsolatedAsyncioTestCase):
    @patch("tools.requests.get")
    async def test_get_weather_success(self, mock_get) -> None:
        mock_get.side_effect = [
            FakeResponse(
                {
                    "results": [
                        {
                            "name": "São Paulo",
                            "country": "Brasil",
                            "latitude": -23.55,
                            "longitude": -46.63,
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "current": {
                        "temperature_2m": 24,
                        "relative_humidity_2m": 70,
                        "weather_code": 1,
                        "wind_speed_10m": 9,
                    }
                }
            ),
        ]

        result = await get_weather(FakeRunContext(), city="São Paulo")

        self.assertIn("São Paulo, Brasil", result)
        self.assertIn("24°C", result)

    @patch("tools.requests.get")
    async def test_get_weather_city_not_found(self, mock_get) -> None:
        mock_get.return_value = FakeResponse({"results": []})

        result = await get_weather(FakeRunContext(), city="Cidade Inexistente")

        self.assertEqual(result, "Cidade 'Cidade Inexistente' não encontrada.")

    @patch("tools.requests.get")
    async def test_get_weather_http_failure(self, mock_get) -> None:
        mock_get.return_value = FakeResponse(
            {},
            status_error=requests.HTTPError("boom"),
        )

        result = await get_weather(FakeRunContext(), city="São Paulo")

        self.assertEqual(
            result,
            "O serviço de clima retornou um erro ao processar a consulta.",
        )


class SearchToolTests(unittest.IsolatedAsyncioTestCase):
    @patch("tools.DDGS")
    async def test_search_web_success(self, mock_ddgs) -> None:
        mock_ddgs.return_value.text.return_value = [
            {
                "title": "Jarvis Project",
                "href": "https://example.com/jarvis",
                "body": "Projeto de assistente por voz.",
            }
        ]

        result = await search_web(FakeRunContext(), query="jarvis projeto")

        self.assertIn("Jarvis Project", result)
        self.assertIn("https://example.com/jarvis", result)

    @patch("tools.DDGS")
    async def test_search_web_failure(self, mock_ddgs) -> None:
        mock_ddgs.return_value.text.side_effect = RuntimeError("offline")

        result = await search_web(FakeRunContext(), query="jarvis projeto")

        self.assertEqual(
            result,
            "Ocorreu um erro ao pesquisar na web por 'jarvis projeto'.",
        )


class EmailToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_ENABLE_EMAIL_TOOL": "true",
                "GMAIL_USER": "jarvis@example.com",
                "GMAIL_APP_PASSWORD": "secret",
            }
        )
        tools = build_email_tools(settings)
        self.tools_by_name = {tool.__name__: tool for tool in tools}

    async def test_draft_email_rejects_non_allowlisted_recipient(self) -> None:
        result = await self.tools_by_name["draft_email"](
            FakeRunContext(),
            to_email="other@example.com",
            subject="Teste",
            message="Corpo",
        )

        self.assertIn("Envio bloqueado", result)

    async def test_draft_email_stores_pending_message(self) -> None:
        context = FakeRunContext()

        result = await self.tools_by_name["draft_email"](
            context,
            to_email="jarvis@example.com",
            subject="Teste",
            message="Corpo do email",
        )

        pending = context.userdata[PENDING_EMAIL_KEY]
        self.assertIsNotNone(pending)
        self.assertEqual(pending["to_email"], "jarvis@example.com")
        self.assertIn("Código de confirmação", result)

    async def test_confirm_email_send_success(self) -> None:
        context = FakeRunContext()

        await self.tools_by_name["draft_email"](
            context,
            to_email="jarvis@example.com",
            subject="Teste",
            message="Corpo do email",
        )
        code = context.userdata[PENDING_EMAIL_KEY]["code"]
        context.session.history = FakeHistory([FakeMessage(role="user", text_content=f"confirmar {code}")])

        with patch("tools.smtplib.SMTP", FakeSMTP):
            result = await self.tools_by_name["confirm_email_send"](
                context,
                code=code,
            )

        self.assertIn("Email enviado com sucesso", result)
        self.assertIsNone(context.userdata[PENDING_EMAIL_KEY])
        self.assertEqual(FakeSMTP.last_instance.logged_in, ("jarvis@example.com", "secret"))

    async def test_confirm_email_send_rejects_invalid_code(self) -> None:
        context = FakeRunContext(messages=[FakeMessage(role="user", text_content="confirmar 999999")])

        await self.tools_by_name["draft_email"](
            context,
            to_email="jarvis@example.com",
            subject="Teste",
            message="Corpo do email",
        )

        result = await self.tools_by_name["confirm_email_send"](
            context,
            code="000000",
        )

        self.assertEqual(result, "Código de confirmação inválido. O email não foi enviado.")

    async def test_cancel_pending_email(self) -> None:
        context = FakeRunContext()

        await self.tools_by_name["draft_email"](
            context,
            to_email="jarvis@example.com",
            subject="Teste",
            message="Corpo do email",
        )

        result = await self.tools_by_name["cancel_pending_email"](context)

        self.assertEqual(result, "Rascunho de email cancelado com sucesso.")
        self.assertIsNone(context.userdata[PENDING_EMAIL_KEY])
