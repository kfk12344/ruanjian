"""Tests for the offline model and the provider factory."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codeagent.agent import extract_json_object  # noqa: E402
from codeagent.config import load_settings  # noqa: E402
from codeagent.llm import (  # noqa: E402
    LLMError,
    MockLLM,
    OpenAICompatibleLLM,
    ScriptedLLM,
    build_offline_review,
    create_llm,
    retry_with_backoff,
)

SYSTEM_PROMPT = "You are CodePilot.\nTARGET_FILE: examples/buggy_calculator.py"
TASK = "Review the Python file `examples/buggy_calculator.py`.\nTARGET_FILE: examples/buggy_calculator.py"


class ProviderFactoryTest(unittest.TestCase):
    def test_auto_detects_mock_without_key(self) -> None:
        settings = load_settings(env={})
        self.assertEqual(settings.provider, "mock")
        self.assertIsInstance(create_llm(settings), MockLLM)

    def test_auto_detects_openai_with_key(self) -> None:
        settings = load_settings(env={"OPENAI_API_KEY": "sk-test"})
        self.assertEqual(settings.provider, "openai")
        self.assertIsInstance(create_llm(settings), OpenAICompatibleLLM)

    def test_explicit_provider_wins(self) -> None:
        settings = load_settings(env={"CODEAGENT_PROVIDER": "mock", "OPENAI_API_KEY": "sk-test"})
        self.assertIsInstance(create_llm(settings), MockLLM)

    def test_scripted_llm_wins_when_replies_given(self) -> None:
        settings = load_settings(env={})
        self.assertIsInstance(create_llm(settings, replies=["x"]), ScriptedLLM)

    def test_unknown_provider_raises(self) -> None:
        settings = load_settings(env={"CODEAGENT_PROVIDER": "telepathy"})
        with self.assertRaises(LLMError):
            create_llm(settings)

    def test_openai_client_requires_key(self) -> None:
        settings = load_settings(env={"CODEAGENT_PROVIDER": "openai"})
        with self.assertRaises(LLMError):
            OpenAICompatibleLLM(settings)


class MockPolicyTest(unittest.TestCase):
    def test_first_turn_requests_the_target_file(self) -> None:
        reply = MockLLM().complete([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TASK},
        ])
        payload = extract_json_object(reply)
        self.assertEqual(payload["action"], "read_file")
        self.assertEqual(payload["action_input"]["path"], "examples/buggy_calculator.py")

    def test_second_turn_searches_the_file(self) -> None:
        reply = MockLLM().complete([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TASK},
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "OBSERVATION[read_file] 1 | def f():"},
        ])
        payload = extract_json_object(reply)
        self.assertEqual(payload["action"], "search_code")

    def test_third_turn_returns_a_review(self) -> None:
        reply = MockLLM().complete([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TASK},
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "OBSERVATION[read_file] 1 | def f():\n2 |     except:"},
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "OBSERVATION[search_code] hit"},
        ])
        payload = extract_json_object(reply)
        self.assertIn("final_answer", payload)
        self.assertIn("# Code review", payload["final_answer"])

    def test_workflow_mode_returns_a_template(self) -> None:
        reply = MockLLM().complete([
            {"role": "system", "content": "[WORKFLOW-REQUIREMENT] write a spec"},
            {"role": "user", "content": "TASK: build a word counter"},
        ])
        self.assertIn("# Requirements", reply)
        self.assertIn("build a word counter", reply)


class OfflineReviewTest(unittest.TestCase):
    def test_review_flags_real_defects(self) -> None:
        source = "\n".join([
            "def f(x=[]):",
            "    try:",
            "        return eval(x)",
            "    except:",
            "        return None",
            "",
            "def g(v):",
            "    if v == None:",
            "        return False",
        ])
        report = build_offline_review("demo.py", source)
        self.assertIn("HIGH", report)
        self.assertIn("Mutable default argument", report)
        self.assertIn("eval()", report)
        self.assertIn("request changes", report)

    def test_clean_source_gets_a_passing_verdict(self) -> None:
        report = build_offline_review("clean.py", "def add(a, b):\n    return a + b\n")
        self.assertIn("approve with nits", report)
        self.assertIn("No rule-based issues detected", report)


class RetryTest(unittest.TestCase):
    def test_retries_then_succeeds(self) -> None:
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise LLMError("boom")
            return "ok"

        result = retry_with_backoff(flaky, attempts=3, backoff=0.0, sleep=lambda _s: None)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)

    def test_gives_up_after_the_last_attempt(self) -> None:
        def always():
            raise LLMError("down")

        with self.assertRaises(LLMError):
            retry_with_backoff(always, attempts=2, backoff=0.0, sleep=lambda _s: None)


if __name__ == "__main__":
    unittest.main()
