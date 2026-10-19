import asyncio
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from model_pool import COOLDOWNS, ModelPool, classify_failure, cooldown_until

MODELS = ("gemini-3.8-live", "gemini-3.1-flash-live-preview", "gemini-2.5-flash-native-audio-preview-12-2025")


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ClassifyFailureTests(unittest.TestCase):
    def test_kinds_of_gemini_live_failures(self) -> None:
        cases = {
            "429 RESOURCE_EXHAUSTED: You exceeded your current quota": "quota",
            "received 1011 (internal error) The service is currently unavailable": "overloaded",
            "503 UNAVAILABLE: The model is overloaded. Please try again later.": "overloaded",
            "1008 models/gemini-x is not found for API version v1beta": "unavailable",
            "1007 Request contains an invalid argument": "context",
            "Failed to connect to Gemini Live": "error",
        }
        for text, kind in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_failure(text), kind)

    def test_reads_the_cause_of_the_plugin_error(self) -> None:
        try:
            try:
                raise RuntimeError("429 Too Many Requests")
            except RuntimeError as exc:
                raise ConnectionError("Failed to connect to Gemini Live") from exc
        except ConnectionError as error:
            self.assertEqual(classify_failure(error), "quota")

    def test_daily_quota_waits_for_midnight_in_california(self) -> None:
        zone = ZoneInfo("America/Los_Angeles")
        now = dt.datetime(2026, 10, 19, 15, 0, tzinfo=zone).timestamp()
        until = cooldown_until("quota", "Quota exceeded for GenerateRequestsPerDayPerProjectPerModel", now)
        self.assertEqual(dt.datetime.fromtimestamp(until, zone).strftime("%Y-%m-%d %H:%M"), "2026-10-20 00:00")
        self.assertEqual(cooldown_until("quota", "per minute", now), now + COOLDOWNS["quota"])


class ModelPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "modelos.json"
        self.clock = Clock()

    def tearDown(self) -> None:
        self.dir.cleanup()

    def pool(self, rotate: bool = False) -> ModelPool:
        return ModelPool(MODELS, rotate=rotate, path=self.path, clock=self.clock)

    def test_fallback_prefers_the_primary_until_it_fails(self) -> None:
        self.assertEqual(self.pool().first(), MODELS[0])
        self.assertEqual(self.pool().mark_failed(MODELS[0], "429 quota"), "quota")
        # A new link (new process) reads the pause from the file.
        self.assertEqual(self.pool().first(), MODELS[1])
        self.clock.now += COOLDOWNS["quota"] + 1
        self.assertEqual(self.pool().first(), MODELS[0])

    def test_next_after_skips_paused_models_and_wraps(self) -> None:
        pool = self.pool()
        pool.mark_failed(MODELS[1], "503 overloaded")
        self.assertEqual(pool.next_after(MODELS[0]), MODELS[2])
        self.assertEqual(pool.next_after(MODELS[2]), MODELS[0])
        pool.mark_failed(MODELS[0], "429")
        pool.mark_failed(MODELS[2], "429")
        self.assertIsNone(pool.next_after(MODELS[2]))

    def test_all_paused_tries_the_one_back_first(self) -> None:
        pool = self.pool()
        pool.mark_failed(MODELS[0], "1008 not found")  # 6 h
        pool.mark_failed(MODELS[1], "429 quota")  # 30 min
        pool.mark_failed(MODELS[2], "Failed to connect")  # 2 min
        self.assertEqual(pool.first(), MODELS[2])

    def test_rotation_takes_turns_between_links(self) -> None:
        firsts = [self.pool(rotate=True).first() for _ in range(4)]
        self.assertEqual(firsts, [MODELS[0], MODELS[1], MODELS[2], MODELS[0]])

    def test_a_full_session_does_not_pause_the_model(self) -> None:
        pool = self.pool()
        self.assertEqual(pool.mark_failed(MODELS[0], "1007 context exhausted"), "context")
        self.assertTrue(pool.available(MODELS[0]))

    def test_a_broken_state_file_is_ignored(self) -> None:
        self.path.write_text("{não é json", encoding="utf-8")
        self.assertEqual(self.pool().first(), MODELS[0])
        self.assertIn("livre", self.pool().describe()[0])


class FakeSession:
    def __init__(self, agent: object) -> None:
        self.current_agent = agent
        self.handlers: dict[str, object] = {}
        self.updated: list[object] = []

    def on(self, name: str):
        def register(handler):
            self.handlers[name] = handler
            return handler

        return register

    def update_agent(self, agent: object) -> None:
        self.current_agent = agent
        self.updated.append(agent)


class FailoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.pool = ModelPool(MODELS, path=Path(self.dir.name) / "modelos.json", clock=Clock())

    def tearDown(self) -> None:
        self.dir.cleanup()

    def run_failover(self, *errors: str) -> tuple[SimpleNamespace, FakeSession]:
        from livekit.agents import llm

        from backends import JarvisAgent, watch_model_failover
        from settings import load_settings

        async def scenario() -> tuple[SimpleNamespace, FakeSession]:
            settings = load_settings({"GOOGLE_API_KEY": "test-key"})
            session = FakeSession(JarvisAgent("Você é o Jarvis."))
            runtime = SimpleNamespace(settings=settings, session=session, agent=session.current_agent, model=MODELS[0])
            watch_model_failover(runtime, self.pool)
            for text in errors:
                session.handlers["error"](
                    SimpleNamespace(
                        error=llm.RealtimeModelError(timestamp=0, label="gemini", error=RuntimeError(text), recoverable=False)
                    )
                )
                await asyncio.sleep(0)
                await asyncio.sleep(0)
            return runtime, session

        return asyncio.run(scenario())

    def test_quota_moves_the_conversation_to_the_next_model(self) -> None:
        runtime, session = self.run_failover("429 RESOURCE_EXHAUSTED quota")

        self.assertEqual(runtime.model, MODELS[1])
        self.assertEqual(len(session.updated), 1)
        agent = session.updated[0]
        self.assertTrue(agent.resumed)
        self.assertEqual(agent.llm.model, MODELS[1])
        self.assertFalse(self.pool.available(MODELS[0]))

    def test_full_session_restarts_once_on_the_same_model(self) -> None:
        runtime, session = self.run_failover("1007 invalid argument", "1007 invalid argument")

        self.assertEqual([agent.llm.model for agent in session.updated], [MODELS[0], MODELS[1]])
        self.assertEqual(runtime.model, MODELS[1])

    def test_recoverable_errors_are_left_to_the_plugin(self) -> None:
        from livekit.agents import llm

        from backends import JarvisAgent, watch_model_failover
        from settings import load_settings

        session = FakeSession(JarvisAgent("Você é o Jarvis."))
        runtime = SimpleNamespace(
            settings=load_settings({"GOOGLE_API_KEY": "test-key"}), session=session, agent=None, model=MODELS[0]
        )
        watch_model_failover(runtime, self.pool)
        session.handlers["error"](
            SimpleNamespace(error=llm.RealtimeModelError(timestamp=0, label="g", error=RuntimeError("429"), recoverable=True))
        )
        self.assertEqual(session.updated, [])
        self.assertTrue(self.pool.available(MODELS[0]))


if __name__ == "__main__":
    unittest.main()
