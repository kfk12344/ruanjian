"""Agent-to-agent messages.

Agents in this workflow never call each other directly. They emit
:class:`AgentMessage` objects into the shared state and read the messages
addressed to them. That keeps every hop inspectable (the trace prints all of
them) and makes the flow testable without a network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict

KINDS = {"handoff", "result", "feedback", "error", "system"}


@dataclass(frozen=True)
class AgentMessage:
    sender: str
    recipient: str
    kind: str
    content: str
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(
                "unknown message kind {k!r}; expected one of {allowed}".format(
                    k=self.kind, allowed=sorted(KINDS))
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "kind": self.kind,
            "content": self.content,
            "payload": self.payload,
            "ts": self.ts,
        }

    def render(self, width: int = 70) -> str:
        body = " ".join(self.content.split())
        if len(body) > width:
            body = body[:width] + "..."
        return "{s} -> {r} [{k}] {body}".format(
            s=self.sender, r=self.recipient, k=self.kind, body=body)
