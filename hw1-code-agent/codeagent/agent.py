"""The agent loop: reason -> act -> observe -> repeat, until a final answer.

The loop is deliberately small and explicit. The model proposes one JSON object
per turn; the loop validates it, executes at most one tool, feeds the
observation back, and stops when the model emits ``final_answer``. Everything
that can go wrong (bad JSON, unknown tool, tool exception, provider outage) is
handled here instead of leaking into the caller.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .config import Settings, load_settings
from .llm import BaseLLM, LLMError, create_llm, retry_with_backoff
from .memory import ConversationMemory
from .prompts import build_chat_task, build_review_task, build_system_prompt
from .tools import ToolContext, ToolRegistry, build_default_registry


MAX_PARSE_CORRECTIONS = 3

_CORRECTION = (
    "Your last reply was not a single valid JSON object. Reply again with "
    "exactly one JSON object: either "
    '{"thought": "...", "action": "<tool>", "action_input": {...}} or '
    '{"thought": "...", "final_answer": "<markdown>"}. No prose, no code fences.'
)


@dataclass
class AgentStep:
    """One turn of the loop, kept for the transcript and for debugging."""

    index: int
    thought: str = ""
    action: Optional[str] = None
    action_input: Dict = field(default_factory=dict)
    observation: Optional[str] = None
    final_answer: Optional[str] = None

    @property
    def kind(self) -> str:
        return "final" if self.final_answer is not None else "tool"

    def render(self) -> str:
        if self.final_answer is not None:
            return "[{i}] thought: {t}\n    -> final answer ({n} chars)".format(
                i=self.index, t=self.thought or "-", n=len(self.final_answer))
        return "[{i}] thought: {t}\n    -> {a}({args})\n    <- {obs}".format(
            i=self.index,
            t=self.thought or "-",
            a=self.action,
            args=json.dumps(self.action_input, ensure_ascii=False)[:160],
            obs=(self.observation or "").replace("\n", "\n       ")[:600],
        )


@dataclass
class AgentResult:
    task: str
    final_answer: str
    steps: List[AgentStep]
    stopped_reason: str
    model: str
    elapsed: float = 0.0

    @property
    def tool_calls(self) -> int:
        return sum(1 for step in self.steps if step.action)

    def transcript(self) -> str:
        return "\n".join(step.render() for step in self.steps)


def extract_json_object(text: str) -> Optional[dict]:
    """Pull the first balanced JSON object out of a model reply.

    Models wrap JSON in code fences, add a sentence before it, or emit trailing
    commentary. Rather than trusting ``json.loads`` on the whole string we scan
    for the first ``{`` and walk to its matching brace, ignoring braces that
    appear inside strings.
    """

    if not text:
        return None
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    start = cleaned.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for position in range(start, len(cleaned)):
            char = cleaned[position]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:position + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return parsed if isinstance(parsed, dict) else None
        start = cleaned.find("{", start + 1)
    return None


class CodeAgent:
    """A small tool-using agent specialised for Python code review."""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        registry: Optional[ToolRegistry] = None,
        settings: Optional[Settings] = None,
        memory: Optional[ConversationMemory] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ):
        self.settings = settings or load_settings()
        self.llm = llm or create_llm(self.settings)
        self.registry = registry or build_default_registry()
        self.memory = memory or ConversationMemory()
        self.on_event = on_event or (lambda kind, payload: None)
        self.context = ToolContext(
            workspace=self.settings.workspace,
            allow_exec=self.settings.allow_exec,
            timeout=min(self.settings.request_timeout, 30.0),
        )

    # -- public API -------------------------------------------------------- #
    def review(self, target: str, focus: str = "") -> AgentResult:
        return self.run(build_review_task(target, focus))

    def ask(self, question: str, target: str = "") -> AgentResult:
        return self.run(build_chat_task(question, target))

    def run(self, task: str, max_steps: Optional[int] = None) -> AgentResult:
        """Drive one full task through the loop."""

        started = time.perf_counter()
        max_steps = max_steps or self.settings.max_steps
        messages: List[Dict] = [{"role": "system", "content": build_system_prompt(self.registry)}]
        messages.extend(self.memory.history())
        messages.append({"role": "user", "content": task})

        steps: List[AgentStep] = []
        parse_errors = 0
        stopped_reason = "max_steps_reached"

        for index in range(max_steps):
            try:
                raw = self._complete(messages)
            except LLMError as exc:
                self.on_event("llm_error", {"error": str(exc)})
                if steps:
                    stopped_reason = "llm_failed_mid_run"
                    break
                raise

            payload = extract_json_object(raw)
            if payload is None:
                parse_errors += 1
                self.on_event("parse_error", {"raw": raw[:400]})
                if parse_errors >= MAX_PARSE_CORRECTIONS:
                    stopped_reason = "model_output_not_json"
                    steps.append(AgentStep(index=index, final_answer=raw, thought="(unparsed reply)"))
                    break
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": _CORRECTION})
                continue
            parse_errors = 0

            thought = str(payload.get("thought") or "")
            final = payload.get("final_answer")
            if isinstance(final, str) and final.strip():
                step = AgentStep(index=index, thought=thought, final_answer=final.strip())
                steps.append(step)
                self.on_event("final", {"step": step})
                stopped_reason = "final_answer"
                break

            action = payload.get("action")
            arguments = payload.get("action_input")
            if not isinstance(action, str) or not action.strip():
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": _CORRECTION})
                continue
            if not isinstance(arguments, dict):
                arguments = {}

            step = AgentStep(index=index, thought=thought, action=action, action_input=arguments)
            self.on_event("action", {"step": step})

            observation = self.registry.run(action, arguments, self.context)
            step.observation = observation
            steps.append(step)
            self.on_event("observation", {"step": step})

            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "OBSERVATION[{a}] {obs}".format(a=action, obs=observation),
            })

        answer = self._best_answer(steps, stopped_reason)
        self.memory.add_user(task)
        self.memory.add_assistant(answer)

        result = AgentResult(
            task=task,
            final_answer=answer,
            steps=steps,
            stopped_reason=stopped_reason,
            model=getattr(self.llm, "name", "unknown"),
            elapsed=time.perf_counter() - started,
        )
        self.on_event("done", {"result": result})
        return result

    # -- internals --------------------------------------------------------- #
    def _complete(self, messages: List[Dict]) -> str:
        return retry_with_backoff(
            lambda: self.llm.complete(messages),
            attempts=self.settings.max_retries,
            backoff=self.settings.retry_backoff,
        )

    @staticmethod
    def _best_answer(steps: List[AgentStep], reason: str) -> str:
        for step in reversed(steps):
            if step.final_answer:
                return step.final_answer
        evidence = [s.observation for s in steps if s.observation]
        return (
            "The agent stopped before producing a final review ({reason}).\n\n"
            "Evidence collected:\n\n{evidence}"
        ).format(reason=reason, evidence="\n\n".join(e[:2000] for e in evidence) or "(none)")
