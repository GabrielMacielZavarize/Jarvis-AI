"""AGD-27: Google Agenda com a API do Google falsa e o relógio parado numa segunda-feira, 8h."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import calendar_tools
import confirmation
from calendar_tools import (
    PENDING_CALENDAR_KEY,
    TZ,
    CalendarError,
    CalendarNotConnected,
    Evento,
    ReminderWatcher,
    cancel_calendar_change,
    confirm_calendar_change,
    event_from_api,
    eventos_de_hoje,
    get_agenda,
    match_events,
    next_meeting,
    parse_when,
    prepare_calendar_delete,
    prepare_calendar_event,
    prepare_calendar_update,
    proximo_evento,
    reminder_instruction,
    reminder_payload,
    resumo_do_dia,
    run_reminder_loop,
)
from confirmation import parse_confirmation
from server import CALENDAR_TOOL_NAMES, create_app
from settings import SettingsError, load_settings
from wake_hub import REMINDER_TTL_S, WakeHub, hud_events

from test_tools import FakeMessage, FakeRunContext

# Segunda-feira, 19 de outubro de 2026, 8h em São Paulo.
NOW = dt.datetime(2026, 10, 19, 8, 0, tzinfo=TZ)


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> dt.datetime:
    return dt.datetime(2026, month, day, hour, minute, tzinfo=TZ)


def api_event(event_id: str, title: str, start: dt.datetime | dt.date, end: dt.datetime | dt.date, **extra) -> dict:
    def moment(value):
        if isinstance(value, dt.datetime):
            return {"dateTime": value.isoformat(), "timeZone": "America/Sao_Paulo"}
        return {"date": value.isoformat()}

    return {"id": event_id, "status": "confirmed", "summary": title, "start": moment(start), "end": moment(end), **extra}


def agenda_items() -> list[dict]:
    return [
        api_event("daily", "Daily do time", at(19, 9), at(19, 9, 15), hangoutLink="https://meet.google.com/abc-defg-hij"),
        api_event("cliente", "Reunião com cliente", at(19, 10), at(19, 11), location="Sala 2"),
        api_event("almoco", "Almoço com a Ana", at(19, 12, 30), at(19, 13, 30)),
        api_event("niver", "Aniversário da Ana", dt.date(2026, 10, 20), dt.date(2026, 10, 21)),
        api_event("planejamento", "Reunião de planejamento", at(20, 10), at(20, 11)),
        api_event("dentista", "Dentista", at(23, 15), at(23, 16)),
        api_event("recusado", "Reunião que recusei", at(19, 16), at(19, 17), attendees=[{"self": True, "responseStatus": "declined"}]),
        api_event("cancelado", "Cancelado", at(19, 17), at(19, 18), status="cancelled"),
    ]


class FakeRequest:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.result


class FakeEvents:
    """events() of the Google Calendar client: answers list/insert/patch/delete from memory."""

    def __init__(self, items: list[dict]):
        self.items = items
        self.calls: list[tuple[str, dict]] = []
        self.error: Exception | None = None

    def _moment(self, raw: dict) -> dt.datetime:
        if "dateTime" in raw:
            return dt.datetime.fromisoformat(raw["dateTime"])
        return dt.datetime.combine(dt.date.fromisoformat(raw["date"]), dt.time(), tzinfo=TZ)

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        start = dt.datetime.fromisoformat(kwargs["timeMin"])
        end = dt.datetime.fromisoformat(kwargs["timeMax"])
        found = [item for item in self.items if self._moment(item["start"]) < end and self._moment(item["end"]) > start]
        return FakeRequest({"items": found}, self.error)

    def insert(self, calendarId, body):
        self.calls.append(("insert", {"calendarId": calendarId, "body": body}))
        return FakeRequest({**body, "id": "novo", "status": "confirmed"}, self.error)

    def patch(self, calendarId, eventId, body):
        self.calls.append(("patch", {"calendarId": calendarId, "eventId": eventId, "body": body}))
        original = next(item for item in self.items if item["id"] == eventId)
        return FakeRequest({**original, **body}, self.error)

    def delete(self, calendarId, eventId):
        self.calls.append(("delete", {"calendarId": calendarId, "eventId": eventId}))
        return FakeRequest("", self.error)

    def writes(self) -> list[tuple[str, dict]]:
        return [call for call in self.calls if call[0] != "list"]


class FakeService:
    def __init__(self, items: list[dict]):
        self._events = FakeEvents(items)

    def events(self) -> FakeEvents:
        return self._events


class HttpError(Exception):
    """Stand-in for googleapiclient.errors.HttpError (has .resp.status)."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.resp = SimpleNamespace(status=status)


class CalendarTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = FakeService(agenda_items())
        self.events = self.service.events()
        self.cards = AsyncMock(return_value=True)
        for target, value in (
            ("agora", lambda: NOW),
            ("get_service", lambda: self.service),
            ("show_card", self.cards),
            ("tool_status", AsyncMock(return_value=True)),
        ):
            patcher = patch.object(calendar_tools, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (("CONFIRMATION_WAIT_SECONDS", 0.05), ("CONFIRMATION_POLL_SECONDS", 0.01)):
            patcher = patch.object(confirmation, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def last_card(self) -> dict:
        kind, data = self.cards.await_args.args
        self.assertEqual(kind, "calendar")
        return data


class ParseWhenTests(unittest.TestCase):
    def check(self, text: str, date: dt.date, time: dt.time | None = None, *, explicit: bool = True) -> None:
        when = parse_when(text, NOW)
        self.assertIsNotNone(when, text)
        self.assertEqual((when.date, when.time, when.explicit_date), (date, time, explicit), text)

    def test_relative_days(self) -> None:
        self.check("hoje", dt.date(2026, 10, 19))
        self.check("amanhã", dt.date(2026, 10, 20))
        self.check("depois de amanhã às 9", dt.date(2026, 10, 21), dt.time(9))
        self.check("amanhã de manhã às 8", dt.date(2026, 10, 20), dt.time(8))
        self.check("ontem", dt.date(2026, 10, 18))
        self.check("daqui a 3 dias", dt.date(2026, 10, 22))

    def test_weekdays(self) -> None:
        self.check("sexta às 15h", dt.date(2026, 10, 23), dt.time(15))
        self.check("Sexta-feira, 15h30", dt.date(2026, 10, 23), dt.time(15, 30))
        self.check("segunda", dt.date(2026, 10, 19))
        self.check("próxima segunda", dt.date(2026, 10, 26))
        self.check("quarta que vem às 10:00", dt.date(2026, 10, 21), dt.time(10))
        self.check("sexta da semana que vem às 9", dt.date(2026, 10, 30), dt.time(9))
        self.check("sábado", dt.date(2026, 10, 24))

    def test_dates(self) -> None:
        self.check("dia 25 às 14h30", dt.date(2026, 10, 25), dt.time(14, 30))
        self.check("dia 5", dt.date(2026, 11, 5))  # dia 5 de outubro já passou
        self.check("25/12 às 20h", dt.date(2026, 12, 25), dt.time(20))
        self.check("3 de novembro às 9 da manhã", dt.date(2026, 11, 3), dt.time(9))
        self.check("dia primeiro de janeiro", dt.date(2027, 1, 1))
        self.check("2026-10-23T15:00:00-03:00", dt.date(2026, 10, 23), dt.time(15))
        self.check("2026-10-23", dt.date(2026, 10, 23))

    def test_spoken_times(self) -> None:
        today = dt.date(2026, 10, 19)
        self.check("às três da tarde", today, dt.time(15), explicit=False)
        self.check("às nove e meia", today, dt.time(9, 30), explicit=False)
        self.check("meio-dia", today, dt.time(12), explicit=False)
        self.check("às 3", today, dt.time(15), explicit=False)  # compromisso às 3 = 15h
        self.check("8 da noite", today, dt.time(20), explicit=False)
        self.check("vinte e uma horas", today, dt.time(21), explicit=False)
        self.check("daqui a 2 horas", today, dt.time(10))
        self.check("daqui a 30 minutos", today, dt.time(8, 30))

    def test_nonsense_is_none(self) -> None:
        self.assertIsNone(parse_when("quando der", NOW))
        self.assertIsNone(parse_when("", NOW))


class EventParsingTests(unittest.TestCase):
    def test_reads_times_links_and_drops_declined_or_cancelled(self) -> None:
        events = [event for event in map(event_from_api, agenda_items()) if event]
        self.assertNotIn("recusado", [event.id for event in events])
        self.assertNotIn("cancelado", [event.id for event in events])
        daily = events[0]
        self.assertEqual((daily.start, daily.end), (at(19, 9), at(19, 9, 15)))
        self.assertEqual(daily.meeting_link, "https://meet.google.com/abc-defg-hij")
        birthday = next(event for event in events if event.id == "niver")
        self.assertTrue(birthday.all_day)

    def test_utc_times_become_sao_paulo(self) -> None:
        event = event_from_api({"id": "x", "summary": "X", "start": {"dateTime": "2026-10-19T15:00:00Z"}, "end": {"dateTime": "2026-10-19T16:00:00Z"}})
        self.assertEqual(event.start, at(19, 12))

    def test_matches_spoken_references(self) -> None:
        events = [event for event in map(event_from_api, agenda_items()) if event]
        ids = lambda query: [event.id for event in match_events(query, events, NOW)]  # noqa: E731

        self.assertEqual(ids("a reunião das 10"), ["cliente"])  # a de hoje, não a de amanhã
        self.assertEqual(ids("reunião das dez"), ["cliente"])
        self.assertEqual(ids("dentista"), ["dentista"])
        self.assertEqual(ids("almoço"), ["almoco"])
        self.assertEqual(ids("planejamento"), ["planejamento"])
        self.assertEqual(ids("reunião"), ["cliente"])
        self.assertEqual(ids("academia"), [])


class PublicApiTests(CalendarTestCase):
    def test_eventos_de_hoje_for_other_modules(self) -> None:
        titles = [event.title for event in eventos_de_hoje()]
        self.assertEqual(titles, ["Daily do time", "Reunião com cliente", "Almoço com a Ana"])
        _, call = self.events.calls[-1]
        self.assertEqual(call["timeMin"], "2026-10-19T00:00:00-03:00")
        self.assertEqual(call["timeMax"], "2026-10-20T00:00:00-03:00")
        self.assertTrue(call["singleEvents"])

    def test_proximo_evento_skips_all_day(self) -> None:
        with patch.object(calendar_tools, "agora", lambda: at(19, 13, 45)):
            self.assertEqual(proximo_evento().id, "planejamento")

    def test_resumo_do_dia_never_raises(self) -> None:
        self.assertIn("3 compromissos", resumo_do_dia())
        with patch.object(calendar_tools, "get_service", side_effect=CalendarNotConnected("Sem login. faça login")):
            self.assertEqual(resumo_do_dia(), "Sem login. faça login")


class ReadToolTests(CalendarTestCase):
    async def test_today(self) -> None:
        result = await get_agenda(FakeRunContext())

        self.assertIn("Agenda de hoje (segunda, 19 de outubro): 3 compromissos.", result)
        self.assertIn("09:00–09:15 · Daily do time", result)
        self.assertIn("10:00–11:00 · Reunião com cliente (Sala 2)", result)
        card = self.last_card()
        self.assertEqual(card["status"], "agenda")
        self.assertEqual([event["id"] for event in card["events"]], ["daily", "cliente", "almoco"])

    async def test_tomorrow_lists_all_day_first(self) -> None:
        result = await get_agenda(FakeRunContext(), day="amanhã")

        self.assertIn("Agenda de amanhã (terça, 20 de outubro): 2 compromissos.", result)
        self.assertLess(result.index("dia inteiro · Aniversário da Ana"), result.index("Reunião de planejamento"))

    async def test_week(self) -> None:
        result = await get_agenda(FakeRunContext(), day="hoje", days=7)
        self.assertIn("sexta, 23 de outubro, 15:00–16:00 · Dentista", result)

    async def test_empty_day_and_unknown_day(self) -> None:
        self.assertIn("nada marcado", await get_agenda(FakeRunContext(), day="domingo"))
        self.assertIn("Não entendi o dia", await get_agenda(FakeRunContext(), day="quando der"))

    async def test_not_logged_in_explains_how(self) -> None:
        def missing():
            raise CalendarNotConnected("O Google Agenda ainda não foi conectado. Rode uma vez no computador: python calendar_tools.py --login")

        with patch.object(calendar_tools, "get_service", missing):
            result = await get_agenda(FakeRunContext())
        self.assertIn("python calendar_tools.py --login", result)

    async def test_revoked_access_is_reported(self) -> None:
        self.events.error = HttpError(401)
        result = await get_agenda(FakeRunContext())
        self.assertIn("recusou o acesso", result)
        self.assertIn("--login", result)

    async def test_next_meeting(self) -> None:
        result = await next_meeting(FakeRunContext())

        self.assertIn("Próximo: hoje (segunda, 19 de outubro), 09:00–09:15 · Daily do time — começa em 1 hora.", result)
        self.assertIn("link de videochamada", result)
        self.assertEqual(self.last_card()["highlight"], "daily")
        self.assertEqual(self.events.writes(), [])


class WriteToolTests(CalendarTestCase):
    async def confirm(self, context: FakeRunContext, phrase: str) -> str:
        code = context.userdata[PENDING_CALENDAR_KEY]["code"]
        context.session.history._messages.append(FakeMessage("user", phrase.format(code=code)))
        return await confirm_calendar_change(context, code)

    async def test_create_needs_the_agenda_phrase_with_the_code(self) -> None:
        context = FakeRunContext(userdata={})
        result = await prepare_calendar_event(context, title="Dentista", when="sexta às 9")

        self.assertIn("ainda NÃO gravado", result)
        self.assertIn("Dentista — sexta, 23 de outubro, 09:00–10:00", result)
        code = context.userdata[PENDING_CALENDAR_KEY]["code"]
        self.assertIn(f"confirmar agenda {code}", result)
        card = self.last_card()
        self.assertEqual((card["status"], card["code"], card["action"]), ("pending", code, "create"))
        self.assertEqual(self.events.writes(), [])

        blocked = await self.confirm(context, "pode marcar, confirma {code}")
        self.assertTrue(blocked.startswith("Bloqueado"))
        self.assertEqual(self.events.writes(), [])

        done = await self.confirm(context, "Confirmar agenda {code}.")
        self.assertEqual(done, "Evento criado no Google Agenda: Dentista — sexta, 23 de outubro, 09:00–10:00.")
        (_, call), = self.events.writes()
        self.assertEqual(call["calendarId"], "primary")
        self.assertEqual(
            call["body"],
            {
                "summary": "Dentista",
                "start": {"dateTime": "2026-10-23T09:00:00-03:00", "timeZone": "America/Sao_Paulo"},
                "end": {"dateTime": "2026-10-23T10:00:00-03:00", "timeZone": "America/Sao_Paulo"},
            },
        )
        self.assertIsNone(context.userdata[PENDING_CALENDAR_KEY])
        self.assertEqual(self.last_card()["status"], "created")

    async def test_wrong_code_changes_nothing(self) -> None:
        context = FakeRunContext(userdata={})
        await prepare_calendar_event(context, title="Dentista", when="sexta às 15h")
        wrong = "000000" if context.userdata[PENDING_CALENDAR_KEY]["code"] != "000000" else "111111"
        result = await confirm_calendar_change(context, wrong)
        self.assertIn("Código de confirmação inválido", result)
        self.assertEqual(self.events.writes(), [])

    async def test_create_warns_about_conflicts(self) -> None:
        result = await prepare_calendar_event(FakeRunContext(userdata={}), title="Call", when="hoje às 10h30", duration_minutes=30)
        self.assertIn("conflita com: 10:00–11:00 · Reunião com cliente", result)

    async def test_time_already_past_today_means_tomorrow(self) -> None:
        # São 8h: "às 7" já passou hoje, então é amanhã às 7h.
        result = await prepare_calendar_event(FakeRunContext(userdata={}), title="Café", when="às 7")
        self.assertIn("amanhã (terça, 20 de outubro), 07:00–08:00", result)

    async def test_missing_time_asks(self) -> None:
        context = FakeRunContext(userdata={})
        result = await prepare_calendar_event(context, title="Dentista", when="sexta")
        self.assertIn("não o horário", result)
        self.assertNotIn(PENDING_CALENDAR_KEY, context.userdata)

    async def test_all_day_event(self) -> None:
        context = FakeRunContext(userdata={})
        await prepare_calendar_event(context, title="Viagem", when="dia 25", all_day=True)
        await self.confirm(context, "confirmar agenda {code}")
        (_, call), = self.events.writes()
        self.assertEqual(call["body"]["start"], {"date": "2026-10-25"})
        self.assertEqual(call["body"]["end"], {"date": "2026-10-26"})

    async def test_delete_the_meeting_at_ten(self) -> None:
        context = FakeRunContext(userdata={})
        result = await prepare_calendar_delete(context, event="a reunião das 10")

        self.assertIn("Exclusão preparada (ainda NÃO apagado): hoje (segunda, 19 de outubro), 10:00–11:00 · Reunião com cliente", result)
        self.assertEqual(self.last_card()["highlight"], "cliente")
        done = await self.confirm(context, "confirmar evento {code}")
        self.assertTrue(done.startswith("Evento apagado"))
        self.assertEqual(self.events.writes(), [("delete", {"calendarId": "primary", "eventId": "cliente"})])

    async def test_delete_with_day_given(self) -> None:
        context = FakeRunContext(userdata={})
        await prepare_calendar_delete(context, event="reunião das 10", day="amanhã")
        self.assertEqual(context.userdata[PENDING_CALENDAR_KEY]["event_id"], "planejamento")

    async def test_ambiguous_reference_asks_which(self) -> None:
        context = FakeRunContext(userdata={})
        self.events.items.append(api_event("cliente2", "Reunião com outro cliente", at(19, 15), at(19, 16)))
        result = await prepare_calendar_delete(context, event="reunião com cliente", day="hoje")
        self.assertIn("Mais de um evento combina", result)
        self.assertNotIn(PENDING_CALENDAR_KEY, context.userdata)

    async def test_unknown_event(self) -> None:
        result = await prepare_calendar_delete(FakeRunContext(userdata={}), event="academia")
        self.assertIn("Não achei nenhum evento", result)

    async def test_move_keeps_day_and_duration(self) -> None:
        context = FakeRunContext(userdata={})
        result = await prepare_calendar_update(context, event="dentista", new_when="16h")

        self.assertIn("para Dentista — sexta, 23 de outubro, 16:00–17:00", result)
        await self.confirm(context, "confirmar agenda {code}")
        (_, call), = self.events.writes()
        self.assertEqual(call["eventId"], "dentista")
        self.assertEqual(call["body"]["start"]["dateTime"], "2026-10-23T16:00:00-03:00")
        self.assertEqual(call["body"]["end"]["dateTime"], "2026-10-23T17:00:00-03:00")

    async def test_move_to_other_day_keeps_time(self) -> None:
        context = FakeRunContext(userdata={})
        await prepare_calendar_update(context, event="almoço", new_when="amanhã")
        body = context.userdata[PENDING_CALENDAR_KEY]["body"]
        self.assertEqual(body["start"]["dateTime"], "2026-10-20T12:30:00-03:00")
        self.assertEqual(body["end"]["dateTime"], "2026-10-20T13:30:00-03:00")

    async def test_update_needs_something_to_change(self) -> None:
        result = await prepare_calendar_update(FakeRunContext(userdata={}), event="dentista")
        self.assertIn("Diga o que mudar", result)

    async def test_cancel(self) -> None:
        context = FakeRunContext(userdata={})
        await prepare_calendar_event(context, title="Dentista", when="sexta às 15h")
        self.assertEqual(await cancel_calendar_change(context), "Mudança na agenda cancelada; nada foi gravado.")
        self.assertEqual(await confirm_calendar_change(context, "123456"), "Não há nenhuma mudança de agenda pendente.")
        self.assertEqual(self.events.writes(), [])

    async def test_api_failure_keeps_the_pending_change(self) -> None:
        context = FakeRunContext(userdata={})
        await prepare_calendar_event(context, title="Dentista", when="sexta às 15h")
        self.events.error = RuntimeError("sem rede")
        result = await self.confirm(context, "confirmar agenda {code}")
        self.assertIn("Falhou, nada mudou na agenda", result)
        self.assertIsNotNone(context.userdata[PENDING_CALENDAR_KEY])


class ConfirmationPhraseTests(unittest.TestCase):
    def test_agenda_phrase(self) -> None:
        self.assertEqual(parse_confirmation("Confirmar agenda 482 913.", "calendar"), "482913")
        self.assertEqual(parse_confirmation("confirma o evento quatro oito dois nove um três", "calendar"), "482913")
        self.assertIsNone(parse_confirmation("confirmar 482913", "calendar"))
        self.assertIsNone(parse_confirmation("confirmar agenda 482913", "email"))
        self.assertIsNone(parse_confirmation("confirmar agenda 482913 e apaga tudo", "calendar"))


class ReminderTests(unittest.TestCase):
    def events(self) -> list[Evento]:
        return [event for event in map(event_from_api, agenda_items()) if event]

    def test_warns_once_inside_the_window(self) -> None:
        watcher = ReminderWatcher(lead_minutes=10, fetch=lambda start, end: self.events())

        self.assertEqual(watcher.check(at(19, 8, 49)), [])
        self.assertEqual([event.id for event in watcher.check(at(19, 8, 50))], ["daily"])
        self.assertEqual(watcher.check(at(19, 8, 55)), [])
        self.assertEqual([event.id for event in watcher.check(at(19, 9, 52))], ["cliente"])

    def test_never_warns_all_day_or_started_events(self) -> None:
        watcher = ReminderWatcher(lead_minutes=10)
        self.assertEqual(watcher.due(self.events(), at(19, 23, 55)), [])
        self.assertEqual(watcher.due(self.events(), at(19, 9, 1)), [])

    def test_instruction_for_the_agent(self) -> None:
        daily = self.events()[0]
        text = reminder_instruction([reminder_payload(daily)], at(19, 8, 50))
        self.assertIn("'Daily do time' às 09:00 (começa em 10 minutos)", text)
        self.assertIn("videochamada", text)

    def test_loop_hands_due_events_and_respects_the_switch(self) -> None:
        clock = iter([at(19, 8, 51), at(19, 8, 52), at(19, 8, 53)])
        enabled = SimpleNamespace(calendar_enabled=True, calendar_reminder_minutes=10)
        disabled = SimpleNamespace(calendar_enabled=False, calendar_reminder_minutes=10)
        settings = iter([disabled, enabled, enabled])
        seen: list[list[str]] = []

        async def scenario() -> None:
            done = asyncio.Event()

            async def on_due(events):
                seen.append([event.id for event in events])
                done.set()

            watcher = ReminderWatcher(fetch=lambda start, end: self.events())
            with patch.object(calendar_tools, "is_connected", lambda: True):
                task = asyncio.create_task(
                    run_reminder_loop(lambda: next(settings), on_due, interval=0, clock=lambda: next(clock), watcher=watcher)
                )
                await asyncio.wait_for(done.wait(), 2)
                task.cancel()

        asyncio.run(scenario())
        self.assertEqual(seen, [["daily"]])


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class WakeHubReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.hub = WakeHub(clock=self.clock)
        self.reminder = {"id": "daily", "title": "Daily", "start": at(19, 9).isoformat(), "link": None}

    def test_without_hud_opens_the_browser_and_tags_the_wake(self) -> None:
        self.assertEqual(self.hub.push_reminders([self.reminder]), {"accepted": True, "opened_browser": True})
        client = self.hub.connect("tab-12345678")
        self.assertEqual(client.queue.get_nowait(), {"type": "wake", "score": 1.0, "reason": "calendar"})
        self.assertEqual(self.hub.claim_reminders(), [self.reminder])
        self.assertEqual(self.hub.claim_reminders(), [])

    def test_open_link_gets_it_without_a_wake(self) -> None:
        self.hub.connect("tab-12345678")
        self.hub.update("tab-12345678", session_active=True, visible=True, mic_label=None)
        self.assertEqual(self.hub.push_reminders([self.reminder]), {"accepted": True, "opened_browser": False})
        self.assertTrue(self.hub.clients["tab-12345678"].queue.empty())
        self.assertEqual(self.hub.claim_reminders(), [self.reminder])

    def test_stale_reminders_are_dropped(self) -> None:
        self.hub.push_reminders([self.reminder])
        self.clock.now += REMINDER_TTL_S + 1
        self.assertEqual(self.hub.claim_reminders(), [])

    def test_hud_stream_subscribes_for_reminders_without_wake_word(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "x", "JARVIS_ENABLE_CALENDAR": "true"})

        async def first_event() -> dict:
            stream = hud_events(self.hub, "tab-12345678", settings)
            event = json.loads((await anext(stream))[6:])
            await stream.aclose()
            return event

        self.assertEqual(
            asyncio.run(first_event()),
            {"type": "config", "enabled": True, "silence_s": 0, "proactive": False, "presence": False, "reminders": True, "wake_word": False},
        )


class SettingsAndServerTests(unittest.TestCase):
    def test_settings(self) -> None:
        self.assertFalse(load_settings({}).calendar_enabled)
        self.assertEqual(load_settings({}).calendar_reminder_minutes, 10)
        custom = load_settings({"JARVIS_ENABLE_CALENDAR": "true", "JARVIS_CALENDAR_REMINDER_MINUTES": "0"})
        self.assertTrue(custom.calendar_enabled)
        self.assertEqual(custom.calendar_reminder_minutes, 0)
        with self.assertRaises(SettingsError):
            load_settings({"JARVIS_CALENDAR_REMINDER_MINUTES": "dez"})

    def client(self, env: dict[str, str]) -> TestClient:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app(reload_env=False, calendar_reminders=False), base_url="http://127.0.0.1")

    def test_status_lists_calendar_tools(self) -> None:
        with patch.object(calendar_tools, "is_connected", lambda: False):
            body = self.client({"GOOGLE_API_KEY": "x", "JARVIS_ENABLE_CALENDAR": "true"}).get("/api/status").json()
        self.assertEqual(body["tools"][-len(CALENDAR_TOOL_NAMES) :], CALENDAR_TOOL_NAMES)
        self.assertEqual(body["calendar"], {"connected": False, "reminder_minutes": 10, "reminders": True})
        off = self.client({"GOOGLE_API_KEY": "x"}).get("/api/status").json()
        self.assertIsNone(off["calendar"])

    def test_agent_claims_reminders_once(self) -> None:
        client = self.client({"GOOGLE_API_KEY": "x", "JARVIS_ENABLE_CALENDAR": "true"})
        client.app.state.wake_hub.reminders.append((float("inf"), {"id": "daily"}))

        self.assertEqual(client.post("/api/calendar/reminders/claim").json(), {"reminders": [{"id": "daily"}]})
        self.assertEqual(client.post("/api/calendar/reminders/claim").json(), {"reminders": []})
        other_site = client.post("/api/calendar/reminders/claim", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(other_site.status_code, 403)
        remote = TestClient(client.app).post("/api/calendar/reminders/claim")
        self.assertEqual(remote.status_code, 403)

    def test_tool_names_match_the_agent(self) -> None:
        names = [tool.__name__ for tool in calendar_tools.build_calendar_tools()]
        self.assertEqual(names, CALENDAR_TOOL_NAMES)


class ErrorTests(unittest.TestCase):
    def test_not_found_and_offline(self) -> None:
        with self.assertRaisesRegex(CalendarError, "não existe mais"):
            calendar_tools._call(FakeRequest(error=HttpError(404)))
        with self.assertRaisesRegex(CalendarError, "sem internet"):
            calendar_tools._call(FakeRequest(error=OSError("offline")))

    def test_missing_token_means_not_connected(self) -> None:
        with patch.object(calendar_tools, "TOKEN_FILE", calendar_tools.ROOT / "nao-existe-token.json"):
            with self.assertRaises(CalendarNotConnected):
                calendar_tools._load_credentials()


if __name__ == "__main__":
    unittest.main()
