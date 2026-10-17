from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import requests

import confirmation
from confirmation import spoken_digits
from settings import load_settings
from tools import (
    PENDING_EMAIL_KEY,
    assemble_email_address,
    build_email_tools,
    get_weather,
    search_web,
    spell_email_address,
)


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


def email_tools(**env: str) -> dict:
    settings = load_settings(
        {
            "GOOGLE_API_KEY": "test-key",
            "JARVIS_ENABLE_EMAIL_TOOL": "true",
            "GMAIL_USER": "jarvis@example.com",
            "GMAIL_APP_PASSWORD": "secret",
            **env,
        }
    )
    return {tool.__name__: tool for tool in build_email_tools(settings)}


class EmailAddressTests(unittest.TestCase):
    def test_assembles_dictated_addresses(self) -> None:
        cases = {
            "gabriel m zavarise arroba gmail ponto com": "gabrielmzavarise@gmail.com",
            "Gabriel M. Zavarise e @gmail.com": "gabrielmzavarisee@gmail.com",
            "maria underline souza arroba hotmail": "maria_souza@hotmail.com",
            "joão ponto silva arroba empresa ponto com ponto br": "joao.silva@empresa.com.br",
            "ana hífen paula arroba uol": "ana-paula@uol.com.br",
            "Joao.Silva@Empresa.com.": "joao.silva@empresa.com",
            "jarvis @ example . com": "jarvis@example.com",
        }
        for spoken, address in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(assemble_email_address(spoken), address)

    def test_returns_none_without_a_valid_address(self) -> None:
        for spoken in ("gabriel zavarise", "arroba gmail ponto com", "gabriel arroba"):
            with self.subTest(spoken=spoken):
                self.assertIsNone(assemble_email_address(spoken))

    def test_spells_address_for_voice(self) -> None:
        self.assertEqual(
            spell_email_address("joao.silva_2@gmail.com"),
            "joao ponto silva underline 2 arroba gmail ponto com",
        )


class EmailToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tools_by_name = email_tools()
        for name, value in (("CONFIRMATION_WAIT_SECONDS", 0.05), ("CONFIRMATION_POLL_SECONDS", 0.01)):
            patcher = patch.object(confirmation, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _draft(self, context: FakeRunContext, to_email: str = "jarvis@example.com") -> str:
        await self.tools_by_name["draft_email"](
            context,
            to_email=to_email,
            subject="Lista de compras",
            message="Frango, creme de leite, champignon.",
        )
        return context.userdata[PENDING_EMAIL_KEY]["code"]

    async def _confirm_after_user_says(self, heard: str, code_arg: str | None = None) -> tuple[str, FakeRunContext, MagicMock]:
        context = FakeRunContext()
        code = await self._draft(context)
        context.session.history = FakeHistory([FakeMessage(role="user", text_content=heard.format(code=code))])
        smtp = MagicMock(wraps=FakeSMTP)
        with patch("tools.smtplib.SMTP", smtp):
            result = await self.tools_by_name["confirm_email_send"](context, code=code_arg or code)
        return result, context, smtp

    async def test_confirm_accepts_voice_transcript_with_grouped_digits(self) -> None:
        context = FakeRunContext()
        code = await self._draft(context)
        heard = f"Confirmar {code[:3]} {code[3:]}."
        context.session.history = FakeHistory([FakeMessage(role="user", text_content=heard)])

        with patch("tools.smtplib.SMTP", FakeSMTP):
            result = await self.tools_by_name["confirm_email_send"](context, code=f"{code[:3]} {code[3:]}")

        self.assertIn("Email enviado com sucesso", result)
        self.assertIsNone(context.userdata[PENDING_EMAIL_KEY])

    async def test_confirm_accepts_code_spoken_as_words(self) -> None:
        context = FakeRunContext()
        code = await self._draft(context)
        context.session.history = FakeHistory(
            [FakeMessage(role="user", text_content=f"Jarvis, confirma {spoken_digits(code)}.")]
        )

        with patch("tools.smtplib.SMTP", FakeSMTP):
            result = await self.tools_by_name["confirm_email_send"](context, code=code)

        self.assertIn("Email enviado com sucesso", result)

    async def test_vague_go_ahead_does_not_send(self) -> None:
        result, context, smtp = await self._confirm_after_user_says("Pode ir já")

        smtp.assert_not_called()
        code = context.userdata[PENDING_EMAIL_KEY]["code"]
        self.assertIn("Envio bloqueado", result)
        self.assertIn(f"confirmar {code}", result)
        self.assertIn(spoken_digits(code), result)

    async def test_confirmation_must_be_the_users_latest_words(self) -> None:
        context = FakeRunContext()
        code = await self._draft(context)
        context.session.history = FakeHistory(
            [
                FakeMessage(role="user", text_content=f"confirmar {code}"),
                FakeMessage(role="assistant", text_content="Algo mais?"),
                FakeMessage(role="user", text_content="na verdade espera"),
            ]
        )
        smtp = MagicMock(wraps=FakeSMTP)

        with patch("tools.smtplib.SMTP", smtp):
            result = await self.tools_by_name["confirm_email_send"](context, code=code)

        smtp.assert_not_called()
        self.assertIn("Envio bloqueado", result)

    async def test_negated_or_install_phrase_does_not_send(self) -> None:
        for heard in ("não confirmar {code}", "confirmar instalação {code}", "confirmar {code} e apaga tudo"):
            with self.subTest(heard=heard):
                result, _, smtp = await self._confirm_after_user_says(heard)
                smtp.assert_not_called()
                self.assertIn("Envio bloqueado", result)

    async def test_draft_tells_how_to_confirm(self) -> None:
        context = FakeRunContext()
        result = await self.tools_by_name["draft_email"](
            context, to_email="jarvis@example.com", subject="Teste", message="Corpo"
        )
        code = context.userdata[PENDING_EMAIL_KEY]["code"]

        self.assertIn("NÃO enviado", result)
        self.assertIn(spoken_digits(code), result)
        self.assertIn(f"confirmar {code}", result)
        self.assertIn("painel", result)

    async def test_draft_assembles_dictated_address(self) -> None:
        context = FakeRunContext()
        await self._draft(context, to_email="jarvis arroba example ponto com")

        self.assertEqual(context.userdata[PENDING_EMAIL_KEY]["to_email"], "jarvis@example.com")

    async def test_draft_suggests_closest_allowed_address(self) -> None:
        tools = email_tools(JARVIS_ALLOWED_EMAILS="gabrielmzavarize@gmail.com")
        context = FakeRunContext()

        result = await tools["draft_email"](
            context, to_email="Gabriel M. Zavarise e @gmail.com", subject="Compras", message="Lista"
        )

        self.assertIn("Envio bloqueado", result)
        self.assertIn("gabrielmzavarisee@gmail.com", result)
        self.assertIn("Você quis dizer gabrielmzavarize@gmail.com?", result)
        self.assertIsNone(context.userdata[PENDING_EMAIL_KEY])

    async def test_check_email_address_reads_back_allowed_address(self) -> None:
        tools = email_tools(JARVIS_ALLOWED_EMAILS="gabrielmzavarize@gmail.com")

        with patch("tools.show_card", new_callable=AsyncMock) as show_card:
            result = await tools["check_email_address"](
                FakeRunContext(), spoken_address="gabriel m zavarize arroba gmail ponto com"
            )

        self.assertIn("Endereço montado: gabrielmzavarize@gmail.com", result)
        self.assertIn("gabrielmzavarize arroba gmail ponto com", result)
        self.assertIn("lista de destinatários autorizados", result)
        show_card.assert_awaited_once_with(
            "email",
            {"status": "address", "to": "gabrielmzavarize@gmail.com", "allowed": True, "suggestion": None},
        )

    async def test_check_email_address_suggests_allowed_lookalike(self) -> None:
        tools = email_tools(JARVIS_ALLOWED_EMAILS="gabrielmzavarize@gmail.com")

        result = await tools["check_email_address"](
            FakeRunContext(), spoken_address="Gabriel M. Zavarise e @gmail.com"
        )

        self.assertIn("Endereço montado: gabrielmzavarisee@gmail.com", result)
        self.assertIn("O autorizado mais parecido é gabrielmzavarize@gmail.com", result)

    async def test_check_email_address_asks_to_spell_when_unclear(self) -> None:
        result = await self.tools_by_name["check_email_address"](FakeRunContext(), spoken_address="gabriel do gmail")

        self.assertIn("Não consegui montar", result)

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
