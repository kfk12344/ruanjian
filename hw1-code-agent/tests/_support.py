"""Shared helpers for the test-suite.

Scratch workspaces are created next to the package (inside the repository) rather
than in the system temp directory: some sandboxes deny writes to %TEMP%, and the
tests must run anywhere.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".test-scratch"


def make_workspace() -> Path:
    """Create an isolated directory that acts as the agent workspace."""

    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / uuid.uuid4().hex[:10]
    path.mkdir()
    return path


def drop(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
