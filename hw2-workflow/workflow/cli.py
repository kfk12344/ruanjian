"""Command line for the Mini SE workflow.

    python main.py demo
    python main.py run "build a word counter"
    python main.py graph
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .engine import Engine, RunResult
from .flows import build_mini_se_flow
from .llm_bridge import HW1_AVAILABLE, BaseLLM, MockLLM, create_llm, hw1_load_settings
from .state import WorkflowState
from .tracing import Tracer

DEMO_TASK = "Build a small English word/number counter module with input validation."


def make_llm(provider: Optional[str] = None, model: Optional[str] = None) -> BaseLLM:
    """Build the model backend, borrowing Homework 1's factory when available."""

    if not HW1_AVAILABLE:
        print("[warn] hw1-code-agent/ not found; using the built-in fallback model",
              file=sys.stderr)
        return MockLLM()

    overrides = {}
    if provider:
        overrides["provider"] = provider
    if model:
        overrides["model"] = model
    settings = hw1_load_settings(**overrides)
    return create_llm(settings)


def _save(result: RunResult, run_dir: Path) -> Path:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    for key, value in result.state.artifacts.items():
        if key in {"code_path", "code_file"} or key.endswith("_verdict"):
            continue
        name = "code.py" if key == "code" else "{k}.md".format(k=key)
        (artifacts / name).write_text(value, encoding="utf-8")

    (run_dir / "state.json").write_text(
        json.dumps(result.state.to_dict(), ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8")
    return run_dir


def cmd_run(args: argparse.Namespace) -> int:
    task = args.task
    state = WorkflowState(task=task)
    run_dir = Path(args.out) / state.run_id
    tracer = Tracer(run_dir / "trace.jsonl", verbose=not args.quiet)
    llm = make_llm(args.provider, args.model)
    workflow = build_mini_se_flow(llm, run_dir)

    if not HW1_AVAILABLE:
        print("[warn] review step will use the fallback scanner", file=sys.stderr)

    engine = Engine(workflow, tracer=tracer, node_retries=args.retries,
                    max_steps=args.max_steps)
    result = engine.run(task, state)
    _save(result, run_dir)

    print("")
    print(result.summary())
    print("run directory: {d}".format(d=run_dir))
    if result.ok:
        print("final summary artifact:\n")
        print(result.state.get("summary", "(none)"))
    return 0 if result.ok else 1


def cmd_graph(args: argparse.Namespace) -> int:
    llm = MockLLM()
    workflow = build_mini_se_flow(llm, Path("."))
    print(workflow.describe())
    print("")
    print(workflow.to_mermaid())
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    args.task = DEMO_TASK
    args.out = args.out or "runs"
    args.quiet = getattr(args, "quiet", False)
    args.provider = getattr(args, "provider", None)
    args.model = getattr(args, "model", None)
    args.retries = getattr(args, "retries", 1)
    args.max_steps = getattr(args, "max_steps", 60)
    return cmd_run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mini-se-workflow",
        description="A 3-agent Mini SE workflow (requirements -> design -> code -> review).",
    )
    parser.add_argument("--version", action="version", version="mini-se " + __version__)

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the workflow for a task")
    run.add_argument("task", help="what to build")
    run.add_argument("--out", default="runs", help="output directory (default: runs)")
    run.add_argument("--provider", default=None, choices=["mock", "openai"])
    run.add_argument("--model", default=None)
    run.add_argument("--retries", type=int, default=1, help="node retries on exceptions")
    run.add_argument("--max-steps", type=int, default=60)
    run.add_argument("--quiet", action="store_true", help="suppress the live trace")
    run.set_defaults(func=cmd_run)

    demo = sub.add_parser("demo", help="run the built-in demo task")
    demo.add_argument("--out", default="runs")
    demo.add_argument("--provider", default=None, choices=["mock", "openai"])
    demo.add_argument("--model", default=None)
    demo.add_argument("--quiet", action="store_true")
    demo.set_defaults(func=cmd_demo, retries=1, max_steps=60)

    graph = sub.add_parser("graph", help="print the flow and its Mermaid diagram")
    graph.set_defaults(func=cmd_graph)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, do not dump a traceback
        print("error: {e}".format(e=exc), file=sys.stderr)
        if "--debug" in sys.argv:
            raise
        return 1
