"""The agents that participate in the Mini SE workflow.

Three of them are thin configurations of :class:`LLMNode` (one prompt, one
artifact). Two are custom nodes:

* :class:`CodingNode` materialises the generated code on disk so that
  :class:`ReviewNode` can read it with the project-1 tools;
* :class:`ReviewNode` **is** the Homework 1 agent, wrapped as a workflow node.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .llm_bridge import HW1_AVAILABLE, BaseLLM, MockLLM, hw1_load_settings
from .messages import AgentMessage
from .nodes import LLMNode, Node, NodeResult, NodeStatus
from .state import FlowError, WorkflowState

_CODE_FENCE = re.compile(r"```(?:python)?\s*\n?(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Pull the fenced code block out of a model reply, if there is one."""

    match = _CODE_FENCE.search(text or "")
    body = match.group(1) if match else (text or "")
    return body.strip("\n") + "\n"


class CodingNode(LLMNode):
    """Writes an implementation file so the reviewer can inspect it."""

    def __init__(self, llm: BaseLLM, run_dir: Path):
        super().__init__(
            name="coding",
            artifact="code",
            marker="CODING",
            llm=llm,
            input_keys=["requirement", "design"],
            instructions=(
                "You are the coding agent. Read the requirements and the design, "
                "then produce ONE fenced ```python block containing a complete, "
                "runnable module: type hints, docstrings, explicit validation, "
                "no bare except, no print() in library code."
            ),
        )
        self.run_dir = Path(run_dir)

    def build_prompt(self, state: WorkflowState) -> str:
        prompt = super().build_prompt(state)
        feedback = state.latest_message("coding")
        if feedback is not None and feedback.kind == "feedback":
            # Reviewer feedback is what makes the second pass different.
            prompt += "\n\n## code_feedback\n" + feedback.content
        return prompt

    def run(self, state: WorkflowState) -> NodeResult:
        result = super().run(state)
        if result.status is NodeStatus.FAILED:
            return result

        code = extract_code(result.artifacts.get("code", ""))
        if not code.strip():
            return NodeResult.failed("the coding agent produced no code block")

        path = self.run_dir / "artifacts" / "code.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")

        result.artifacts["code"] = code
        result.artifacts["code_path"] = "artifacts/code.py"
        result.artifacts["code_file"] = str(path)
        return result


class ReviewNode(Node):
    """Runs the Homework 1 CodeAgent over the generated file."""

    name = "review"

    def __init__(self, llm: BaseLLM, run_dir: Path, max_steps: int = 6):
        self.llm = llm
        self.run_dir = Path(run_dir)
        self.max_steps = max_steps

    def describe(self) -> str:
        source = "homework 1 CodeAgent" if HW1_AVAILABLE else "built-in fallback scanner"
        return "review: static review via {s}".format(s=source)

    def run(self, state: WorkflowState) -> NodeResult:
        target = state.get("code_path")
        if not target:
            return NodeResult.failed("no code artifact to review")

        if HW1_AVAILABLE:
            review, verdict, steps, stopped = self._run_project1(target)
        else:
            review, verdict, steps, stopped = self._fallback_review(target)

        message = AgentMessage(
            sender=self.name,
            recipient="review_gate",
            kind="result",
            content=verdict,
            payload={"verdict": verdict, "tool_calls": steps},
        )
        return NodeResult.ok(
            {"review": review, "review_verdict": verdict},
            [message],
            tool_calls=steps,
            stopped_reason=stopped,
        )

    # -- homework 1 integration -------------------------------------------- #
    def _run_project1(self, target: str):
        from codeagent.agent import CodeAgent  # imported lazily: keeps the bridge optional

        provider = "mock" if isinstance(self.llm, MockLLM) else "openai"
        settings = hw1_load_settings(
            provider=provider,
            workspace=self.run_dir,
            max_steps=self.max_steps,
            max_retries=2,
            allow_exec=False,
        )
        agent = CodeAgent(llm=self.llm, settings=settings)
        result = agent.review(target)
        text = result.final_answer
        verdict = "request changes" if "request changes" in text.lower() else "approve with nits"
        return text, verdict, result.tool_calls, result.stopped_reason

    # -- degraded mode ------------------------------------------------------ #
    def _fallback_review(self, target: str):
        path = self.run_dir / target
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FlowError("cannot read {p}: {e}".format(p=path, e=exc)) from exc

        problems: List[str] = []
        if re.search(r"except\s*:", source):
            problems.append("HIGH: bare `except:` swallows every exception")
        if re.search(r"\bprint\s*\(", source):
            problems.append("LOW: `print()` used instead of `logging`")
        if "-> " not in source:
            problems.append("LOW: missing return type hints")

        verdict = "request changes" if any(p.startswith("HIGH") for p in problems) else "approve with nits"
        lines = ["# Code review: {t}".format(t=target), "",
                 "**Verdict:** {v}".format(v=verdict), ""]
        lines += ["- {p}".format(p=p) for p in problems] or ["No issues detected."]
        lines += ["", "_(fallback scanner: hw1-code-agent/ was not importable)_"]
        return "\n".join(lines), verdict, 0, "fallback"


def build_requirement_node(llm: BaseLLM) -> LLMNode:
    return LLMNode(
        name="requirement",
        artifact="requirement",
        marker="REQUIREMENT",
        llm=llm,
        instructions=(
            "You are the requirements agent. Turn the user task into a short "
            "requirements document with: Goal, Functional requirements (FR-n), "
            "Non-functional requirements (NFR-n), Acceptance criteria (AC-n). "
            "Use Markdown headings."
        ),
    )


def build_design_node(llm: BaseLLM) -> LLMNode:
    return LLMNode(
        name="design",
        artifact="design",
        marker="DESIGN",
        llm=llm,
        input_keys=["requirement"],
        instructions=(
            "You are the design agent. From the requirements, write a design "
            "document with at least these Markdown sections: Overview, Modules, "
            "Data flow, Error strategy, Test plan. Keep it implementation-ready."
        ),
    )


def build_docs_node(llm: BaseLLM) -> LLMNode:
    return LLMNode(
        name="documentation",
        artifact="docs",
        marker="DOCS",
        llm=llm,
        input_keys=["requirement", "code"],
        instructions=(
            "You are the documentation agent. Write a README-style usage guide "
            "for the generated code: quick start, API table, error handling."
        ),
    )


def build_summary_node(llm: BaseLLM) -> LLMNode:
    return LLMNode(
        name="summary",
        artifact="summary",
        marker="SUMMARY",
        llm=llm,
        input_keys=["requirement", "design", "code", "review", "docs"],
        max_input_chars=1500,
        instructions=(
            "You are the reporting agent. Summarise the run: what was produced, "
            "what the reviewer said, and the top open risks. Keep it under 20 lines."
        ),
    )
