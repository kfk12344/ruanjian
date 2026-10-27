"""The workflow engine.

The engine is a deliberately small interpreter:

* steps run in order;
* a step may be skipped by a predicate (``when``);
* a failed step either aborts the run or jumps to an earlier step (``on_fail``),
  which is how retry loops are expressed;
* ``max_visits`` is the loop guard, so a bad flow cannot spin forever;
* a ``ParallelStep`` runs independent nodes concurrently and merges their output
  in declaration order, keeping the trace deterministic.

There is no graph database, no DSL and no scheduler. A list of steps plus two
control-flow attributes covers every flow this course needs, and it is small
enough to read in one sitting — which matters more for a two-week MVP than a
generic DAG engine.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Union

from .messages import AgentMessage
from .nodes import Node, NodeResult, NodeStatus
from .state import FlowError, WorkflowState
from .tracing import Tracer


@dataclass
class Step:
    node: Node
    label: Optional[str] = None
    when: Optional[Callable[[WorkflowState], bool]] = None
    on_fail: Optional[str] = None
    max_visits: int = 1
    retries: int = 1

    def __post_init__(self) -> None:
        self.label = self.label or self.node.name
        if self.max_visits < 1:
            raise ValueError("max_visits must be >= 1")
        if self.retries < 1:
            raise ValueError("retries must be >= 1")


@dataclass
class ParallelStep:
    nodes: Sequence[Node]
    label: str
    when: Optional[Callable[[WorkflowState], bool]] = None
    on_fail: Optional[str] = None
    max_visits: int = 1
    retries: int = 1

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("a parallel step needs at least one node")


StepLike = Union[Step, ParallelStep]


class Workflow:
    """An ordered list of steps with a name."""

    def __init__(self, name: str, steps: Sequence[StepLike]):
        self.name = name
        self.steps: List[StepLike] = list(steps)
        self.validate()

    def labels(self) -> List[str]:
        return [step.label for step in self.steps]

    def index_of(self, label: str) -> int:
        try:
            return self.labels().index(label)
        except ValueError:
            raise FlowError("no step named {l!r}; known: {known}".format(
                l=label, known=", ".join(self.labels()))) from None

    def validate(self) -> None:
        labels = self.labels()
        duplicates = {label for label in labels if labels.count(label) > 1}
        if duplicates:
            raise FlowError("duplicate step labels: {d}".format(d=sorted(duplicates)))
        for step in self.steps:
            if step.on_fail and step.on_fail not in labels:
                raise FlowError(
                    "step {l!r} jumps to unknown step {t!r}".format(l=step.label, t=step.on_fail))

    def describe(self) -> str:
        lines = ["workflow: {n}".format(n=self.name)]
        for index, step in enumerate(self.steps, 1):
            if isinstance(step, ParallelStep):
                inner = " + ".join(node.name for node in step.nodes)
                kind = "parallel"
            else:
                inner = step.node.name
                kind = "node"
            line = "  {i:>2}. {l:<18} [{k}] visits<={v}".format(
                i=index, l=step.label, k=kind, v=step.max_visits)
            if step.on_fail:
                line += "  on_fail->{t}".format(t=step.on_fail)
            if step.when:
                line += "  (conditional)"
            lines.append(line)
            if inner != step.label:
                lines.append("      {inner}".format(inner=inner))
        return "\n".join(lines)

    def to_mermaid(self) -> str:
        """Render the flow as a Mermaid flowchart (used by --graph)."""

        lines = ["flowchart TD", "    start([start])"]
        previous = "start"
        for index, step in enumerate(self.steps, 1):
            node_id = "s{i}".format(i=index)
            if isinstance(step, ParallelStep):
                lines.append('    {n}["{l}<br/>(parallel)"]'.format(n=node_id, l=step.label))
            else:
                lines.append('    {n}["{l}"]'.format(n=node_id, l=step.label))
            lines.append("    {p} --> {n}".format(p=previous, n=node_id))
            previous = node_id
        lines.append("    {p} --> stop([stop])".format(p=previous))
        for index, step in enumerate(self.steps, 1):
            if step.on_fail:
                target = self.index_of(step.on_fail) + 1
                lines.append("    s{i} -.->|\"on_fail\"| s{t}".format(i=index, t=target))
        return "\n".join(lines)


@dataclass
class RunResult:
    state: WorkflowState
    status: str
    executed: List[str] = field(default_factory=list)
    elapsed: float = 0.0
    trace_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def summary(self) -> str:
        lines = [
            "run {id}: {status} in {elapsed:.2f}s".format(
                id=self.state.run_id, status=self.status, elapsed=self.elapsed),
            "steps: {s}".format(s=" -> ".join(self.executed) or "(none)"),
            "artifacts: {a}".format(a=", ".join(sorted(self.state.artifacts)) or "(none)"),
        ]
        if self.state.errors:
            lines.append("issues: {e}".format(e="; ".join(self.state.errors)))
        return "\n".join(lines)


class Engine:
    """Executes a :class:`Workflow` against a :class:`WorkflowState`."""

    def __init__(
        self,
        workflow: Workflow,
        tracer: Optional[Tracer] = None,
        max_steps: int = 60,
        node_retries: int = 2,
        retry_backoff: float = 0.0,
    ):
        self.workflow = workflow
        self.tracer = tracer or Tracer(verbose=True)
        self.max_steps = max_steps
        self.node_retries = node_retries
        self.retry_backoff = retry_backoff
        self._executed: List[str] = []

    # -- public API -------------------------------------------------------- #
    def run(self, task: str, state: Optional[WorkflowState] = None) -> RunResult:
        state = state or WorkflowState(task=task)
        started = time.perf_counter()
        self._executed = []
        index = 0
        status = "failed"

        self.tracer.log("run_start", workflow=self.workflow.name, run_id=state.run_id,
                        task=task[:120])

        while index < len(self.workflow.steps):
            if len(self._executed) > self.max_steps:
                state.record_error("global step budget of {n} exhausted".format(n=self.max_steps))
                status = "failed"
                break

            step = self.workflow.steps[index]

            if step.when is not None and not step.when(state):
                self.tracer.log("step_skipped", label=step.label)
                index += 1
                continue

            visit = state.visit(step.label)
            if visit > step.max_visits:
                reason = (
                    "loop guard: step '{l}' would run a {v}th time "
                    "(max_visits={m})".format(l=step.label, v=visit, m=step.max_visits)
                )
                state.record_error(reason)
                self.tracer.log("step_failed", label=step.label, reason=reason)
                status = "failed"
                break

            self.tracer.log("step_start", label=step.label, visit=visit, node=type(
                step).__name__)
            began = time.perf_counter()
            result = self._execute(step, state)
            elapsed_ms = int((time.perf_counter() - began) * 1000)

            self._apply(step, result, state)

            if result.status is NodeStatus.FAILED:
                state.record_error("{l}: {r}".format(l=step.label, r=result.reason))
                self.tracer.log("step_failed", label=step.label, reason=result.reason, ms=elapsed_ms)
                if step.on_fail:
                    target = self.workflow.index_of(step.on_fail)
                    self.tracer.log("jump", frm=step.label, to=step.on_fail,
                                    reason=result.reason[:80])
                    index = target
                    continue
                status = "failed"
                break

            chars = sum(len(value) for value in result.artifacts.values())
            self.tracer.log("step_ok", label=step.label, ms=elapsed_ms, chars=chars)
            self._executed.append(step.label)
            index += 1
        else:
            status = "completed"

        state.status = status
        elapsed = time.perf_counter() - started
        self.tracer.log("done", status=status, seconds=round(elapsed, 3))
        return RunResult(
            state=state,
            status=status,
            executed=list(self._executed),
            elapsed=elapsed,
            trace_path=str(self.tracer.path) if self.tracer.path else None,
        )

    # -- internals --------------------------------------------------------- #
    def _execute(self, step: StepLike, state: WorkflowState) -> NodeResult:
        attempts = max(step.retries, self.node_retries)
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                if isinstance(step, ParallelStep):
                    return self._run_parallel(step, state)
                return step.node.run(state)
            except Exception as exc:  # noqa: BLE001 - a node must never kill the run
                last_error = "{e!r}".format(e=exc)
                self.tracer.log("retry", label=step.label, attempt=attempt,
                                total=attempts, reason=str(exc)[:120])
                if attempt < attempts and self.retry_backoff:
                    time.sleep(self.retry_backoff * attempt)
        return NodeResult.failed("node raised: {e}".format(e=last_error))

    def _run_parallel(self, step: ParallelStep, state: WorkflowState) -> NodeResult:
        def call(node: Node) -> NodeResult:
            try:
                return node.run(state)
            except Exception as exc:  # noqa: BLE001
                return NodeResult.failed("node {n} raised: {e!r}".format(n=node.name, e=exc))

        with ThreadPoolExecutor(max_workers=len(step.nodes)) as pool:
            results = list(pool.map(call, step.nodes))

        merged = NodeResult.ok()
        failures = []
        for node, result in zip(step.nodes, results):
            merged.artifacts.update(result.artifacts)
            merged.messages.extend(result.messages)
            merged.meta["parallel:" + node.name] = {
                "status": result.status.value,
                "chars": sum(len(v) for v in result.artifacts.values()),
            }
            if result.status is NodeStatus.FAILED:
                failures.append("{n}: {r}".format(n=node.name, r=result.reason))
        if failures:
            return NodeResult.failed("; ".join(failures), messages=merged.messages)
        return merged

    def _apply(self, step: StepLike, result: NodeResult, state: WorkflowState) -> None:
        state.artifacts.update(result.artifacts)
        for message in result.messages:
            state.add_message(message)
            self.tracer.log(
                "message",
                sender=message.sender,
                recipient=message.recipient,
                kind=message.kind,
                preview=" ".join(message.content.split())[:70],
            )
