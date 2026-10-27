"""Bridge to Homework 1.

Homework 2 is required to reuse the project-1 agent. Rather than copying
`codeagent/` into this project (which would rot immediately), the workflow
imports it from the sibling directory and re-exports the small surface it needs.

If `hw1-code-agent/` is not present the module still imports: it falls back to a
tiny built-in stand-in so the workflow can be demonstrated on its own. The
console prints a warning in that case, because the review step is then weaker.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HW1_ROOT = REPO_ROOT / "hw1-code-agent"


def _ensure_hw1_on_path() -> bool:
    if not (HW1_ROOT / "codeagent" / "__init__.py").is_file():
        return False
    path = str(HW1_ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)
    return True


HW1_AVAILABLE = _ensure_hw1_on_path()


# --------------------------------------------------------------------------- #
# Preferred path: borrow the real implementation from Homework 1
# --------------------------------------------------------------------------- #
if HW1_AVAILABLE:  # pragma: no cover - exercised in the normal checkout
    from codeagent.config import load_settings as hw1_load_settings
    from codeagent.llm import (
        BaseLLM,
        LLMError,
        MockLLM,
        ScriptedLLM,
        create_llm,
        retry_with_backoff,
    )
    from codeagent.memory import ConversationMemory

    SETTINGS_FACTORY = hw1_load_settings

# --------------------------------------------------------------------------- #
# Fallback path: keep the workflow runnable without the sibling project
# --------------------------------------------------------------------------- #
else:  # pragma: no cover - only when hw1 is missing
    import time
    from abc import ABC, abstractmethod

    class LLMError(RuntimeError):
        pass

    class BaseLLM(ABC):
        @abstractmethod
        def complete(self, messages, temperature=None, max_tokens=None) -> str:
            raise NotImplementedError

    class ScriptedLLM(BaseLLM):
        def __init__(self, replies):
            self._replies = list(replies)

        def complete(self, messages, temperature=None, max_tokens=None) -> str:
            if not self._replies:
                raise LLMError("scripted model exhausted")
            return self._replies.pop(0)

    class MockLLM(BaseLLM):
        """Minimal template engine; replaced by Homework 1's version when present."""

        def complete(self, messages, temperature=None, max_tokens=None) -> str:
            system = messages[0].get("content", "") if messages else ""
            user = messages[-1].get("content", "") if messages else ""
            task = user.split("TASK:", 1)[-1].strip()[:400]
            if "[WORKFLOW-CODING]" in system:
                return (
                    "```python\n"
                    "def transform(text):\n"
                    "    if not isinstance(text, str):\n"
                    "        raise ValueError('text must be a str')\n"
                    "    return text.split()\n"
                    "```\n"
                )
            heading = {
                "REQUIREMENT": "# Requirements",
                "DESIGN": "# Design",
                "DOCS": "# Usage",
                "SUMMARY": "# Summary",
                "FIX": "# Fix plan",
            }
            for marker, title in heading.items():
                if "[WORKFLOW-{m}]".format(m=marker) in system:
                    return "{t}: {task}\n\n- item one\n- item two\n- item three\n".format(
                        t=title, task=task)
            return "# Result\n\n{task}\n".format(task=task)

    def create_llm(settings, replies=None):
        return ScriptedLLM(replies) if replies is not None else MockLLM()

    def retry_with_backoff(func, attempts=3, backoff=1.5, sleep=time.sleep):
        last = None
        for attempt in range(1, attempts + 1):
            try:
                return func()
            except LLMError as exc:
                last = exc
                if attempt < attempts:
                    sleep(backoff ** attempt)
        raise LLMError("giving up after {n} attempts: {last}".format(n=attempts, last=last))

    class ConversationMemory:  # not used by the workflow, kept for API parity
        def __init__(self, max_chars=24000):
            self.max_chars = max_chars
            self.turns = []

    def hw1_load_settings(**overrides):
        raise LLMError(
            "hw1-code-agent/ was not found next to hw2-workflow/; "
            "the real CodeAgent settings are unavailable"
        )
