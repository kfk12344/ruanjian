"""Tool layer: a small, auditable sandbox the agent can act through.

Design notes
------------
* Every tool receives a :class:`ToolContext` carrying the workspace root, the
  execution switch and the timeout, so tools stay pure functions of their input.
* All paths are resolved inside the workspace root; anything that escapes it
  (``..``, absolute paths elsewhere, symlinks out) raises :class:`ToolError`
  instead of silently touching the host file system.
* A tool never raises into the agent loop: :meth:`ToolRegistry.run` converts
  failures into ``ERROR: ...`` observations, which the model is told to react to.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

MAX_OUTPUT_CHARS = 12000


class ToolError(RuntimeError):
    """A tool rejected its input or failed safely."""


@dataclass
class ToolContext:
    """Everything a tool needs to run, injected by the agent."""

    workspace: Path
    allow_exec: bool = True
    timeout: float = 10.0


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, str]
    func: Callable[[dict, ToolContext], str]
    requires_exec: bool = False

    def signature(self) -> str:
        parts = []
        for key, hint in self.parameters.items():
            parts.append("{k}: {h}".format(k=key, h=hint))
        return "{n}({args})".format(n=self.name, args=", ".join(parts))


def _resolve(ctx: ToolContext, raw: str) -> Path:
    """Resolve ``raw`` inside the workspace or raise :class:`ToolError`."""

    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("path must be a non-empty string")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ctx.workspace / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:  # pragma: no cover - platform dependent
        raise ToolError("cannot resolve {p!r}: {e}".format(p=raw, e=exc)) from exc

    root = ctx.workspace.resolve()
    if resolved != root and root not in resolved.parents:
        raise ToolError(
            "path {p!r} is outside the workspace {w}; refusing to touch it".format(
                p=raw, w=root)
        )
    return resolved


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated {n} characters]".format(n=len(text) - limit)


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

def tool_list_files(args: dict, ctx: ToolContext) -> str:
    root = _resolve(ctx, args.get("path", "."))
    pattern = args.get("pattern", "*")
    if not root.exists():
        raise ToolError("no such path {p}".format(p=args.get("path")))
    if root.is_file():
        return str(root.relative_to(ctx.workspace.resolve()))

    matches: List[str] = []
    for path in sorted(root.rglob(pattern)):
        if path.is_dir():
            continue
        if any(part in {".git", "__pycache__", ".codeagent_tmp"} for part in path.parts):
            continue
        try:
            matches.append(path.relative_to(ctx.workspace.resolve()).as_posix())
        except ValueError:  # pragma: no cover - defensive
            continue
        if len(matches) >= 200:
            matches.append("... [more than 200 files, narrow the pattern]")
            break
    return "\n".join(matches) if matches else "no files matched pattern {p!r}".format(p=pattern)


def tool_read_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(ctx, args.get("path", ""))
    if not path.exists():
        raise ToolError("no such file {p}".format(p=args.get("path")))
    if path.is_dir():
        raise ToolError("{p} is a directory; use list_files".format(p=args.get("path")))
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError("cannot read {p}: {e}".format(p=args.get("path"), e=exc)) from exc

    start = max(1, int(args.get("start_line", 1) or 1))
    max_lines = max(1, min(int(args.get("max_lines", 400) or 400), 2000))
    lines = raw.splitlines()
    window = lines[start - 1:start - 1 + max_lines]

    body = "\n".join(
        "{n:>5} | {line}".format(n=start + offset, line=line)
        for offset, line in enumerate(window)
    )
    if start - 1 + max_lines < len(lines):
        body += "\n... [file continues; call read_file with start_line={n}]".format(
            n=start + max_lines)
    return "{p} ({total} lines)\n{body}".format(
        p=path.relative_to(ctx.workspace.resolve()).as_posix(),
        total=len(lines), body=body)


def tool_search_code(args: dict, ctx: ToolContext) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        raise ToolError("pattern must not be empty")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError("invalid regular expression {p!r}: {e}".format(p=pattern, e=exc)) from exc

    root = _resolve(ctx, args.get("path", "."))
    if root.is_file():
        files = [root]
    else:
        files = [p for p in sorted(root.rglob(args.get("glob", "*.py")))
                 if p.is_file() and "__pycache__" not in p.parts]

    hits: List[str] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                rel = path.relative_to(ctx.workspace.resolve()).as_posix()
                hits.append("{f}:{n}: {l}".format(f=rel, n=number, l=line.strip()[:160]))
                if len(hits) >= 80:
                    hits.append("... [more than 80 hits]")
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "no matches for {p!r}".format(p=pattern)


def _run_python_file(path: Path, ctx: ToolContext) -> str:
    if not ctx.allow_exec:
        raise ToolError("code execution is disabled (CODEAGENT_ALLOW_EXEC=0)")
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(ctx.workspace),
            capture_output=True,
            text=True,
            timeout=ctx.timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise ToolError("execution timed out after {t}s".format(t=ctx.timeout))
    except OSError as exc:
        raise ToolError("cannot start python: {e}".format(e=exc)) from exc

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    parts = ["exit_code={c}".format(c=completed.returncode)]
    if stdout:
        parts.append("stdout:\n" + stdout)
    if stderr:
        parts.append("stderr:\n" + stderr)
    return _truncate("\n".join(parts))


def tool_run_python_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(ctx, args.get("path", ""))
    if not path.is_file():
        raise ToolError("no such file {p}".format(p=args.get("path")))
    return _run_python_file(path, ctx)


def tool_run_python(args: dict, ctx: ToolContext) -> str:
    code = args.get("code", "")
    if not code.strip():
        raise ToolError("code must not be empty")
    if not ctx.allow_exec:
        raise ToolError("code execution is disabled (CODEAGENT_ALLOW_EXEC=0)")

    scratch = ctx.workspace / ".codeagent_tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / ("snippet_{s}.py".format(s=uuid.uuid4().hex[:8]))
    try:
        target.write_text(code, encoding="utf-8")
        return _run_python_file(target, ctx)
    finally:
        try:
            target.unlink()
        except OSError:  # pragma: no cover - best effort cleanup
            pass


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

class ToolRegistry:
    """Name -> :class:`Tool` lookup with a human-readable catalogue."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> "ToolRegistry":
        if tool.name in self._tools:
            raise ValueError("tool {n!r} registered twice".format(n=tool.name))
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(
                "unknown tool {n!r}; available: {names}".format(
                    n=name, names=", ".join(sorted(self._tools)) or "(none)")
            ) from None

    @property
    def names(self) -> List[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        blocks = []
        for name in self.names:
            tool = self._tools[name]
            params = ", ".join(
                "{k} ({h})".format(k=k, h=h) for k, h in tool.parameters.items()
            ) or "none"
            blocks.append("- {n}: {d}\n    params: {p}".format(
                n=tool.name, d=tool.description, p=params))
        return "\n".join(blocks)

    def run(self, name: str, arguments: Optional[dict], ctx: ToolContext) -> str:
        """Execute a tool, turning every failure into an observation string."""

        try:
            tool = self.get(name)
            if tool.requires_exec and not ctx.allow_exec:
                raise ToolError("code execution is disabled (CODEAGENT_ALLOW_EXEC=0)")
            return _truncate(tool.func(arguments or {}, ctx))
        except ToolError as exc:
            return "ERROR: {e}".format(e=exc)
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            return "ERROR: unexpected failure in {n}: {e!r}".format(n=name, e=exc)


def build_default_registry() -> ToolRegistry:
    """The tool set shipped with the review agent."""

    registry = ToolRegistry()
    registry.register(Tool(
        name="list_files",
        description="List files under a directory, filtered by a glob pattern.",
        parameters={"path": "str, default '.'", "pattern": "glob, default '*'"},
        func=tool_list_files,
    ))
    registry.register(Tool(
        name="read_file",
        description="Read a text file with line numbers, optionally a line window.",
        parameters={"path": "str, required", "start_line": "int, default 1",
                    "max_lines": "int, default 400"},
        func=tool_read_file,
    ))
    registry.register(Tool(
        name="search_code",
        description="Regex search across files; returns file:line: text hits.",
        parameters={"pattern": "regex, required", "path": "str, default '.'",
                    "glob": "glob, default '*.py'"},
        func=tool_search_code,
    ))
    registry.register(Tool(
        name="run_python",
        description="Run a short Python snippet in the workspace (sandboxed, timed).",
        parameters={"code": "str, required"},
        func=tool_run_python,
        requires_exec=True,
    ))
    registry.register(Tool(
        name="run_python_file",
        description="Run an existing Python file in the workspace and capture output.",
        parameters={"path": "str, required"},
        func=tool_run_python_file,
        requires_exec=True,
    ))
    return registry
