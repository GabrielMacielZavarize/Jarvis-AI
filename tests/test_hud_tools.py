from __future__ import annotations

import asyncio
import datetime as dt
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from livekit import rtc

from hud import HUD_TOPIC, hud_request, publish_hud_event, watch_user_voice
from prompts import build_initial_reply_instruction, greeting_for
from tools import (
    _TIMER_TASKS,
    _collect_diagnostics,
    _format_utc_offset,
    manage_hud_panels,
    get_current_time,
    get_weather,
    run_diagnostics,
    search_news,
    set_timer,
    show_on_hud,
)

from test_tools import FakeResponse, FakeRunContext


def fake_job_context() -> tuple[SimpleNamespace, AsyncMock]:
    publish = AsyncMock()
    participant = SimpleNamespace(publish_data=publish)
    return SimpleNamespace(room=SimpleNamespace(local_participant=participant)), publish


def published_events(publish: AsyncMock) -> list[dict]:
    events = []
    for call in publish.await_args_list:
        payload = call.args[0]
        events.append(json.loads(payload))
        assert call.kwargs["topic"] == HUD_TOPIC
    return events


class HudPublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_is_noop_without_room(self) -> None:
        self.assertFalse(await publish_hud_event("tool", name="x", status="running"))

    async def test_publish_sends_json_on_hud_topic(self) -> None:
        ctx, publish = fake_job_context()
        with patch("hud.get_job_context", return_value=ctx):
            self.assertTrue(await publish_hud_event("tool", name="x", status="done"))

        event = published_events(publish)[0]
        self.assertEqual(event["type"], "tool")
        self.assertEqual(event["name"], "x")
        self.assertIn("ts", event)

    async def test_publish_failure_is_swallowed(self) -> None:
        ctx, publish = fake_job_context()
        publish.side_effect = RuntimeError("room closed")
        with patch("hud.get_job_context", return_value=ctx):
            self.assertFalse(await publish_hud_event("tool", name="x", status="done"))


class VoiceWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_and_publishes_when_user_speaks(self) -> None:
        session = rtc.EventEmitter()
        watch_user_voice(session)
        ctx, publish = fake_job_context()

        with patch("hud.get_job_context", return_value=ctx), self.assertLogs("jarvis-hud", "INFO") as logs:
            session.emit("user_state_changed", SimpleNamespace(new_state="speaking"))
            session.emit("user_input_transcribed", SimpleNamespace(is_final=True, transcript="olá jarvis"))
            session.emit("user_input_transcribed", SimpleNamespace(is_final=False, transcript="parcial"))
            await asyncio.sleep(0)

        self.assertEqual(published_events(publish)[0]["type"], "voice")
        self.assertEqual(published_events(publish)[0]["state"], "speaking")
        self.assertEqual(len(logs.output), 2)
        self.assertIn("olá jarvis", logs.output[1])


class WeatherCardTests(unittest.IsolatedAsyncioTestCase):
    @patch("tools.requests.get")
    async def test_weather_publishes_card_with_forecast(self, mock_get) -> None:
        mock_get.side_effect = [
            FakeResponse(
                {
                    "results": [
                        {
                            "name": "Porto Alegre",
                            "country": "Brasil",
                            "latitude": -30.03,
                            "longitude": -51.23,
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "timezone": "America/Sao_Paulo",
                    "current": {
                        "temperature_2m": 18,
                        "relative_humidity_2m": 80,
                        "weather_code": 61,
                        "wind_speed_10m": 12,
                        "apparent_temperature": 17,
                    },
                    "daily": {
                        "time": ["2026-10-17", "2026-10-18"],
                        "weather_code": [61, 2],
                        "temperature_2m_max": [21, 24],
                        "temperature_2m_min": [14, 15],
                        "precipitation_probability_max": [80, 10],
                    },
                }
            ),
        ]
        ctx, publish = fake_job_context()

        with patch("hud.get_job_context", return_value=ctx):
            result = await get_weather(FakeRunContext(), city="Porto Alegre")

        self.assertIn("Chuva leve", result)
        self.assertIn("Máx 21°C / Mín 14°C", result)

        events = published_events(publish)
        self.assertEqual([e["type"] for e in events], ["tool", "net", "card", "tool"])
        self.assertIn("api.open-meteo.com", events[1]["hosts"])
        card = events[2]
        self.assertEqual(card["kind"], "weather")
        self.assertEqual(card["data"]["location"], "Porto Alegre")
        self.assertEqual(len(card["data"]["daily"]), 2)
        self.assertEqual(card["data"]["daily"][1]["label"], "Parcialmente nublado")


class NewsToolTests(unittest.IsolatedAsyncioTestCase):
    @patch("tools.DDGS")
    async def test_search_news_success(self, mock_ddgs) -> None:
        mock_ddgs.return_value.news.return_value = [
            {
                "title": "Nova armadura revelada",
                "url": "https://example.com/armadura",
                "source": "Stark News",
                "date": "2026-10-17T10:00:00+00:00",
                "body": "Detalhes da Mark L.",
            }
        ]

        result = await search_news(FakeRunContext(), topic="tecnologia")

        self.assertIn("Nova armadura revelada (Stark News)", result)
        self.assertEqual(mock_ddgs.return_value.news.call_args.kwargs["region"], "br-pt")

    @patch("tools.DDGS")
    async def test_search_news_failure(self, mock_ddgs) -> None:
        mock_ddgs.return_value.news.side_effect = RuntimeError("offline")

        result = await search_news(FakeRunContext(), topic="tecnologia")

        self.assertEqual(result, "Ocorreu um erro ao buscar notícias sobre 'tecnologia'.")


class TimeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_time_without_city(self) -> None:
        result = await get_current_time(FakeRunContext())

        self.assertTrue(result.startswith("Horário local:"))
        self.assertIn("UTC", result)

    @patch("tools.requests.get")
    async def test_time_in_city_uses_geocoded_timezone(self, mock_get) -> None:
        mock_get.return_value = FakeResponse(
            {
                "results": [
                    {
                        "name": "Tóquio",
                        "country": "Japão",
                        "latitude": 35.68,
                        "longitude": 139.69,
                        "timezone": "Asia/Tokyo",
                    }
                ]
            }
        )

        result = await get_current_time(FakeRunContext(), city="Tóquio")

        self.assertIn("Tóquio, Japão", result)
        self.assertIn("UTC+09:00", result)

    @patch("tools.requests.get")
    async def test_time_city_not_found(self, mock_get) -> None:
        mock_get.return_value = FakeResponse({"results": []})

        result = await get_current_time(FakeRunContext(), city="Atlântida")

        self.assertEqual(result, "Cidade 'Atlântida' não encontrada.")

    def test_utc_offset_format(self) -> None:
        moment = dt.datetime(2026, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        self.assertEqual(_format_utc_offset(moment), "UTC-03:00")


class DiagnosticsToolTests(unittest.IsolatedAsyncioTestCase):
    def test_collect_diagnostics_shape(self) -> None:
        data = _collect_diagnostics()

        self.assertGreater(data["cpu"]["cores"], 0)
        self.assertEqual(len(data["cpu"]["per_core"]), data["cpu"]["cores"])
        self.assertGreater(data["memory"]["total_gb"], 0)
        self.assertGreaterEqual(data["uptime_s"], 0)

    async def test_run_diagnostics_summary(self) -> None:
        result = await run_diagnostics(FakeRunContext())

        self.assertIn("CPU", result)
        self.assertIn("Memória", result)


class TimerToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for task in list(_TIMER_TASKS):
            task.cancel()
        await asyncio.sleep(0)

    async def test_rejects_invalid_duration(self) -> None:
        result = await set_timer(FakeRunContext(), minutes=0)
        self.assertIn("precisa estar entre", result)

    async def test_timer_starts_and_finishes(self) -> None:
        context = FakeRunContext()
        context.session.generate_reply = unittest.mock.Mock()

        result = await set_timer(context, minutes=0.001, label="chá")
        self.assertEqual(result, "Timer 'chá' iniciado para 0 segundos.")

        await asyncio.sleep(0.2)
        context.session.generate_reply.assert_called_once()
        self.assertIn("chá", context.session.generate_reply.call_args.kwargs["instructions"])


class ShowOnHudTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_when_hud_is_offline(self) -> None:
        result = await show_on_hud(FakeRunContext(), title="Lista", content="a\nb")
        self.assertIn("não está conectado", result)

    async def test_publishes_note(self) -> None:
        ctx, publish = fake_job_context()
        with patch("hud.get_job_context", return_value=ctx):
            result = await show_on_hud(FakeRunContext(), title="Lista", content="a\nb")

        self.assertEqual(result, "Painel exibido no HUD.")
        event = published_events(publish)[0]
        self.assertEqual(event["kind"], "note")
        self.assertEqual(event["data"]["content"], "a\nb")


class HudPanelToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_reports_what_the_hud_actually_closed(self) -> None:
        reply = {"open": ["note"], "changed": ["weather", "search"]}
        with patch("tools.hud_request", AsyncMock(return_value=reply)) as request:
            result = await manage_hud_panels(FakeRunContext(), action="close", panels=["weather", "search", "bogus"])

        request.assert_awaited_once_with("close", ["weather", "search"])
        self.assertEqual(result, "Fechei: clima, pesquisa. Continuam abertos: notas.")

    async def test_close_missing_panel_is_honest(self) -> None:
        reply = {"open": ["search"], "changed": []}
        with patch("tools.hud_request", AsyncMock(return_value=reply)):
            result = await manage_hud_panels(FakeRunContext(), action="close", panels=["weather"])

        self.assertEqual(result, "Não havia painel de clima aberto. Abertos agora: pesquisa.")

    async def test_expand_and_list(self) -> None:
        with patch("tools.hud_request", AsyncMock(return_value={"open": ["weather"], "changed": ["weather"]})):
            expanded = await manage_hud_panels(FakeRunContext(), action="expand", panels=["weather"])
            listed = await manage_hud_panels(FakeRunContext(), action="list")

        self.assertIn("ampliado", expanded)
        self.assertEqual(listed, "Painéis abertos no HUD: clima.")

    async def test_does_not_claim_success_without_hud(self) -> None:
        result = await manage_hud_panels(FakeRunContext(), action="close", panels=["weather"])
        self.assertIn("não está conectado", result)

    async def test_hud_request_uses_rpc_to_the_viewer(self) -> None:
        perform = AsyncMock(return_value=json.dumps({"open": [], "changed": ["weather"]}))
        viewer = SimpleNamespace(identity="operador-1")
        agent = SimpleNamespace(identity="agent-AJ_1")
        room = SimpleNamespace(
            local_participant=SimpleNamespace(perform_rpc=perform),
            remote_participants={"a": agent, "b": viewer},
        )
        with patch("hud.get_job_context", return_value=SimpleNamespace(room=room)):
            reply = await hud_request("close", ["weather"])

        self.assertEqual(reply["changed"], ["weather"])
        kwargs = perform.await_args.kwargs
        self.assertEqual(kwargs["destination_identity"], "operador-1")
        self.assertEqual(kwargs["method"], "jarvis.hud")
        self.assertEqual(json.loads(kwargs["payload"]), {"action": "close", "kinds": ["weather"]})


class PromptTests(unittest.TestCase):
    def test_greeting_follows_time_of_day(self) -> None:
        self.assertTrue(greeting_for(dt.datetime(2026, 1, 1, 8)).startswith("Bom dia"))
        self.assertTrue(greeting_for(dt.datetime(2026, 1, 1, 15)).startswith("Boa tarde"))
        self.assertTrue(greeting_for(dt.datetime(2026, 1, 1, 22)).startswith("Boa noite"))

    def test_initial_instruction_quotes_greeting(self) -> None:
        instruction = build_initial_reply_instruction(dt.datetime(2026, 1, 1, 8))
        self.assertIn('"Bom dia, senhor.', instruction)
