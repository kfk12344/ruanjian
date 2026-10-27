"""Node abstractions.

A node is a unit of work with one job. Nodes are **read-only** with respect to
the shared state: they inspect it and return a :class:`NodeResult`; the engine
applies the result. This is what lets the parallel step run nodes concurrently
without locking and keeps the execution order of the trace deterministic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from .llm_bridge import BaseLLM
from .messages import AgentMessage
from .state import WorkflowState


class NodeStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeResult:
    status: NodeStatus = NodeStatus.OK
    artifacts: Dict[str, str] = field(default_factory=dict)
    messages: List[AgentMessage] = field(default_factory=list)
    reason: str = ""
    meta: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        artifacts: Optional[Dict[str, str]] = None,
        messages: Optional[List[AgentMessage]] = None,
        **meta: object
    ) -> "NodeResult":
        return cls(status=NodeStatus.OK, artifacts=artifacts or {},
                   messages=messages or [], meta=dict(meta))

    @classmethod
    def failed(
        cls,
        reason: str,
        messages: Optional[List[AgentMessage]] = None,
        **meta: object
    ) -> "NodeResult":
        return cls(status=NodeStatus.FAILED, reason=reason,
                   messages=messages or [], meta=dict(meta))


class Node(ABC):
    """Base class: a named, describable unit of work."""

    name: str = "node"

    @abstractmethod
    def run(self, state: WorkflowState) -> NodeResult:
        raise NotImplementedError

    def describe(self) -> str:
        return "{n}: {d}".format(n=self.name, d=(self.__doc__ or "").strip().splitlines()[0]
                                 if self.__doc__ else "")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<{c} {n}>".format(c=type(self).__name__, n=self.name)


class FunctionNode(Node):
    """Adapter for a plain ``state -> NodeResult`` callable (used in tests)."""

    def __init__(self, name: str, func: Callable[[WorkflowState], NodeResult]):
        self.name = name
        self._func = func

    def run(self, state: WorkflowState) -> NodeResult:
        return self._func(state)


class LLMNode(Node):
    """Produces one artifact by asking the model a templated question."""

    def __init__(
        self,
        name: str,
        artifact: str,
        marker: str,
        instructions: str,
        llm: BaseLLM,
        input_keys: Optional[List[str]] = None,
        max_input_chars: int = 3000,
    ):
        self.name = name
        self.artifact = artifact
        self.llm = llm
        self.instructions = instructions.strip()
        self.input_keys = list(input_keys or [])
        self.max_input_chars = max_input_chars
        # The marker lets the offline mock pick the right template.
        self.system_prompt = "[WORKFLOW-{m}] {instructions}".format(
            m=marker, instructions=self.instructions)

    def build_prompt(self, state: WorkflowState) -> str:
        parts = ["TASK: {t}".format(t=state.task)]
        for key in self.input_keys:
            value = state.get(key)
            if not value:
                continue
            if len(value) > self.max_input_chars:
                value = value[: self.max_input_chars] + "\n...[truncated]"
            parts.append("## {k}\n{v}".format(k=key, v=value))
        return "\n\n".join(parts)

    def run(self, state: WorkflowState) -> NodeResult:
        reply = self.llm.complete([
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.build_prompt(state)},
        ])
        reply = (reply or "").strip()
        if not reply:
            return NodeResult.failed("the model returned an empty {a}".format(a=self.artifact))

        preview = " ".join(reply.split())[:80]
        message = AgentMessage(
            sender=self.name,
            recipient="workflow",
            kind="result",
            content=preview,
            payload={"artifact": self.artifact, "chars": len(reply)},
        )
        return NodeResult.ok({self.artifact: reply}, [message], chars=len(reply))


class GateNode(Node):
    """Checks an artifact and either passes or sends feedback back upstream."""

    def __init__(
        self,
        name: str,
        predicate: Callable[[WorkflowState], "tuple[bool, str]"],
        feedback_to: str,
        description: str = "",
    ):
        self.name = name
        self.predicate = predicate
        self.feedback_to = feedback_to
        self._description = description

    def describe(self) -> str:
        return "{n}: {d}".format(n=self.name, d=self._description or "quality gate")

    def run(self, state: WorkflowState) -> NodeResult:
        passed, reason = self.predicate(state)
        if passed:
            return NodeResult.ok(messages=[
                AgentMessage(self.name, "workflow", "result", "gate passed")
            ])
        return NodeResult.failed(
            reason,
            messages=[AgentMessage(self.name, self.feedback_to, "feedback", reason)],
        )
