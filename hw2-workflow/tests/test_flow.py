"""End-to-end tests for the Mini SE workflow (offline, no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import drop, make_workspace  # noqa: E402
from workflow.cli import make_llm  # noqa: E402
from workflow.engine import Engine  # noqa: E402
from workflow.flows import build_mini_se_flow, design_gate, review_gate  # noqa: E402
from workflow.llm_bridge import MockLLM  # noqa: E402
from workflow.state import WorkflowState  # noqa: E402
from workflow.tracing import Tracer  # noqa: E402


class MiniFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_workspace()
        self.run_dir = self.root / "run"
        self.tracer = Tracer(self.run_dir / "trace.jsonl", verbose=False)

    def tearDown(self) -> None:
        drop(self.root)

    def _run(self):
        workflow = build_mini_se_flow(MockLLM(), self.run_dir)
        engine = Engine(workflow, tracer=self.tracer)
        return engine.run("Build a word counter with input validation.")

    def test_end_to_end_completes(self) -> None:
        result = self._run()
        self.assertTrue(result.ok, result.state.errors)
        for key in ("requirement", "design", "code", "review", "docs", "summary"):
            self.assertTrue(result.state.get(key), "missing artifact {k}".format(k=key))

    def test_review_fails_once_then_the_loop_fixes_it(self) -> None:
        result = self._run()
        self.assertEqual(result.state.visits["coding"], 2)
        self.assertEqual(result.state.visits["review_gate"], 2)
        self.assertEqual(result.state.get("review_verdict"), "approve with nits")

    def test_generated_code_is_written_and_importable(self) -> None:
        result = self._run()
        code_path = self.run_dir / "artifacts" / "code.py"
        self.assertTrue(code_path.is_file())
        source = code_path.read_text(encoding="utf-8")
        self.assertIn("def transform", source)
        compile(source, str(code_path), "exec")  # must be syntactically valid

    def test_reviewer_feedback_is_sent_to_the_coder(self) -> None:
        result = self._run()
        feedback = [m for m in result.state.messages
                    if m.sender == "review_gate" and m.recipient == "coding"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0].kind, "feedback")
        self.assertIn("requested changes", feedback[0].content)

    def test_trace_records_the_jump(self) -> None:
        self._run()
        trace = self.tracer.path.read_text(encoding="utf-8")
        self.assertIn('"jump"', trace)
        self.assertIn('"review_gate"', trace)
        self.assertIn('"done"', trace)

    def test_summary_is_last_artifact(self) -> None:
        result = self._run()
        self.assertEqual(result.executed[-1], "summary")

    def test_state_serialises_to_json(self) -> None:
        result = self._run()
        payload = result.state.to_dict()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("artifacts", payload)
        self.assertIn("messages", payload)

    def test_make_llm_returns_offline_model_without_key(self) -> None:
        self.assertIsInstance(make_llm(provider="mock"), MockLLM)


class GateTest(unittest.TestCase):
    def state(self, **artifacts: str) -> WorkflowState:
        state = WorkflowState(task="demo")
        for key, value in artifacts.items():
            state.set(key, value)
        return state

    def test_design_gate_rejects_empty(self) -> None:
        passed, reason = design_gate(self.state())
        self.assertFalse(passed)
        self.assertIn("nothing", reason)

    def test_design_gate_rejects_thin_documents(self) -> None:
        passed, reason = design_gate(self.state(design="## A\ntoo short"))
        self.assertFalse(passed)
        self.assertIn("thin", reason)

    def test_design_gate_rejects_unstructured_documents(self) -> None:
        body = "x" * 200
        passed, reason = design_gate(self.state(design=body))
        self.assertFalse(passed)
        self.assertIn("sections", reason)

    def test_design_gate_accepts_a_real_document(self) -> None:
        doc = "## Overview\n" + "y" * 120 + "\n## Modules\n## Test plan\n"
        passed, _ = design_gate(self.state(design=doc))
        self.assertTrue(passed)

    def test_review_gate_blocks_on_request_changes(self) -> None:
        passed, _ = review_gate(self.state(review_verdict="request changes"))
        self.assertFalse(passed)

    def test_review_gate_passes_on_approval(self) -> None:
        passed, _ = review_gate(self.state(review_verdict="approve with nits"))
        self.assertTrue(passed)

    def test_review_gate_blocks_without_a_review(self) -> None:
        passed, reason = review_gate(self.state())
        self.assertFalse(passed)
        self.assertIn("no review", reason)


if __name__ == "__main__":
    unittest.main()
