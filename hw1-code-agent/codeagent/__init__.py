"""CodePilot: a small, tool-using code review agent."""

from __future__ import annotations

from .agent import AgentResult, AgentStep, CodeAgent, extract_json_object
from .config import Settings, load_settings
from .llm import BaseLLM, LLMError, MockLLM, OpenAICompatibleLLM, ScriptedLLM, create_llm
from .memory import ConversationMemory
from .tools import Tool, ToolContext, ToolError, ToolRegistry, build_default_registry

__version__ = "1.0.0"

__all__ = [
    "AgentResult",
    "AgentStep",
    "BaseLLM",
    "CodeAgent",
    "ConversationMemory",
    "LLMError",
    "MockLLM",
    "OpenAICompatibleLLM",
    "ScriptedLLM",
    "Settings",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "__version__",
    "build_default_registry",
    "create_llm",
    "extract_json_object",
    "load_settings",
]
