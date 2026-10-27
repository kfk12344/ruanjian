"""Execution tracing: one console line per event plus a JSONL audit log.

The console output is for humans following a demo; ``trace.jsonl`` is for
post-mortem analysis and for the "执行日志与状态追踪" requirement.

Everything written to the console is ASCII on purpose: the default Windows
console code page is not UTF-8 and would raise UnicodeEncodeError on box-drawing
or emoji characters.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, TextIO


class Tracer:
    """Writes events to the console and (optionally) to ``trace.jsonl``."""

    def __init__(self, path: Path = None, stream: TextIO = None, verbose: bool = True):
        self.path = Path(path) if path else None
        self.stream = stream if stream is not None else sys.stderr
        self.verbose = verbose
        self.events = []
        self._started = time.time()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def log(self, event: str, **fields: Any) -> None:
        record = {"t": round(time.time() - self._started, 4), "event": event}
        record.update(fields)
        self.events.append(record)
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.verbose:
            self._print(record)

    def _print(self, record: Dict[str, Any]) -> None:
        stamp = "{:>7.3f}s".format(record["t"])
        event = record["event"]
        if event == "run_start":
            line = "{stamp}  == {workflow} run {run_id}\n           task: {task}".format(
                stamp=stamp, **record)
        elif event == "step_start":
            line = "{stamp}  >> {label}  (visit {visit})".format(stamp=stamp, **record)
        elif event == "step_ok":
            line = "{stamp}  OK {label}  {ms}ms  {chars} chars".format(
                stamp=stamp, label=record.get("label"), ms=record.get("ms"),
                chars=record.get("chars"))
        elif event == "step_failed":
            line = "{stamp}  !! {label}  {reason}".format(
                stamp=stamp, label=record.get("label"), reason=record.get("reason"))
        elif event == "step_skipped":
            line = "{stamp}  -- {label}  skipped".format(stamp=stamp, label=record.get("label"))
        elif event == "message":
            line = "{stamp}     msg {sender} -> {recipient} [{kind}] {preview}".format(
                stamp=stamp, sender=record.get("sender"),
                recipient=record.get("recipient"), kind=record.get("kind"),
                preview=record.get("preview"))
        elif event == "jump":
            line = "{stamp}  << {frm} -> {to}  ({reason})".format(stamp=stamp, **record)
        elif event == "retry":
            line = "{stamp}  ~~ {label} retry {attempt}/{total}: {reason}".format(
                stamp=stamp, **record)
        elif event == "done":
            line = "{stamp}  == finished: {status} in {seconds}s".format(
                stamp=stamp, status=record.get("status"), seconds=record.get("seconds"))
        else:
            rest = {k: v for k, v in record.items() if k not in {"t", "event"}}
            line = "{stamp}  {event}  {rest}".format(stamp=stamp, event=event, rest=rest)
        print(line, file=self.stream, flush=True)
