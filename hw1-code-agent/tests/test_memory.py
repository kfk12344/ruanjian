"""Tests for the character-budgeted conversation memory."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codeagent.memory import ConversationMemory  # noqa: E402


class MemoryTest(unittest.TestCase):
    def test_history_preserves_order(self) -> None:
        memory = ConversationMemory(max_chars=1000)
        memory.add_user("hello")
        memory.add_assistant("hi there")
        roles = [m["role"] for m in memory.history()]
        self.assertEqual(roles, ["user", "assistant"])

    def test_budget_evicts_whole_exchanges(self) -> None:
        memory = ConversationMemory(max_chars=40)
        memory.add_user("a" * 30)
        memory.add_assistant("b" * 30)
        memory.add_user("c" * 5)
        memory.add_assistant("d" * 5)
        self.assertLessEqual(memory.size, 40)
        # Even number of turns: no orphaned assistant message.
        self.assertEqual(len(memory.turns) % 2, 0)

    def test_evicted_content_is_digested(self) -> None:
        memory = ConversationMemory(max_chars=60)
        memory.add_user("the secret keyword is ORANGE")
        memory.add_assistant("noted: ORANGE")
        for _ in range(5):
            memory.add_user("filler " * 10)
            memory.add_assistant("ok " * 10)
        self.assertIn("ORANGE", memory.digest)

    def test_digest_appears_as_leading_system_message(self) -> None:
        memory = ConversationMemory(max_chars=10)
        memory.add_user("x" * 50)
        memory.add_assistant("y" * 50)
        history = memory.history()
        self.assertEqual(history[0]["role"], "system")
        self.assertIn("EARLIER CONTEXT DIGEST", history[0]["content"])

    def test_reset_clears_everything(self) -> None:
        memory = ConversationMemory()
        memory.add_user("anything")
        memory.reset()
        self.assertEqual(memory.history(), [])
        self.assertEqual(memory.digest, "")

    def test_invalid_role_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConversationMemory().add("system", "nope")

    def test_snapshot_is_json(self) -> None:
        memory = ConversationMemory()
        memory.add_user("hi")
        self.assertIn('"turns"', memory.snapshot())


if __name__ == "__main__":
    unittest.main()
