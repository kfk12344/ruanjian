"""Shared workflow state.

One mutable :class:`WorkflowState` instance travels through every node. Nodes
read from it and return their outputs as a :class:`NodeResult`; the engine is
the only writer. That single-writer rule is what makes the parallel step safe
and the trace reproducible.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .messages import AgentMessage


class FlowError(RuntimeError):
    """Raised when the workflow cannot continue (missing artifact, bad config)."""


@dataclass
class WorkflowState:
    task: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    artifacts: Dict[str, str] = field(default_factory=dict)
    messages: List[AgentMessage] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    visits: Dict[str, int] = field(default_factory=dict)
    status: str = "running"
    started_at: float = field(default_factory=time.time)

    # -- artifacts --------------------------------------------------------- #
    def set(self, key: str, value: str) -> None:
        if not key:
            raise ValueError("artifact key must not be empty")
        self.artifacts[key] = value

    def get(self, key: str, default: str = "") -> str:
        return self.artifacts.get(key, default)

    def require(self, key: str) -> str:
        if key not in self.artifacts:
            raise FlowError(
                "artifact {k!r} is missing; it should have been produced by an "
                "earlier step".format(k=key)
            )
        return self.artifacts[key]

    # -- messages ---------------------------------------------------------- #
    def add_message(self, message: AgentMessage) -> None:
        self.messages.append(message)

    def messages_for(self, recipient: str) -> List[AgentMessage]:
        return [m for m in self.messages if m.recipient == recipient]

    def latest_message(self, recipient: str) -> Optional[AgentMessage]:
        found = self.messages_for(recipient)
        return found[-1] if found else None

    # -- bookkeeping ------------------------------------------------------- #
    def record_error(self, message: str) -> None:
        self.errors.append(message)

    def visit(self, label: str) -> int:
        self.visits[label] = self.visits.get(label, 0) + 1
        return self.visits[label]

    # -- export ------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "status": self.status,
            "artifacts": dict(self.artifacts),
            "visits": dict(self.visits),
            "errors": list(self.errors),
            "messages": [m.to_dict() for m in self.messages],
        }
