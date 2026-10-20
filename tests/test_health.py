from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import health
from health import DAY_S, Event, HealthStore, report, summarize
from server import create_app
from wake_word import NearMisses, ServerLink, WakeDetector, run

LOCAL = "http://127.0.0.1:8000"
# O conftest troca health._post por um no-op em cada teste; esta é a versão real.
REAL_POST = health._post
NOW = time.mktime((2026, 10, 20, 15, 0, 0, 0, 0, -1))
THRESHOLDS = {"jarvis": 0.5, "friday": 0.7}


def sample(kind: str, key: str, value: float | None = None, detail: str | None = None, ago: float = 60.0) -> Event:
    return Event(NOW - ago, kind, key, value, detail)


def summary(events: list[Event], days: int = 7, thresholds: dict[str, float] | None = None) -> dict:
    return summarize(events, now=NOW, days=days, wake_thresholds=THRESHOLDS if thresholds is None else thresholds, min_similarity=0.6)


def texts(result: dict) -> list[str]:
    return [hint["text"] for hint in result["suggestions"]]


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "saude.db"
        self.now = NOW
        self.store = HealthStore(self.path, clock=lambda: self.now)

    def test_keeps_events_in_sqlite(self) -> None:
        self.store.add("latency", "gemini-x", 1.25)
        self.store.add("tool_error", "get_weather", detail="x" * 500)

        events = HealthStore(self.path).events(0)

        self.assertEqual([(e.kind, e.key, e.value) for e in events], [("latency", "gemini-x", 1.25), ("tool_error", "get_weather", None)])
        self.assertEqual(len(events[1].detail), 200)

    def test_drops_events_older_than_the_retention(self) -> None:
        self.store.add("latency", "m", 1.0, ts=NOW - (health.RETENTION_DAYS + 1) * DAY_S)
        self.store.add("latency", "m", 2.0, ts=NOW - DAY_S)
        with patch.object(health, "PRUNE_EVERY", 1):
            HealthStore(self.path, clock=lambda: NOW).add("latency", "m", 3.0)

        self.assertEqual([e.value for e in self.store.events(0)], [2.0, 3.0])

    def test_keeps_at_most_max_events(self) -> None:
        with patch.object(health, "MAX_EVENTS", 3), patch.object(health, "PRUNE_EVERY", 1):
            for value in range(6):
                self.store.add("latency", "m", float(value))

        self.assertEqual([e.value for e in self.store.events(0)], [3.0, 4.0, 5.0])

    def test_clear_and_broken_file(self) -> None:
        self.store.add("wake", "jarvis", 0.8)
        self.store.clear()
        self.assertEqual(self.store.events(0), [])

        self.path.write_text("isto não é sqlite", encoding="utf-8")
        broken = HealthStore(self.path)
        broken.add("wake", "jarvis", 0.8)
        self.assertEqual(broken.events(0), [])


class SummaryTests(unittest.TestCase):
    def test_empty_history_has_no_suggestions(self) -> None:
        result = summary([])

        self.assertEqual(result["events"], 0)
        self.assertEqual(result["suggestions"], [])
        self.assertEqual([item["word"] for item in result["wake"]], ["friday", "jarvis"])

    def test_friday_waking_without_speech_asks_for_a_higher_threshold(self) -> None:
        events = [sample("wake", "friday", 0.72, ago=i * 600) for i in range(5)]
        events += [sample("wake_silent", "friday", ago=i * 600) for i in range(4)]

        result = summary(events)

        friday = next(item for item in result["wake"] if item["word"] == "friday")
        self.assertEqual((friday["activations"], friday["silent"]), (5, 4))
        self.assertEqual(
            texts(result), ["O “Friday” ativou 4 vezes sem você falar em 7 dias: suba JARVIS_WAKE_THRESHOLD_FRIDAY para 0.80."]
        )

    def test_many_near_misses_ask_for_a_lower_threshold(self) -> None:
        events = [sample("wake_near", "jarvis", 0.4 + i / 100, ago=i * 60) for i in range(6)]
        events.append(sample("wake", "jarvis", 0.9))

        result = summary(events, days=1)

        jarvis = next(item for item in result["wake"] if item["word"] == "jarvis")
        self.assertEqual((jarvis["near"], jarvis["near_best"]), (6, 0.45))
        self.assertEqual(
            texts(result), ["O “Jarvis” quase ativou 6 vezes hoje: se era você chamando, desça JARVIS_WAKE_THRESHOLD_JARVIS para 0.45."]
        )

    def test_near_misses_with_as_many_activations_are_fine(self) -> None:
        events = [sample("wake_near", "jarvis", 0.4, ago=i * 60) for i in range(5)]
        events += [sample("wake", "jarvis", 0.9, ago=i * 60) for i in range(5)]

        self.assertEqual(summary(events)["suggestions"], [])

    def test_response_time_got_worse_since_yesterday(self) -> None:
        events = [sample("latency", "gemini-x", 1.2, ago=DAY_S + 3600 + i) for i in range(5)]
        events += [sample("latency", "gemini-x", 1.9, ago=3600 + i) for i in range(5)]

        result = summary(events)

        self.assertEqual((result["latency"]["prev24"], result["latency"]["last24"]), (1.2, 1.9))
        self.assertEqual([day["count"] for day in result["latency"]["daily"]], [5, 5])
        self.assertEqual(texts(result), ["O tempo de resposta piorou desde ontem: mediana de 1,2 s para 1,9 s."])

    def test_few_samples_or_small_change_say_nothing_about_latency(self) -> None:
        few = [sample("latency", "m", 1.0, ago=DAY_S + 60), sample("latency", "m", 3.0, ago=60)]
        small = [sample("latency", "m", 1.0, ago=DAY_S + 60 + i) for i in range(5)]
        small += [sample("latency", "m", 1.2, ago=60 + i) for i in range(5)]

        self.assertEqual(summary(few)["suggestions"], [])
        self.assertEqual(summary(small)["suggestions"], [])

    def test_failing_tool_and_quota_pauses(self) -> None:
        events = [sample("tool_error", "get_weather", detail=f"timeout {i}", ago=600 - i) for i in range(3)]
        events.append(sample("tool_error", "open_app", detail="não achei"))
        events += [sample("model_pause", "gemini-live", detail="quota", ago=i * 60) for i in range(3)]
        events.append(sample("model_pause", "gemini-live", detail="overloaded"))
        events.append(sample("model_switch", "gemini-reserva", detail="gemini-live"))

        result = summary(events)

        self.assertEqual(result["tools"][0], {"name": "get_weather", "errors": 3, "last": "timeout 2"})
        self.assertEqual(result["models"]["switches"], 1)
        self.assertEqual(result["models"]["pauses"][0], {"model": "gemini-live", "reason": "quota", "count": 3})
        self.assertEqual(
            texts(result),
            [
                "A ferramenta get_weather falhou 3 vezes em 7 dias: último erro “timeout 2”.",
                "O gemini-live pausou por cota 3 vezes em 7 dias: ponha um reserva em GOOGLE_FALLBACK_MODELS "
                "ou ligue o rodízio com JARVIS_MODEL_ROTATION=rotate.",
            ],
        )

    def test_memory_searches_that_found_nothing(self) -> None:
        events = [sample("memory_search", "nada") for _ in range(2)]
        events += [sample("memory_search", "sentido", 0.7), sample("memory_search", "palavras", 0.9), sample("memory_search", "sentido", 0.65)]

        result = summary(events)

        self.assertEqual(result["memory"], {"searches": 5, "empty": 2, "average": 0.75, "min_similarity": 0.6})
        self.assertEqual(
            texts(result),
            ["2 de 5 buscas na memória não acharam nada: se o fato existia, desça JARVIS_MEMORY_MIN_SIMILARITY (hoje 0.60)."],
        )

    def test_window_leaves_older_events_out(self) -> None:
        events = [sample("wake_silent", "friday", ago=2 * DAY_S + i) for i in range(4)]

        self.assertEqual(summary(events, days=1)["events"], 0)
        self.assertEqual(len(summary(events, days=7)["suggestions"]), 1)

    def test_word_without_detector_threshold_still_shows(self) -> None:
        result = summary([sample("wake_silent", "friday", ago=i) for i in range(3)], thresholds={})

        self.assertEqual(result["wake"][0]["threshold"], None)
        self.assertEqual(texts(result), ["O “Friday” ativou 3 vezes sem você falar em 7 dias: suba JARVIS_WAKE_THRESHOLD_FRIDAY."])


class ReportTests(unittest.TestCase):
    def test_posts_the_event_in_the_background(self) -> None:
        sent: list[tuple[str, dict]] = []
        with patch.dict(os.environ, {"JARVIS_HUD_URL": "http://127.0.0.1:8123/"}):
            report("latency", "gemini-x", 1.23456, post=lambda url, body: sent.append((url, body)))
        for _ in range(100):
            if sent:
                break
            time.sleep(0.01)

        self.assertEqual(sent, [("http://127.0.0.1:8123/api/health/event", {"kind": "latency", "key": "gemini-x", "value": 1.235})])

    def test_server_down_is_silent(self) -> None:
        import requests

        with patch.object(health.requests, "post", side_effect=requests.ConnectionError("recusado")) as post:
            REAL_POST("http://127.0.0.1:1/api/health/event", {"kind": "latency", "key": "m"})

        post.assert_called_once()


class ApiTests(unittest.TestCase):
    def client(self, env: dict[str, str] | None = None, base_url: str = LOCAL) -> TestClient:
        patcher = patch.dict(os.environ, {"GOOGLE_API_KEY": "k", **(env or {})}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = HealthStore(Path(folder.name) / "saude.db")
        app = create_app(reload_env=False, calendar_reminders=False, proactive=lambda hub: None, health_store=self.store)
        return TestClient(app, base_url=base_url)

    def test_agent_posts_and_hud_reads(self) -> None:
        client = self.client({"JARVIS_WAKE_WORD": "true", "JARVIS_WAKE_WORDS": "jarvis,friday"})

        for _ in range(3):
            self.assertEqual(client.post("/api/health/event", json={"kind": "wake_silent", "key": "friday"}).json(), {"ok": True})
        client.post("/api/health/event", json={"kind": "latency", "key": "gemini-x", "value": 1.4})
        body = client.get("/api/health?days=1").json()

        self.assertTrue(body["enabled"])
        self.assertEqual(body["latency"]["count"], 1)
        friday = next(item for item in body["wake"] if item["word"] == "friday")
        self.assertEqual((friday["silent"], friday["threshold"]), (3, 0.7))
        self.assertIn("JARVIS_WAKE_THRESHOLD_FRIDAY para 0.80", body["suggestions"][0]["text"])

    def test_rejects_unknown_kinds_and_wakes_from_outside(self) -> None:
        client = self.client()

        self.assertEqual(client.post("/api/health/event", json={"kind": "wake", "key": "jarvis"}).status_code, 422)
        self.assertEqual(client.post("/api/health/event", json={"kind": "latency", "key": "m", "value": -1}).status_code, 422)
        self.assertEqual(client.post("/api/health/event", json={"kind": "latency", "key": ""}).status_code, 422)
        self.assertEqual(self.store.events(0), [])

    def test_other_sites_and_hosts_are_refused(self) -> None:
        client = self.client()
        cross = {"Sec-Fetch-Site": "cross-site"}

        self.assertEqual(client.get("/api/health", headers=cross).status_code, 403)
        self.assertEqual(client.post("/api/health/event", json={"kind": "wake_silent", "key": "x"}, headers=cross).status_code, 403)
        self.assertEqual(client.delete("/api/health", headers=cross).status_code, 403)
        rebinding = self.client(base_url="http://evil.example:8000")
        self.assertEqual(rebinding.get("/api/health").status_code, 403)
        self.assertEqual(self.store.events(0), [])

    def test_clear(self) -> None:
        client = self.client()
        client.post("/api/health/event", json={"kind": "tool_error", "key": "open_app", "detail": "falhou"})

        self.assertEqual(client.delete("/api/health").json(), {"ok": True})
        self.assertEqual(self.store.events(0), [])

    def test_turned_off(self) -> None:
        client = self.client({"JARVIS_HEALTH": "false"})

        self.assertEqual(client.post("/api/health/event", json={"kind": "wake_silent", "key": "jarvis"}).json(), {"ok": False})
        self.assertEqual(client.get("/api/health").json(), {"enabled": False})
        self.assertEqual(self.store.events(0), [])

    def test_accepted_wake_is_recorded_by_the_server(self) -> None:
        client = self.client({"JARVIS_WAKE_WORD": "true"})
        client.app.state.wake_hub.connect("aba-de-teste-1234")
        headers = {"X-Jarvis-Wake": "1"}

        client.post("/api/wake/trigger", json={"score": 0.83}, headers=headers)
        # Link já abrindo: o segundo aviso é recusado e não conta como ativação.
        client.post("/api/wake/trigger", json={"score": 0.91}, headers=headers)

        self.assertEqual([(e.kind, e.key, e.value) for e in self.store.events(0)], [("wake", "jarvis", 0.83)])


class FakeModel:
    words = ("jarvis",)

    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores)

    def predict(self, frame: object) -> dict[str, float]:
        return {"jarvis": self.scores.pop(0) if self.scores else 0.0}

    def reset(self) -> None:
        pass


class NearMissTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.detector = WakeDetector(FakeModel([]), {"jarvis": 0.5}, clock=lambda: self.now)
        self.near = NearMisses(self.detector, clock=lambda: self.now)

    def feed(self, *scores: float) -> list[tuple[str, float]]:
        found = []
        for score in scores:
            found += self.near.feed({"jarvis": score})
            self.now += 0.08
        return found

    def test_one_event_per_utterance_with_its_peak(self) -> None:
        found = self.feed(0.1, 0.32, 0.41, 0.36, *([0.0] * 20))

        self.assertEqual(found, [("jarvis", 0.41)])

    def test_low_scores_and_real_wakes_are_not_near_misses(self) -> None:
        self.assertEqual(self.feed(*([0.29] * 30)), [])
        self.feed(0.35, 0.45)
        self.near.discard()
        self.assertEqual(self.feed(0.6, *([0.0] * 30)), [])

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def test_detector_loop_reports_near_misses(self) -> None:
        from wake_word import DetectorState

        class Stream:
            description = "teste"

            def __init__(inner) -> None:
                pass

            def read(inner, timeout: float) -> np.ndarray:
                self.now += 0.08
                return np.full(1280, 300, dtype=np.int16)

            def close(inner) -> None:
                pass

        class Link:
            def __init__(inner) -> None:
                inner.near_calls: list[tuple[str, float]] = []

            def state(inner, mic_silent: bool = False, words: tuple[str, ...] = ()) -> DetectorState:
                return DetectorState(listen=True)

            def near(inner, word: str, score: float) -> None:
                inner.near_calls.append((word, score))

            def trigger(inner, score: float, word: str | None = None) -> dict:
                return {"accepted": True}

        self.detector.model = FakeModel([0.0] * 30 + [0.38, 0.42, 0.2] + [0.0] * 30)
        link = Link()
        with patch("builtins.print"):
            run(
                link,  # type: ignore[arg-type]
                self.detector,
                open_mic=lambda label: Stream(),
                clock=lambda: self.now,
                sleep=self.advance,
                keep_running=lambda: self.now < 8.0,
                near=self.near,
            )

        self.assertEqual(link.near_calls, [("jarvis", 0.42)])

    def test_server_link_posts_the_near_miss(self) -> None:
        class Http:
            def __init__(inner) -> None:
                inner.calls: list[tuple[str, dict]] = []

            def post(inner, url: str, json: dict, timeout: float) -> None:
                inner.calls.append((url, json))

        http = Http()
        ServerLink("http://127.0.0.1:8000/", "segredo", http=http).near("friday", 0.51234)

        self.assertEqual(http.calls, [("http://127.0.0.1:8000/api/health/event", {"kind": "wake_near", "key": "friday", "value": 0.512})])


class SourcesTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_errors_and_latency_are_reported(self) -> None:
        import hud

        with patch.object(hud, "report_health") as reported, patch.object(hud, "publish_hud_event", return_value=True):
            await hud.tool_status("get_weather", "running")
            await hud.tool_status("get_weather", "error", "timeout")

        reported.assert_called_once_with("tool_error", "get_weather", detail="timeout")

    def test_response_time_is_reported(self) -> None:
        import hud

        handlers: dict[str, object] = {}

        class Session:
            def on(self, name: str):
                def register(handler):
                    handlers[name] = handler
                    return handler

                return register

        class State:
            def __init__(self, old: str, new: str) -> None:
                self.old_state, self.new_state = old, new

        hud.watch_response_time(Session(), lambda: "gemini-x")
        with patch.object(hud, "report_health") as reported, patch.object(hud, "_publish_soon"):
            handlers["user_state_changed"](State("speaking", "listening"))  # type: ignore[operator]
            handlers["agent_state_changed"](State("thinking", "speaking"))  # type: ignore[operator]

        kind, model, seconds = reported.call_args.args
        self.assertEqual((kind, model), ("latency", "gemini-x"))
        self.assertLess(seconds, 1.0)

    def test_memory_search_note(self) -> None:
        import memory
        from memory import Hit

        with patch.object(memory, "report_health") as reported:
            memory._report_search([])
            memory._report_search([Hit({"id": "1"}, 1.2, 0.72, by_meaning=True), Hit({"id": "2"}, 1.0, 0.8)])
            memory._report_search([Hit({"id": "3"}, 1.0, None)])

        self.assertEqual(
            [call.args for call in reported.call_args_list],
            [("memory_search", "nada", None), ("memory_search", "sentido", 0.8), ("memory_search", "palavras", None)],
        )


if __name__ == "__main__":
    unittest.main()
