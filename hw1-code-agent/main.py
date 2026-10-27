#!/usr/bin/env python3
"""CodePilot entry point.

    python main.py review examples/buggy_calculator.py -v
    python main.py chat
    python main.py tools
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codeagent.cli import main  # noqa: E402  (path setup must run first)

if __name__ == "__main__":
    raise SystemExit(main())
