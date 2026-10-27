"""The Mini SE workflow: 需求 -> 设计 -> 编码 -> 审查 -> 文档 -> 汇总.

The flow deliberately contains all four control patterns the assignment asks
for (and the two it recommends):

* **sequential**  requirement -> design -> coding;
* **conditional** the design gate may send the design agent back to work;
* **loop**        the review gate sends the coding agent back with feedback;
* **parallel**    review and documentation both consume the code, so they run
                  concurrently and their outputs are merged deterministically.

Both gates are *structural* rather than vibes-based, which is what makes the
offline demo repeatable: the design gate counts sections, the review gate looks
at the reviewer's verdict.
"""

from __future__ import annotations

from typing import Tuple

from .agents import (
    CodingNode,
    ReviewNode,
    build_design_node,
    build_docs_node,
    build_requirement_node,
    build_summary_node,
)
from .engine import ParallelStep, Step, Workflow
from .llm_bridge import BaseLLM
from .nodes import GateNode
from .state import WorkflowState

MIN_DESIGN_CHARS = 150
MIN_DESIGN_SECTIONS = 3


def design_gate(state: WorkflowState) -> Tuple[bool, str]:
    """Reject a design document that is empty, thin, or unstructured."""

    design = state.get("design")
    if not design:
        return False, "the design agent returned nothing"
    if len(design) < MIN_DESIGN_CHARS:
        return False, "design is too thin ({n} chars, need >= {m})".format(
            n=len(design), m=MIN_DESIGN_CHARS)
    sections = design.count("## ")
    if sections < MIN_DESIGN_SECTIONS:
        return False, "design needs at least {m} '## ' sections, found {n}".format(
            m=MIN_DESIGN_SECTIONS, n=sections)
    return True, ""


def review_gate(state: WorkflowState) -> Tuple[bool, str]:
    """Fail the gate while the reviewer still wants changes."""

    verdict = state.get("review_verdict", "")
    if not verdict:
        return False, "no review artifact to judge"
    if "request changes" in verdict.lower():
        return False, "reviewer requested changes; sending the code back for a fix"
    return True, verdict


def build_mini_se_flow(llm: BaseLLM, run_dir) -> Workflow:
    """Assemble the workflow. Call once per run (the coding node binds run_dir)."""

    steps = [
        Step(build_requirement_node(llm), max_visits=1),
        Step(build_design_node(llm), max_visits=3),
        Step(
            GateNode("design_gate", design_gate, feedback_to="design",
                     description="design must be structured and complete"),
            on_fail="design",
            max_visits=3,
        ),
        Step(CodingNode(llm, run_dir), max_visits=3),
        ParallelStep(
            [ReviewNode(llm, run_dir), build_docs_node(llm)],
            label="verify",
            max_visits=3,
        ),
        Step(
            GateNode("review_gate", review_gate, feedback_to="coding",
                     description="review must approve the code"),
            on_fail="coding",
            max_visits=3,
        ),
        Step(build_summary_node(llm), max_visits=1),
    ]
    return Workflow("mini-se", steps)
