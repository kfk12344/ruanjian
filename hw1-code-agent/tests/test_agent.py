"""Tests for the agent loop: JSON parsing, tool dispatch, retries, stop rules."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import drop, make_workspace  # noqa: E402
from codeagent.agent import CodeAgent, extract_json_object  # noqa: E402
from codeagent.config import load_settings  # noqa: E402
from codeagent.llm import LLMError, ScriptedLLM  # noqa: E402

SOURCE = '''def divide(a, b):
    try:
        return a / b
    except:
        return None
'''


def action(name: str, payload: dict) -> str:
    return json.dumps({"thought": "go", "action": name, "action_input": payload})


def final(text: str) -> str:
    return json.dumps({"thought": "done", "final_answer": text})


class ExtractJsonTest(unittest.TestCase):
    def test_plain_object(self) -> None:
        self.assertEqual(extract_json_object('{"a": 1}'), {"a": 1})

    def test_fenced_object(self) -> None:
        self.assertEqual(extract_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_around_object(self) -> None:
        self.assertEqual(extract_json_object('Sure! {"a": 1} hope that helps'), {"a": 1})

    def test_braces_inside_strings(self) -> None:
        payload = '{"thought": "use {braces}", "action": "read_file"}'
        self.assertEqual(extract_json_object(payload)["action"], "read_file")

    def test_escaped_quotes(self) -> None:
        payload = r'{"final_answer": "he said \"hi\" }"}'
        self.assertIn("hi", extract_json_object(payload)["final_answer"])

    def test_no_json_returns_none(self) -> None:
        self.assertIsNone(extract_json_object("I cannot help with that."))
        self.assertIsNone(extract_json_object(""))

    def test_unbalanced_returns_none(self) -> None:
        self.assertIsNone(extract_json_object('{"a": 1'))


class AgentLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_workspace()
        (self.root / "target.py").write_text(SOURCE, encoding="utf-8")
        self.settings = load_settings(
            provider="mock", workspace=self.root, max_steps=6, max_retries=1)

    def tearDown(self) -> None:
        drop(self.root)

    def agent(self, replies) -> CodeAgent:
        return CodeAgent(llm=ScriptedLLM(replies), settings=self.settings)

    def test_read_then_final(self) -> None:
        result = self.agent([
            action("read_file", {"path": "target.py"}),
            final("looks fine"),
        ]).run("review target.py")

        self.assertEqual(result.final_answer, "looks fine")
        self.assertEqual(result.stopped_reason, "final_answer")
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(len(result.steps), 2)
        self.assertIn("except:", result.steps[0].observation)

    def test_observation_is_fed_back_to_the_model(self) -> None:
        llm = ScriptedLLM([
            action("read_file", {"path": "target.py"}),
            final("done"),
        ])
        CodeAgent(llm=llm, settings=self.settings).run("review target.py")
        second_call = llm.calls[1]
        self.assertTrue(any(
            m["content"].startswith("OBSERVATION[read_file]") for m in second_call
        ))

    def test_bad_json_gets_one_correction_then_proceeds(self) -> None:
        result = self.agent([
            "sorry, I will just describe the code",
            action("read_file", {"path": "target.py"}),
            final("ok"),
        ]).run("review target.py")
        self.assertEqual(result.stopped_reason, "final_answer")
        self.assertEqual(result.final_answer, "ok")
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(len(result.steps), 2)

    def test_three_bad_replies_stop_the_run(self) -> None:
        result = self.agent(["nope", "still nope", "nope again"]).run("review target.py")
        self.assertEqual(result.stopped_reason, "model_output_not_json")

    def test_unknown_tool_is_reported_to_the_model(self) -> None:
        llm = ScriptedLLM([
            action("rm_rf", {"path": "/"}),
            final("gave up"),
        ])
        result = CodeAgent(llm=llm, settings=self.settings).run("review target.py")
        self.assertIn("ERROR:", result.steps[0].observation)
        self.assertIn("rm_rf", result.steps[0].observation)

    def test_missing_tool_argument_does_not_crash(self) -> None:
        result = self.agent([
            action("read_file", {}),
            final("done"),
        ]).run("review target.py")
        self.assertTrue(result.steps[0].observation.startswith("ERROR:"))

    def test_max_steps_is_enforced(self) -> None:
        replies = [action("list_files", {"path": "."}) for _ in range(10)]
        result = self.agent(replies).run("loop forever", max_steps=3)
        self.assertEqual(result.stopped_reason, "max_steps_reached")
        self.assertEqual(len(result.steps), 3)

    def test_provider_outage_is_retried(self) -> None:
        class FlakyLLM(ScriptedLLM):
            def __init__(self):
                super().__init__([final("recovered")])
                self.failures = 1

            def complete(self, messages, temperature=None, max_tokens=None):
                if self.failures:
                    self.failures -= 1
                    raise LLMError("temporary 503")
                return super().complete(messages, temperature, max_tokens)

        settings = load_settings(
            provider="mock", workspace=self.root, max_retries=3, retry_backoff=0.0)
        result = CodeAgent(llm=FlakyLLM(), settings=settings).run("review target.py")
        self.assertEqual(result.final_answer, "recovered")

    def test_memory_keeps_the_exchange_for_later_turns(self) -> None:
        agent = self.agent([final("first"), final("second")])
        agent.run("first question")
        agent.run("second question")
        contents = [turn.content for turn in agent.memory.turns]
        self.assertIn("first question", contents)
        self.assertIn("first", contents)

    def test_events_are_emitted(self) -> None:
        seen = []
        agent = CodeAgent(
            llm=ScriptedLLM([action("read_file", {"path": "target.py"}), final("ok")]),
            settings=self.settings,
            on_event=lambda kind, payload: seen.append(kind),
        )
        agent.run("review target.py")
        self.assertIn("action", seen)
        self.assertIn("final", seen)
        self.assertIn("done", seen)


if __name__ == "__main__":
    unittest.main()
