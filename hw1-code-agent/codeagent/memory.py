"""Conversation memory with a character budget and a rolling digest.

Context windows are finite, so the agent keeps the most recent turns verbatim and
folds everything older into a short digest that stays at the top of the prompt.
The budget is measured in characters rather than tokens: no tokenizer
dependency, and for review work a character budget tracks cost closely enough.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


DEFAULT_MAX_CHARS = 24000
DIGEST_LIMIT = 1200


@dataclass
class Turn:
    role: str
    content: str

    def as_message(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ConversationMemory:
    """Bounded message history shared by every call to the model."""

    max_chars: int = DEFAULT_MAX_CHARS
    turns: List[Turn] = field(default_factory=list)
    digest: str = ""

    # -- writes ------------------------------------------------------------ #
    def add(self, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant', got {r!r}".format(r=role))
        self.turns.append(Turn(role=role, content=content or ""))
        self._evict()

    def add_user(self, content: str) -> None:
        self.add("user", content)

    def add_assistant(self, content: str) -> None:
        self.add("assistant", content)

    def reset(self) -> None:
        self.turns.clear()
        self.digest = ""

    # -- reads ------------------------------------------------------------- #
    @property
    def size(self) -> int:
        return sum(len(turn.content) for turn in self.turns)

    def history(self) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if self.digest:
            messages.append({
                "role": "system",
                "content": "[EARLIER CONTEXT DIGEST]\n" + self.digest,
            })
        messages.extend(turn.as_message() for turn in self.turns)
        return messages

    def snapshot(self) -> str:
        return json.dumps(
            {"digest": self.digest, "turns": [t.__dict__ for t in self.turns]},
            ensure_ascii=False, indent=2)

    # -- internals --------------------------------------------------------- #
    def _evict(self) -> None:
        """Drop the oldest complete exchange while the budget is exceeded."""

        while self.size > self.max_chars and len(self.turns) >= 2:
            pair = self.turns[:2]
            # Never split a user/assistant exchange: an orphaned assistant turn
            # teaches the model nothing and can break strict providers.
            del self.turns[:2]
            self._absorb(pair)

    def _absorb(self, removed: List[Turn]) -> None:
        pieces = []
        for turn in removed:
            snippet = " ".join(turn.content.split())
            if len(snippet) > 240:
                snippet = snippet[:240] + "..."
            pieces.append("{role}: {text}".format(role=turn.role, text=snippet))
        joined = "\n".join(pieces)
        self.digest = (self.digest + "\n" + joined).strip()[-DIGEST_LIMIT:]
