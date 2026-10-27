"""Command-line interface for CodePilot.

    python main.py review examples/buggy_calculator.py
    python main.py chat --target examples/buggy_utils.py
    python main.py tools
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .agent import CodeAgent, AgentResult
from .config import Settings, load_settings
from .llm import LLMError, create_llm
from .memory import ConversationMemory
from .tools import build_default_registry


def _print_transcript(result: AgentResult) -> None:
    print("\n--- agent trace ---", file=sys.stderr)
    print(result.transcript(), file=sys.stderr)
    print("--- end trace ({n} steps, {t:.2f}s) ---\n".format(
        n=len(result.steps), t=result.elapsed), file=sys.stderr)


def _save(result: AgentResult, directory: Path, target: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(target).stem or "review"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = directory / "{stem}-{stamp}.md".format(stem=stem, stamp=stamp)
    path.write_text(result.final_answer + "\n", encoding="utf-8")
    return path


def _build_agent(settings: Settings, verbose: bool) -> CodeAgent:
    llm = create_llm(settings)
    registry = build_default_registry()
    on_event = None
    if verbose:
        def on_event(kind: str, payload: dict) -> None:
            if kind == "action":
                step = payload["step"]
                print("  [step {i}] {a}({args})".format(
                    i=step.index, a=step.action,
                    args=json.dumps(step.action_input, ensure_ascii=False)[:120]),
                    file=sys.stderr)
            elif kind == "parse_error":
                print("  [warn] model reply was not JSON, asking again", file=sys.stderr)
    return CodeAgent(llm=llm, registry=registry, settings=settings, on_event=on_event)


def cmd_review(args: argparse.Namespace, settings: Settings) -> int:
    target = Path(args.target)
    if not target.exists():
        print("error: {p} does not exist".format(p=target), file=sys.stderr)
        return 2

    workspace = settings.workspace
    try:
        relative = target.resolve().relative_to(workspace)
    except ValueError:
        print("error: {p} is outside the agent workspace {w}".format(
            p=target, w=workspace), file=sys.stderr)
        return 2

    agent = _build_agent(settings, args.verbose)
    result = agent.review(str(relative).replace("\\", "/"), focus=args.focus or "")

    if args.json:
        print(json.dumps({
            "target": str(relative),
            "model": result.model,
            "stopped_reason": result.stopped_reason,
            "steps": [
                {"index": s.index, "thought": s.thought, "action": s.action,
                 "action_input": s.action_input, "observation": s.observation}
                for s in result.steps if s.action
            ],
            "final_answer": result.final_answer,
        }, ensure_ascii=False, indent=2))
    else:
        print(result.final_answer)

    if args.verbose:
        _print_transcript(result)

    if args.save:
        path = _save(result, Path(args.save), str(relative))
        print("\nsaved: {p}".format(p=path), file=sys.stderr)
    return 0


def cmd_chat(args: argparse.Namespace, settings: Settings) -> int:
    agent = _build_agent(settings, verbose=False)
    agent.memory = ConversationMemory()
    print("CodePilot chat ({m}). Type 'exit' to quit, '/reset' to clear memory.".format(
        m=settings.provider + ":" + settings.model))
    target = args.target or ""
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            return 0
        if line == "/reset":
            agent.memory.reset()
            print("memory cleared")
            continue
        if line == "/memory":
            print(agent.memory.snapshot())
            continue
        try:
            result = agent.ask(line, target=target)
        except LLMError as exc:
            print("error: {e}".format(e=exc), file=sys.stderr)
            continue
        print(textwrap.dedent(result.final_answer))


def cmd_tools(args: argparse.Namespace, settings: Settings) -> int:
    registry = build_default_registry()
    print("workspace: {w}".format(w=settings.workspace))
    print("provider : {p}".format(p=settings.provider))
    print("tools    :")
    for name in registry.names:
        tool = registry.get(name)
        print("  - {sig}\n      {desc}".format(sig=tool.signature(), desc=tool.description))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codepilot",
        description="A small tool-using agent that reviews Python code.",
    )
    parser.add_argument("--version", action="version", version="codepilot " + __version__)
    parser.add_argument("--workspace", default=None,
                        help="sandbox root for tools (default: current directory)")
    parser.add_argument("--provider", default=None, choices=["mock", "openai"],
                        help="force a provider instead of auto-detection")
    parser.add_argument("--model", default=None, help="model name for the openai provider")

    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="review one Python file")
    review.add_argument("target", help="path to the file, relative to the workspace")
    review.add_argument("--focus", default="", help="extra instruction for the reviewer")
    review.add_argument("--save", default=None, metavar="DIR",
                        help="write the review to DIR/<name>-<timestamp>.md")
    review.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    review.add_argument("--verbose", "-v", action="store_true", help="print the agent trace")
    review.set_defaults(func=cmd_review)

    chat = sub.add_parser("chat", help="interactive REPL with conversation memory")
    chat.add_argument("--target", default="", help="file to keep in context")
    chat.set_defaults(func=cmd_chat)

    tools = sub.add_parser("tools", help="list the available tools")
    tools.set_defaults(func=cmd_tools)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    overrides = {}
    if args.workspace:
        overrides["workspace"] = Path(args.workspace)
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model
    settings = load_settings(**overrides)

    if args.command == "review" and not settings.workspace.exists():
        print("error: workspace {w} does not exist".format(w=settings.workspace), file=sys.stderr)
        return 2

    try:
        return args.func(args, settings)
    except LLMError as exc:
        print("llm error: {e}".format(e=exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("interrupted", file=sys.stderr)
        return 130
