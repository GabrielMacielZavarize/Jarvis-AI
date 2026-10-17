from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from livekit import rtc

from hud import HUD_TOPIC, hud_request, publish_hud_event, watch_user_voice
from prompts import AGENT_INSTRUCTION, build_initial_reply_instruction, greeting_for
from tools import (
    _SESSION_TASKS,
    _TIMER_TASKS,
    HUD_PANEL_KINDS,
    TIMERS_KEY,
    _collect_diagnostics,
    _format_utc_offset,
    _hang_up,
    _wait_for_farewell,
    _windows_default_audio,
    check_microphone,
    end_session,
    get_current_time,
    get_timers,
    get_weather,
    manage_hud_panels,
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


def panel(kind: str, title: str, detail: str = "", expanded: bool = False) -> dict:
    return {"id": f"card-{kind}", "kind": kind, "title": title, "detail": detail, "expanded": expanded}


SCREEN = panel("screen", "Leitura de tela", "tela 2")
MEDIA = panel("media", "Reprodução", "YouTube · lo-fi")
WEATHER = panel("weather", "Meteorologia", "Criciúma")
NOTE = panel("note", "Lista de compras estrogonofe de frango")


class HudPanelToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_reports_what_the_hud_actually_closed(self) -> None:
        reply = {"open": [NOTE], "changed": [WEATHER, SCREEN], "unmatched": []}
        with patch("tools.hud_request", AsyncMock(return_value=reply)) as request:
            result = await manage_hud_panels(FakeRunContext(), action="close", panels=["weather", "screen"])

        request.assert_awaited_once_with(
            "close", {"targets": ["weather", "screen"], "kinds": ["weather", "screen"]}
        )
        self.assertEqual(
            result,
            "Fechado no HUD: Meteorologia (Criciúma) [weather]; Leitura de tela (tela 2) [screen]. "
            "Continuam abertos: Lista de compras estrogonofe de frango [note].",
        )

    async def test_screen_panel_reaches_the_hud(self) -> None:
        # Regressão: 'screen' era descartado antes de chegar ao HUD e o modelo dizia "fechado".
        with patch("tools.hud_request", AsyncMock(return_value={"open": [], "changed": [SCREEN]})) as request:
            result = await manage_hud_panels(FakeRunContext(), action="close", panels=["screen"])

        self.assertEqual(request.await_args.args[1]["targets"], ["screen"])
        self.assertTrue(result.startswith("Fechado no HUD: Leitura de tela"))

    async def test_close_missing_panel_says_nothing_was_closed(self) -> None:
        reply = {"open": [MEDIA], "changed": [], "unmatched": ["leitura de tela"]}
        with patch("tools.hud_request", AsyncMock(return_value=reply)):
            result = await manage_hud_panels(FakeRunContext(), action="close", panels=["leitura de tela"])

        self.assertTrue(result.startswith("NADA foi fechado:"))
        self.assertIn("'leitura de tela'", result)
        self.assertIn("Reprodução (YouTube · lo-fi) [media]", result)
        self.assertNotIn("Fechado no HUD", result)

    async def test_close_without_panels_targets_the_most_recent(self) -> None:
        reply = {"open": [], "changed": [panel("timer", "Timer", "macarrão · concluído")]}
        with patch("tools.hud_request", AsyncMock(return_value=reply)) as request:
            result = await manage_hud_panels(FakeRunContext(), action="close")

        request.assert_awaited_once_with("close", {"targets": ["last"], "kinds": []})
        self.assertIn("Timer (macarrão · concluído) [timer]", result)

    async def test_titles_are_forwarded_for_matching_on_the_hud(self) -> None:
        reply = {"open": [NOTE], "changed": [dict(NOTE, expanded=True)]}
        with patch("tools.hud_request", AsyncMock(return_value=reply)) as request:
            result = await manage_hud_panels(
                FakeRunContext(), action="expand", panels=["rascunho lista de compras estrogonofe de frango"]
            )

        payload = request.await_args.args[1]
        self.assertEqual(payload["targets"], ["rascunho lista de compras estrogonofe de frango"])
        self.assertEqual(payload["kinds"], [])
        self.assertEqual(result, "Ampliado no centro do HUD: Lista de compras estrogonofe de frango (ampliado) [note].")

    async def test_expand_with_nothing_open(self) -> None:
        with patch("tools.hud_request", AsyncMock(return_value={"open": [], "changed": []})):
            result = await manage_hud_panels(FakeRunContext(), action="expand", panels=["email"])

        self.assertEqual(
            result,
            "NADA foi ampliado: não há nenhum painel aberto no HUD. Painéis abertos agora: nenhum. "
            "Não diga ao usuário que foi ampliado.",
        )

    async def test_list_shows_titles_newest_first(self) -> None:
        with patch("tools.hud_request", AsyncMock(return_value={"open": [SCREEN, MEDIA], "changed": []})):
            listed = await manage_hud_panels(FakeRunContext(), action="list")

        self.assertEqual(
            listed,
            "Painéis abertos no HUD, do mais recente ao mais antigo: "
            "Leitura de tela (tela 2) [screen]; Reprodução (YouTube · lo-fi) [media].",
        )

    async def test_close_all_and_collapse(self) -> None:
        with patch("tools.hud_request", AsyncMock(return_value={"open": [], "changed": [SCREEN, MEDIA]})):
            closed = await manage_hud_panels(FakeRunContext(), action="close_all")
        with patch("tools.hud_request", AsyncMock(return_value={"open": [SCREEN], "changed": []})):
            collapsed = await manage_hud_panels(FakeRunContext(), action="collapse")

        self.assertTrue(closed.startswith("Fechados 2 painel(is)"))
        self.assertTrue(collapsed.startswith("NADA foi reduzido: nenhum painel estava ampliado."))

    async def test_understands_replies_from_an_older_hud_build(self) -> None:
        with patch("tools.hud_request", AsyncMock(return_value={"open": ["note"], "changed": ["weather"]})):
            result = await manage_hud_panels(FakeRunContext(), action="close", panels=["weather"])

        self.assertEqual(result, "Fechado no HUD: Meteorologia [weather]. Continuam abertos: Nota [note].")

    async def test_does_not_claim_success_without_hud(self) -> None:
        result = await manage_hud_panels(FakeRunContext(), action="close", panels=["weather"])
        self.assertEqual(result, "NADA foi fechado: o HUD não está conectado. Não diga que conseguiu.")

    def test_panel_kinds_cover_every_card_of_the_hud(self) -> None:
        web = Path(__file__).resolve().parent.parent / "web" / "src" / "lib"
        union = re.search(r"export type CardKind =([^;]+);", (web / "types.ts").read_text(encoding="utf-8"))
        card_kinds = set(re.findall(r"'(\w+)'", union.group(1)))
        titles = dict(re.findall(r"(\w+): \{ code: '[^']+', title: '([^']+)'", (web / "panels.ts").read_text(encoding="utf-8")))

        self.assertEqual(set(HUD_PANEL_KINDS), card_kinds)
        self.assertEqual(titles, HUD_PANEL_KINDS)

    async def test_hud_request_uses_rpc_to_the_viewer(self) -> None:
        perform = AsyncMock(return_value=json.dumps({"open": [], "changed": [WEATHER]}))
        viewer = SimpleNamespace(identity="operador-1")
        agent = SimpleNamespace(identity="agent-AJ_1")
        room = SimpleNamespace(
            local_participant=SimpleNamespace(perform_rpc=perform),
            remote_participants={"a": agent, "b": viewer},
        )
        with patch("hud.get_job_context", return_value=SimpleNamespace(room=room)):
            reply = await hud_request("close", {"targets": ["Leitura de tela"]})

        self.assertEqual(reply["changed"], [WEATHER])
        kwargs = perform.await_args.kwargs
        self.assertEqual(kwargs["destination_identity"], "operador-1")
        self.assertEqual(kwargs["method"], "jarvis.hud")
        self.assertEqual(json.loads(kwargs["payload"]), {"action": "close", "targets": ["Leitura de tela"]})

    async def test_hud_request_ignores_malformed_replies(self) -> None:
        perform = AsyncMock(return_value=json.dumps(["weather"]))
        room = SimpleNamespace(
            local_participant=SimpleNamespace(perform_rpc=perform),
            remote_participants={"b": SimpleNamespace(identity="operador-1")},
        )
        with patch("hud.get_job_context", return_value=SimpleNamespace(room=room)):
            self.assertIsNone(await hud_request("list"))


class TimerQueryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for task in list(_TIMER_TASKS):
            task.cancel()
        await asyncio.sleep(0)

    async def test_without_timers(self) -> None:
        self.assertEqual(await get_timers(FakeRunContext()), "Nenhum timer foi criado nesta conversa.")

    async def test_reports_time_left_for_each_timer(self) -> None:
        context = FakeRunContext()
        with patch("tools.time.time", return_value=1_000_000.0):
            await set_timer(context, minutes=10, label="macarrão")
            await set_timer(context, minutes=1, label="chá")
        with patch("tools.time.time", return_value=1_000_090.0):
            result = await get_timers(context)

        self.assertTrue(result.startswith("Timers ativos: 'macarrão': faltam 8 min e 30 s (termina às "))
        self.assertIn("Já terminaram: 'chá' terminou há 30 s.", result)

    async def test_finished_timer_is_reported_as_done(self) -> None:
        context = FakeRunContext()
        context.session.generate_reply = unittest.mock.Mock()
        await set_timer(context, minutes=0.001, label="ovo")
        await asyncio.sleep(0.2)

        result = await get_timers(context)
        self.assertTrue(result.startswith("Nenhum timer ativo agora. Já terminaram: 'ovo' terminou há"))
        timer = next(iter(context.userdata[TIMERS_KEY].values()))
        self.assertEqual(timer["status"], "done")


class MicrophoneToolTests(unittest.IsolatedAsyncioTestCase):
    MIC = {
        "label": "Headset (HyperX Cloud)",
        "device_id": "abc",
        "is_default": False,
        "enabled": True,
        "signal_s": 3,
        "heard_s": 0,
        "available": ["Headset (HyperX Cloud)", "Microfone (Realtek)"],
    }

    async def test_reports_hud_microphone_signal_and_windows_defaults(self) -> None:
        windows = {"entrada": "Microfone (Realtek)", "saída": "Alto-falantes (Realtek)"}
        with patch("tools.hud_request", AsyncMock(return_value={"mic": self.MIC})) as request, patch(
            "tools._windows_default_audio", return_value=windows
        ):
            result = await check_microphone(FakeRunContext())

        request.assert_awaited_once_with("mic")
        self.assertEqual(
            result,
            "Microfone selecionado no HUD: 'Headset (HyperX Cloud)'. O navegador recebeu som dele há 3 s. "
            "Eu ouvi sua voz pela última vez agora há pouco. Outros microfones disponíveis: Microfone (Realtek). "
            "Padrões do Windows: entrada 'Microfone (Realtek)', saída 'Alto-falantes (Realtek)'.",
        )

    async def test_muted_microphone(self) -> None:
        mic = dict(self.MIC, enabled=False, is_default=True, available=[])
        with patch("tools.hud_request", AsyncMock(return_value={"mic": mic})), patch(
            "tools._windows_default_audio", return_value={}
        ):
            result = await check_microphone(FakeRunContext())

        self.assertEqual(
            result,
            "Microfone selecionado no HUD: 'Headset (HyperX Cloud)', o padrão do sistema. "
            "Ele está MUDO no HUD (botão de microfone desligado).",
        )

    async def test_hud_offline_still_reports_windows_defaults(self) -> None:
        with patch("tools._windows_default_audio", return_value={"entrada": "Microfone (Realtek)"}):
            result = await check_microphone(FakeRunContext())

        self.assertTrue(result.startswith("Não consegui consultar o HUD"))
        self.assertIn("Padrões do Windows: entrada 'Microfone (Realtek)'.", result)

    async def test_outdated_hud_build(self) -> None:
        with patch("tools.hud_request", AsyncMock(return_value={"open": [], "changed": []})), patch(
            "tools._windows_default_audio", return_value={}
        ):
            result = await check_microphone(FakeRunContext())

        self.assertIn("jarvis.py --rebuild", result)

    @unittest.skipUnless(os.name == "nt", "pycaw só existe no Windows")
    def test_windows_defaults_read_only_device_names(self) -> None:
        speakers = SimpleNamespace(FriendlyName="Alto-falantes (Realtek)")
        raw_microphone = object()
        utilities = SimpleNamespace(
            GetMicrophone=lambda: raw_microphone,
            GetSpeakers=lambda: speakers,
            CreateDevice=lambda device: SimpleNamespace(FriendlyName="Microfone (Realtek)")
            if device is raw_microphone
            else None,
        )
        comtypes = SimpleNamespace(CoInitialize=unittest.mock.Mock(), CoUninitialize=unittest.mock.Mock())
        modules = {"comtypes": comtypes, "pycaw": SimpleNamespace(), "pycaw.pycaw": SimpleNamespace(AudioUtilities=utilities)}
        with patch.dict("sys.modules", modules):
            devices = _windows_default_audio()

        self.assertEqual(devices, {"entrada": "Microfone (Realtek)", "saída": "Alto-falantes (Realtek)"})
        comtypes.CoUninitialize.assert_called_once()


class FakeSpeechHandle:
    def __init__(self) -> None:
        self.callbacks = []
        self.wait_for_playout = AsyncMock()

    def add_done_callback(self, callback) -> None:
        self.callbacks.append(callback)


class EndSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch("tools.FAREWELL_AUDIO_TAIL_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_hud_closes_the_link_after_the_goodbye(self) -> None:
        session = SimpleNamespace(shutdown=unittest.mock.Mock())
        with patch("tools.hud_request", AsyncMock(return_value={"ended": True})) as request:
            await _hang_up(session, wait_for_farewell=False)

        request.assert_awaited_once_with("end_session")
        session.shutdown.assert_not_called()

    async def test_agent_ends_the_session_when_the_hud_does_not(self) -> None:
        session = SimpleNamespace(shutdown=unittest.mock.Mock())
        await _hang_up(session, wait_for_farewell=False)
        session.shutdown.assert_called_once()

    async def test_waits_for_the_goodbye_to_play(self) -> None:
        session = rtc.EventEmitter()
        handle = FakeSpeechHandle()
        waiting = asyncio.create_task(_wait_for_farewell(session))
        await asyncio.sleep(0)
        session.emit("speech_created", SimpleNamespace(speech_handle=handle))
        await asyncio.wait_for(waiting, 1)

        handle.wait_for_playout.assert_awaited_once()
        self.assertFalse(session._events.get("speech_created"))

    async def test_gives_up_waiting_when_no_goodbye_comes(self) -> None:
        with patch("tools.FAREWELL_START_TIMEOUT_S", 0.01), self.assertLogs("jarvis-tools", "WARNING"):
            await _wait_for_farewell(rtc.EventEmitter())

    async def test_tool_schedules_hang_up_after_its_speech(self) -> None:
        context = FakeRunContext()
        context.speech_handle = FakeSpeechHandle()
        context.session.shutdown = unittest.mock.Mock()

        result = await end_session(context)

        self.assertIn("Despeça-se", result)
        self.assertIn("O computador continua ligado", result)
        self.assertEqual(len(context.speech_handle.callbacks), 1)
        context.speech_handle.callbacks[0](context.speech_handle)
        await asyncio.wait_for(asyncio.gather(*_SESSION_TASKS), 1)
        # Sem HUD conectado, o próprio agente encerra a sessão.
        context.session.shutdown.assert_called_once()


class PromptTests(unittest.TestCase):
    def test_greeting_follows_time_of_day(self) -> None:
        self.assertTrue(greeting_for(dt.datetime(2026, 1, 1, 8)).startswith("Bom dia"))
        self.assertTrue(greeting_for(dt.datetime(2026, 1, 1, 15)).startswith("Boa tarde"))
        self.assertTrue(greeting_for(dt.datetime(2026, 1, 1, 22)).startswith("Boa noite"))

    def test_initial_instruction_quotes_greeting(self) -> None:
        instruction = build_initial_reply_instruction(dt.datetime(2026, 1, 1, 8))
        self.assertIn('"Bom dia, senhor.', instruction)

    def test_hud_tabs_and_shutdown_rules(self) -> None:
        self.assertIn('"Feche a aba" sem citar um site = o painel do HUD mais recente', AGENT_INSTRUCTION)
        self.assertIn("Fechar um painel NUNCA é pausar", AGENT_INSTRUCTION)
        self.assertIn("chame end_session", AGENT_INSTRUCTION)
        self.assertIn("get_timers", AGENT_INSTRUCTION)
        self.assertIn("check_microphone", AGENT_INSTRUCTION)
