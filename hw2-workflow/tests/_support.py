"""Shared helpers for the workflow test-suite."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".test-scratch"


def make_workspace() -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / uuid.uuid4().hex[:10]
    path.mkdir()
    return path


def drop(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
