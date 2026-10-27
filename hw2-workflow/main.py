#!/usr/bin/env python3
"""Mini SE Workflow entry point.

    python main.py demo
    python main.py run "build a word counter"
    python main.py graph
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow.cli import main  # noqa: E402  (path setup must run first)

if __name__ == "__main__":
    raise SystemExit(main())
