"""Mini SE Workflow MVP: a 3-agent pipeline with gates, loops and tracing."""

from __future__ import annotations

from .engine import Engine, ParallelStep, RunResult, Step, Workflow
from .flows import build_mini_se_flow, design_gate, review_gate
from .llm_bridge import HW1_AVAILABLE, BaseLLM, MockLLM, ScriptedLLM, create_llm
from .messages import AgentMessage
from .nodes import Node, NodeResult, NodeStatus
from .state import FlowError, WorkflowState
from .tracing import Tracer

__version__ = "1.0.0"

__all__ = [
    "AgentMessage",
    "BaseLLM",
    "Engine",
    "FlowError",
    "HW1_AVAILABLE",
    "MockLLM",
    "Node",
    "NodeResult",
    "NodeStatus",
    "ParallelStep",
    "RunResult",
    "ScriptedLLM",
    "Step",
    "Tracer",
    "Workflow",
    "WorkflowState",
    "__version__",
    "build_mini_se_flow",
    "create_llm",
    "design_gate",
    "review_gate",
]
