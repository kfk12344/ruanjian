# -*- coding: utf-8 -*-
"""Regenerate the example transcripts with clean UTF-8 output.

Run from the repository root:  python capture_examples.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

NOISE = ("python.exe :", "所在位置", "CategoryInfo", "FullyQualifiedErrorId")


def clean(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if any(token in line for token in NOISE):
            continue
        if line.lstrip().startswith("+ "):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept) + "\n"


def run(cwd: Path, args):
    proc = subprocess.run(
        [PY] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )
    return proc.returncode, proc.stdout, proc.stderr


def capture_hw1() -> int:
    hw1 = REPO / "hw1-code-agent"
    code, out, err = run(hw1, ["main.py", "review", "examples/buggy_calculator.py", "-v"])
    print("hw1 exit:", code)

    content = (
        "# CodePilot review of `examples/buggy_calculator.py`\n\n"
        "Reproduced with `python main.py review examples/buggy_calculator.py -v` "
        "using the offline model (no API key, no network).\n\n"
        "## Agent trace (stderr)\n\n"
        "```text\n" + clean(err) + "```\n\n"
        "## Report (stdout)\n\n"
        "```markdown\n" + out.strip() + "\n```\n"
    )
    (hw1 / "examples" / "sample-review.md").write_text(content, encoding="utf-8")
    return code


def capture_hw2() -> int:
    hw2 = REPO / "hw2-workflow"
    runs_dir = hw2 / "runs"
    if runs_dir.exists():
        shutil.rmtree(runs_dir)

    code, out, err = run(hw2, ["main.py", "demo", "--out", "runs"])
    print("hw2 exit:", code)

    target = hw2 / "examples" / "sample-run"
    if target.exists():
        shutil.rmtree(target)

    candidates = sorted(runs_dir.glob("*"), key=lambda path: path.stat().st_mtime) if runs_dir.exists() else []
    if candidates:
        shutil.copytree(candidates[-1], target,
                        ignore=shutil.ignore_patterns("trace.jsonl"))
        (target / "console.txt").write_text(clean(err), encoding="utf-8")
    return code


def main() -> int:
    failures = capture_hw1() + capture_hw2()
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
