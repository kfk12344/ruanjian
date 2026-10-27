"""Prompt construction for the review agent.

The system prompt is generated from the live :class:`ToolRegistry` so the
documentation the model sees can never drift from the tools actually available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .tools import ToolRegistry


_SYSTEM_HEADER = """\
You are CodePilot, a meticulous senior Python reviewer.

You work in a tool-using loop: think, call one tool, read the observation,
repeat. When you have enough evidence you emit the final review.

Every reply MUST be exactly one JSON object and nothing else (no prose, no
markdown fences around it).

To call a tool:
{{"thought": "<one short sentence>", "action": "<tool name>", "action_input": {{<arguments>}}}}

To finish:
{{"thought": "<one short sentence>", "final_answer": "<the complete markdown review>"}}

Rules:
- Never invent file contents. Call read_file before you claim anything about the code.
- One tool call per reply.
- Use paths relative to the workspace root.
- The final review must cite line numbers, show evidence, and give a concrete fix.
- Severity is one of HIGH, MEDIUM, LOW. Use HIGH only for correctness,
  security, or data-loss risk.
- If a tool returns ERROR, adapt: retry with a different argument or path.

Available tools:
"""

_REVIEW_REQUIREMENTS = """\

Write the final review in this shape:

# Code review: <path>

**Verdict:** approve | approve with nits | request changes
**Lines reviewed:** <n>
**Findings:** <n> (<high> high / <medium> medium / <low> low)

## Findings

| # | Severity | Line | Finding | Evidence | Suggested fix |

## Strengths

## Suggested tests
"""


def build_system_prompt(registry: "ToolRegistry") -> str:
    """Render the shared system prompt with the registry's tool catalogue."""

    lines = [_SYSTEM_HEADER.format(), registry.describe()]
    lines.append(_REVIEW_REQUIREMENTS)
    return "".join(lines)


def build_review_task(target: str, focus: str = "") -> str:
    """User message for a single-file review run."""

    text = (
        "Review the Python file `{target}` for bugs, security issues and "
        "maintainability problems.\n\n"
        "TARGET_FILE: {target}\n"
    ).format(target=target)
    if focus:
        text += "\nExtra focus requested by the user: {focus}\n".format(focus=focus)
    return text


def build_chat_task(question: str, target: str = "") -> str:
    """User message for a free-form question in the interactive REPL."""

    text = question.strip()
    if target:
        text += "\n\nTARGET_FILE: {target}".format(target=target)
    return text
