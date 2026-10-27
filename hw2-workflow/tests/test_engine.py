"""Tests for the workflow engine: ordering, branching, loops, retries, parallel."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import drop, make_workspace  # noqa: E402
from workflow.engine import Engine, ParallelStep, Step, Workflow  # noqa: E402
from workflow.messages import AgentMessage  # noqa: E402
from workflow.nodes import FunctionNode, NodeResult, NodeStatus  # noqa: E402
from workflow.state import FlowError, WorkflowState  # noqa: E402
from workflow.tracing import Tracer  # noqa: E402


def recorder(name: str, log: list, artifact: str = "") -> FunctionNode:
    def run(state: WorkflowState) -> NodeResult:
        log.append(name)
        artifacts = {artifact: "{n} output".format(n=name)} if artifact else {}
        message = AgentMessage(name, "workflow", "result", "{n} done".format(n=name))
        return NodeResult.ok(artifacts, [message])

    return FunctionNode(name, run)


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_workspace()
        self.trace = self.root / "trace.jsonl"

    def tearDown(self) -> None:
        drop(self.root)

    def engine(self, workflow: Workflow, **kwargs) -> Engine:
        return Engine(workflow, tracer=Tracer(self.trace, verbose=False), **kwargs)

    def test_steps_run_in_order(self) -> None:
        log = []
        flow = Workflow("t", [Step(recorder("a", log)), Step(recorder("b", log))])
        result = self.engine(flow).run("do it")
        self.assertEqual(log, ["a", "b"])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.executed, ["a", "b"])

    def test_artifacts_are_shared_through_state(self) -> None:
        flow = Workflow("t", [
            Step(recorder("a", [], artifact="alpha")),
            Step(recorder("b", [], artifact="beta")),
        ])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.state.get("alpha"), "a output")
        self.assertEqual(result.state.get("beta"), "b output")

    def test_when_predicate_skips_a_step(self) -> None:
        log = []
        flow = Workflow("t", [
            Step(recorder("a", log), when=lambda state: False),
            Step(recorder("b", log)),
        ])
        result = self.engine(flow).run("do it")
        self.assertEqual(log, ["b"])
        self.assertEqual(result.executed, ["b"])

    def test_failed_step_without_on_fail_aborts(self) -> None:
        def boom(state):
            return NodeResult.failed("kaput")

        flow = Workflow("t", [Step(FunctionNode("boom", boom)), Step(recorder("never", []))])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.status, "failed")
        self.assertIn("kaput", " ".join(result.state.errors))

    def test_on_fail_jumps_backwards(self) -> None:
        log = []
        state_box = {"fail_first": True}

        def maybe(state):
            if state_box["fail_first"]:
                state_box["fail_first"] = False
                return NodeResult.failed("retry me")
            return NodeResult.ok({"fixed": "yes"})

        flow = Workflow("t", [
            Step(recorder("work", log), max_visits=2),
            Step(FunctionNode("gate", maybe), on_fail="work", max_visits=2),
            Step(recorder("after", log)),
        ])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.status, "completed")
        self.assertEqual(log, ["work", "work", "after"])
        self.assertEqual(result.state.get("fixed"), "yes")

    def test_loop_guard_stops_an_endless_cycle(self) -> None:
        log = []

        def always_bad(state):
            return NodeResult.failed("still bad")

        flow = Workflow("t", [
            Step(recorder("work", log), max_visits=5),
            Step(FunctionNode("gate", always_bad), on_fail="work", max_visits=2),
        ])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("loop guard" in error for error in result.state.errors))
        self.assertLessEqual(len(log), 3)

    def test_node_exception_is_retried_then_reported(self) -> None:
        calls = {"n": 0}

        def flaky(state):
            calls["n"] += 1
            raise RuntimeError("provider down")

        flow = Workflow("t", [Step(FunctionNode("flaky", flaky), retries=3)])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.status, "failed")
        self.assertEqual(calls["n"], 3)
        self.assertIn("provider down", " ".join(result.state.errors))

    def test_parallel_step_merges_in_declaration_order(self) -> None:
        flow = Workflow("t", [
            ParallelStep([recorder("left", [], artifact="left"),
                          recorder("right", [], artifact="right")],
                         label="fanout"),
        ])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.status, "completed")
        self.assertEqual(sorted(result.state.artifacts), ["left", "right"])
        senders = sorted(m.sender for m in result.state.messages)
        self.assertEqual(senders, ["left", "right"])

    def test_parallel_failure_fails_the_step(self) -> None:
        def bad(state):
            return NodeResult.failed("no good")

        flow = Workflow("t", [ParallelStep([FunctionNode("bad", bad), recorder("good", [])],
                                           label="fanout")])
        result = self.engine(flow).run("do it")
        self.assertEqual(result.status, "failed")

    def test_global_step_budget(self) -> None:
        log = []
        flow = Workflow("t", [Step(recorder("s{i}".format(i=i), log)) for i in range(5)])
        result = self.engine(flow, max_steps=2).run("do it")
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("budget" in error for error in result.state.errors))

    def test_duplicate_labels_rejected(self) -> None:
        with self.assertRaises(FlowError):
            Workflow("t", [Step(recorder("a", [])), Step(recorder("a", []))])

    def test_unknown_jump_target_rejected(self) -> None:
        with self.assertRaises(FlowError):
            Workflow("t", [Step(recorder("a", []), on_fail="nowhere")])

    def test_trace_file_is_written(self) -> None:
        flow = Workflow("t", [Step(recorder("a", []))])
        self.engine(flow).run("do it")
        self.assertTrue(self.trace.exists())
        content = self.trace.read_text(encoding="utf-8")
        self.assertIn('"step_ok"', content)
        self.assertIn('"done"', content)

    def test_describe_and_mermaid_mention_every_step(self) -> None:
        flow = Workflow("demo", [Step(recorder("alpha", [])), Step(recorder("beta", []))])
        self.assertIn("alpha", flow.describe())
        self.assertIn("beta", flow.describe())
        diagram = flow.to_mermaid()
        self.assertIn("flowchart TD", diagram)
        self.assertIn("alpha", diagram)
        self.assertIn("stop", diagram)


if __name__ == "__main__":
    unittest.main()
