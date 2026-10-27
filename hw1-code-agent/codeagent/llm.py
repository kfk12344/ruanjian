"""LLM back-ends.

Three implementations share one tiny interface so the agent loop never has to
care where the text comes from:

* :class:`OpenAICompatibleLLM` -- any ``/chat/completions`` endpoint (OpenAI,
  DeepSeek, Qwen/DashScope compatibility mode, local vLLM, Ollama ...).
* :class:`MockLLM` -- a deterministic, rule-based stand-in used for the offline
  demo and the test-suite. It really inspects the file it is given, so the
  review it prints is grounded in the code under review.
* :class:`ScriptedLLM` -- replays a fixed list of replies; used by unit tests.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Iterable, List, Optional, Sequence

from .config import Settings


class LLMError(RuntimeError):
    """Raised when a provider cannot produce a completion."""


class BaseLLM(ABC):
    """Minimal chat interface: a list of role/content dicts in, text out."""

    name: str = "base"

    @abstractmethod
    def complete(
        self,
        messages: Sequence[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        raise NotImplementedError


class ScriptedLLM(BaseLLM):
    """Replays canned replies in order; raises once the script runs out."""

    name = "scripted"

    def __init__(self, replies: Iterable[str]):
        self._replies: List[str] = list(replies)
        self.calls: List[List[dict]] = []

    def complete(self, messages, temperature=None, max_tokens=None) -> str:
        self.calls.append([dict(m) for m in messages])
        if not self._replies:
            raise LLMError("scripted model has no replies left")
        return self._replies.pop(0)


class OpenAICompatibleLLM(BaseLLM):
    """Thin ``urllib`` client for the OpenAI chat-completions shape."""

    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise LLMError(
                "no API key configured; set CODEAGENT_API_KEY or OPENAI_API_KEY, "
                "or run with CODEAGENT_PROVIDER=mock"
            )
        self.settings = settings

    def complete(self, messages, temperature=None, max_tokens=None) -> str:
        payload = {
            "model": self.settings.model,
            "messages": list(messages),
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": self.settings.max_tokens if max_tokens is None else max_tokens,
        }
        request = urllib.request.Request(
            self.settings.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.settings.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.request_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx/5xx carry a JSON explanation
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise LLMError("HTTP {code} from {url}: {detail}".format(
                code=exc.code, url=self.settings.base_url, detail=detail)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError("cannot reach {url}: {exc}".format(url=self.settings.base_url, exc=exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("provider returned non-JSON body: {exc}".format(exc=exc)) from exc

        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected response shape: {body}".format(
                body=json.dumps(body)[:300])) from exc


# --------------------------------------------------------------------------- #
# Offline stand-in
# --------------------------------------------------------------------------- #

_ISSUE_RULES = [
    # (regex, severity, title, advice)
    (r"except\s*:", "HIGH", "Bare `except:` swallows every exception",
     "Catch the specific exception you can handle, e.g. `except ValueError`."),
    (r"except\s+Exception\s+as\s+\w+\s*:\s*(pass|\.\.\.)", "HIGH", "Silently ignored exception",
     "Log or re-raise; `pass` here hides real failures."),
    (r"\beval\s*\(", "HIGH", "`eval()` executes arbitrary code",
     "Use `ast.literal_eval` for data or an explicit parser."),
    (r"\bexec\s*\(", "HIGH", "`exec()` executes arbitrary code",
     "Avoid dynamic execution; call the function you need."),
    (r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\})", "HIGH", "Mutable default argument",
     "Default to `None` and create the list/dict inside the function."),
    (r"==\s*None\b", "MEDIUM", "Comparison with `None` using `==`",
     "Use `is None` / `is not None`."),
    (r"==\s*(True|False)\b", "MEDIUM", "Boolean compared with `==`",
     "Use `if flag:` / `if not flag:`."),
    (r"\bassert\s+", "MEDIUM", "`assert` disappears under `python -O`",
     "Raise `ValueError` for input validation that must always run."),
    (r"\bwhile\s+True\s*:", "MEDIUM", "Unbounded `while True` loop",
     "Add an explicit exit condition or a maximum iteration count."),
    (r"(?<!with )\bopen\s*\(", "MEDIUM", "File opened without a context manager",
     "Use `with open(...) as fh:` so the handle is always closed."),
    (r"print\s*\(", "LOW", "`print()` used for diagnostics",
     "Use the `logging` module so output can be filtered."),
    (r"TODO|FIXME", "LOW", "Unresolved TODO/FIXME marker",
     "Finish the work or file a tracking issue."),
    (r"range\s*\(\s*len\s*\(", "LOW", "Index loop over a sequence",
     "Prefer `for item in items` or `enumerate(items)`."),
    (r"\bglobal\s+\w+", "LOW", "Mutable global state",
     "Pass the value explicitly or wrap it in a small class."),
    (r"shell\s*=\s*True", "HIGH", "`shell=True` enables command injection",
     "Pass an argument list and keep `shell=False`."),
]

# Rules that span more than one line; matched against the whole source.
_BLOCK_RULES = [
    (r"except\s+(?:Exception|BaseException)\s+as\s+\w+\s*:\s*\n\s*(?:pass|\.\.\.)",
     "HIGH", "Exception swallowed with `pass`",
     "Log the failure or re-raise; `pass` here hides every error."),
    (r"except\s*:\s*\n\s*pass\b", "HIGH", "Bare `except: pass`",
     "Catch the specific exception and handle it explicitly."),
]


class MockLLM(BaseLLM):
    """Deterministic stand-in so the demo and the tests need no network.

    It plays two roles:

    * inside the review agent it answers with valid ReAct JSON, performing the
      same tool calls a real model would (read the file, grep it, then report);
    * inside the workflow (``[WORKFLOW-*]`` system prompts) it returns a
      template document built from the task description.
    """

    name = "mock"

    def __init__(self):
        self.calls = 0

    # -- public API -------------------------------------------------------- #
    def complete(self, messages, temperature=None, max_tokens=None) -> str:
        self.calls += 1
        system = (messages[0].get("content") or "") if messages else ""
        mode = re.search(r"\[WORKFLOW-([A-Z_]+)\]", system)
        if mode:
            return self._workflow_reply(mode.group(1), messages)
        return self._react_reply(messages)

    # -- workflow templates ------------------------------------------------ #
    def _workflow_reply(self, mode: str, messages) -> str:
        task = self._first_task_text(messages)
        user = (messages[-1].get("content") or "") if messages else ""
        if mode == "CODING":
            # First pass ships a real defect so the workflow's review gate has
            # something to catch; the retry (which carries reviewer feedback)
            # returns the fixed version.
            template = _CODING_TEMPLATE_V2 if "## code_feedback" in user else _CODING_TEMPLATE_V1
            return template.format(task=task)
        template = {
            "REQUIREMENT": _REQUIREMENT_TEMPLATE,
            "DESIGN": _DESIGN_TEMPLATE,
            "DOCS": _DOCS_TEMPLATE,
            "SUMMARY": _SUMMARY_TEMPLATE,
            "FIX": _FIX_TEMPLATE,
        }.get(mode, _SUMMARY_TEMPLATE)
        return template.format(task=task)

    @staticmethod
    def _first_task_text(messages) -> str:
        for message in messages:
            if message.get("role") == "user":
                text = (message.get("content") or "").strip()
                # The prompt is "TASK: <task>\n\n## <artifact>\n..."; stop at the
                # first context section so upstream documents do not leak in.
                match = re.search(r"TASK:\s*(.+?)(?:\n\s*\n## |\Z)", text, re.S)
                return (match.group(1).strip() if match else text)[:600]
        return "(no task supplied)"

    # -- ReAct policy ------------------------------------------------------ #
    def _react_reply(self, messages) -> str:
        observations = [
            m.get("content", "") for m in messages
            if m.get("role") == "user" and (m.get("content") or "").startswith("OBSERVATION")
        ]
        target = self._target_file(messages)

        if not observations:
            return _action("read_file", {"path": target, "max_lines": 400})

        if len(observations) == 1:
            return _action("search_code", {
                "pattern": r"except|eval|exec|== *None|print\(|while True|TODO|open\(",
                "path": target,
            })

        source = self._source_from(observations)
        return json.dumps(
            {"thought": "I have the source and the grep hits; writing the review.",
             "final_answer": build_offline_review(target, source)},
            ensure_ascii=False,
        )

    @staticmethod
    def _target_file(messages) -> str:
        for message in messages:
            if message.get("role") == "user":
                match = re.search(r"TARGET_FILE:\s*(\S+)", message.get("content") or "")
                if match:
                    return match.group(1)
        return "examples/buggy_calculator.py"

    @staticmethod
    def _source_from(observations) -> str:
        for text in observations:
            if text.startswith("OBSERVATION[read_file]"):
                body = text.split("\n", 1)[1] if "\n" in text else ""
                # Strip the "   12 | " line-number gutter added by read_file.
                lines = []
                for line in body.splitlines():
                    match = re.match(r"^\s*\d+\s*\|\s?(.*)$", line)
                    lines.append(match.group(1) if match else line)
                return "\n".join(lines)
        return ""


def _action(name: str, payload: dict) -> str:
    return json.dumps(
        {"thought": "call {n} to gather evidence".format(n=name),
         "action": name, "action_input": payload},
        ensure_ascii=False,
    )


def build_offline_review(target: str, source: str) -> str:
    """Rule-based review used by the offline demo; also the mock's final answer."""

    findings = []
    lines = source.splitlines()
    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern, severity, title, advice in _ISSUE_RULES:
            if re.search(pattern, line):
                findings.append((severity, index, title, stripped[:110], advice))

    # Multi-line rules: report the line where the construct starts.
    for pattern, severity, title, advice in _BLOCK_RULES:
        for match in re.finditer(pattern, source, re.MULTILINE):
            line_number = source.count("\n", 0, match.start()) + 1
            snippet = match.group(0).splitlines()[0].strip()[:110]
            findings.append((severity, line_number, title, snippet, advice))

    # One finding per (line, title); overlapping rules must not double-report.
    seen = set()
    unique = []
    for finding in findings:
        key = (finding[1], finding[2])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    findings = unique

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda item: (order[item[0]], item[1]))

    header = [
        "# Code review: {}".format(target),
        "",
        "**Verdict:** {verdict}  ".format(
            verdict="request changes" if any(f[0] == "HIGH" for f in findings) else "approve with nits"),
        "**Lines reviewed:** {n}  ".format(n=len(lines)),
        "**Findings:** {n} ({h} high / {m} medium / {l} low)".format(
            n=len(findings),
            h=sum(1 for f in findings if f[0] == "HIGH"),
            m=sum(1 for f in findings if f[0] == "MEDIUM"),
            l=sum(1 for f in findings if f[0] == "LOW"),
        ),
        "",
        "## Findings",
        "",
    ]
    if findings:
        header.append("| # | Severity | Line | Finding | Evidence | Suggested fix |")
        header.append("|---|----------|------|---------|----------|---------------|")
        for number, (severity, line, title, evidence, advice) in enumerate(findings, 1):
            header.append("| {n} | {s} | {l} | {t} | `{e}` | {a} |".format(
                n=number, s=severity, l=line, t=title,
                e=evidence.replace("|", "\\|"), a=advice))
    else:
        header.append("No rule-based issues detected.")

    header += [
        "",
        "## Suggestions",
        "",
        "1. Add type hints to public functions and a module-level docstring.",
        "2. Cover the error paths with `unittest` cases; the happy path alone is not enough.",
        "3. Keep functions under ~30 lines so each has one reason to change.",
        "",
    ]
    return "\n".join(header)


_REQUIREMENT_TEMPLATE = """# Requirements: {task}

## 1. Goal
Deliver a small, runnable tool for: {task}

## 2. Functional requirements
- FR-1 Parse and validate the incoming text.
- FR-2 Expose one public function per user-visible operation.
- FR-3 Return structured results instead of printing.

## 3. Non-functional requirements
- NFR-1 Python 3.9+, standard library only.
- NFR-2 Every public function has a docstring and type hints.
- NFR-3 Failures raise ValueError with an actionable message.

## 4. Acceptance criteria
- AC-1 `python -m unittest` passes.
- AC-2 Invalid input is rejected with a clear message, never a traceback.
"""

_DESIGN_TEMPLATE = """# Design: {task}

## 1. Overview
A single module with a pure core and a thin command-line wrapper.

## 2. Modules
| Module | Responsibility |
|--------|----------------|
| `core.py` | Pure functions, no I/O, fully unit-testable |
| `cli.py` | Argument parsing and formatting only |

## 3. Data flow
input text -> validate() -> transform() -> Result dataclass -> render()

## 4. Error strategy
Validate at the boundary, raise `ValueError` with the offending value, and let
the CLI turn it into a non-zero exit code plus a one-line message.

## 5. Test plan
Unit tests for the happy path, empty input, wrong type, and out-of-range values.
"""

_CODING_TEMPLATE_V1 = """```python
\"\"\"Draft implementation for: {task}\"\"\"


def transform(text):
    try:
        return text.split()
    except:
        return []


def count_words(text):
    words = transform(text)
    print("word count:", len(words))
    return len(words)
```
"""

_CODING_TEMPLATE_V2 = """```python
\"\"\"Generated by the coding agent for: {task}\"\"\"

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Result:
    \"\"\"Outcome of one transformation.\"\"\"
    original: str
    words: List[str]
    numbers: List[int]


def transform(text: str) -> Result:
    \"\"\"Split text into words and integers.\"\"\"
    if not isinstance(text, str):
        raise ValueError("text must be a str, got %r" % (type(text).__name__,))
    if not text.strip():
        raise ValueError("text must not be empty")
    words = re.findall(r"[A-Za-z_]+", text)
    numbers = [int(n) for n in re.findall(r"-?\\d+", text)]
    return Result(original=text, words=words, numbers=numbers)


def render(result: Result) -> str:
    \"\"\"Render a result for humans.\"\"\"
    return "words=%d numbers=%d total=%d" % (
        len(result.words), len(result.numbers), sum(result.numbers))
```
"""

_DOCS_TEMPLATE = """# Usage: {task}

## Quick start
```
python main.py "some input text"
```

## API
| Function | Purpose |
|----------|---------|
| `transform(text)` | Split text into words and integers, raising `ValueError` on bad input |
| `render(result)` | Format a result for humans |

## Error handling
Invalid input raises `ValueError`; the CLI prints the message and exits non-zero.
"""

_FIX_TEMPLATE = """# Fix plan for: {task}

- H-1 Replace the broad `except` with the specific exception type.
- H-2 Validate arguments at the entry point and raise `ValueError`.
- M-1 Add a context manager for file handles.
- L-1 Swap `print` for `logging`.

The next coding round applies these changes and re-runs the reviewer.
"""

_SUMMARY_TEMPLATE = """# Run summary: {task}

| Stage | Status |
|-------|--------|
| Requirements | done |
| Design | done |
| Implementation | done |
| Review | done |

**Open risks:** the generated code is a template for the offline demo; run the
flow with a real model (`CODEAGENT_PROVIDER=openai`) for production-quality code.
"""


def create_llm(settings: Settings, replies: Optional[Sequence[str]] = None) -> BaseLLM:
    """Factory: scripted > mock > OpenAI-compatible, based on settings."""

    if replies is not None:
        return ScriptedLLM(replies)
    if settings.is_mock:
        return MockLLM()
    if settings.provider == "openai":
        return OpenAICompatibleLLM(settings)
    raise LLMError("unknown provider {p!r} (expected 'mock' or 'openai')".format(p=settings.provider))


def retry_with_backoff(func, attempts: int = 3, backoff: float = 1.5, sleep=time.sleep):
    """Call ``func`` up to ``attempts`` times, backing off between failures."""

    last = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except LLMError as exc:
            last = exc
            if attempt < attempts:
                sleep(backoff ** attempt)
    raise LLMError("giving up after {n} attempts: {last}".format(n=attempts, last=last))
