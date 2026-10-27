"""Tests for the tool sandbox: path containment, reading, search, execution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import drop, make_workspace  # noqa: E402
from codeagent.tools import ToolContext, build_default_registry  # noqa: E402

SAMPLE = '''"""Sample module."""


def add(a, b):
    try:
        return a + b
    except:
        return 0


def flag(value):
    if value == None:
        return False
    return True
'''


class ToolSandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_workspace()
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "sample.py").write_text(SAMPLE, encoding="utf-8")
        (self.root / "pkg" / "notes.txt").write_text("hello\n", encoding="utf-8")
        self.ctx = ToolContext(workspace=self.root, allow_exec=True, timeout=15)
        self.registry = build_default_registry()

    def tearDown(self) -> None:
        drop(self.root)

    def test_read_file_adds_line_numbers(self) -> None:
        out = self.registry.run("read_file", {"path": "pkg/sample.py", "max_lines": 5}, self.ctx)
        self.assertIn("1 | ", out)
        self.assertIn("def add", out)
        self.assertIn("lines", out)

    def test_read_file_window(self) -> None:
        out = self.registry.run(
            "read_file", {"path": "pkg/sample.py", "start_line": 5, "max_lines": 2}, self.ctx)
        self.assertIn("5 | ", out)
        self.assertNotIn(" 4 | ", out)

    def test_read_missing_file_is_an_observation_not_a_crash(self) -> None:
        out = self.registry.run("read_file", {"path": "missing.py"}, self.ctx)
        self.assertTrue(out.startswith("ERROR:"))
        self.assertIn("no such file", out)

    def test_path_escape_is_rejected(self) -> None:
        out = self.registry.run("read_file", {"path": "../../etc/passwd"}, self.ctx)
        self.assertTrue(out.startswith("ERROR:"))
        self.assertIn("outside the workspace", out)

    def test_absolute_path_outside_workspace_is_rejected(self) -> None:
        out = self.registry.run("read_file", {"path": "C:/Windows/win.ini"}, self.ctx)
        self.assertTrue(out.startswith("ERROR:"))

    def test_directory_instead_of_file_is_explained(self) -> None:
        out = self.registry.run("read_file", {"path": "pkg"}, self.ctx)
        self.assertIn("is a directory", out)

    def test_list_files_honours_pattern(self) -> None:
        out = self.registry.run("list_files", {"path": ".", "pattern": "*.py"}, self.ctx)
        self.assertIn("pkg/sample.py", out)
        self.assertNotIn("notes.txt", out)

    def test_search_code_reports_file_and_line(self) -> None:
        out = self.registry.run(
            "search_code", {"pattern": r"except:", "path": ".", "glob": "*.py"}, self.ctx)
        self.assertIn("pkg/sample.py:7", out)

    def test_search_rejects_bad_regex(self) -> None:
        out = self.registry.run("search_code", {"pattern": "([unclosed"}, self.ctx)
        self.assertTrue(out.startswith("ERROR:"))
        self.assertIn("invalid regular expression", out)

    def test_run_python_snippet(self) -> None:
        out = self.registry.run("run_python", {"code": "print(6 * 7)"}, self.ctx)
        self.assertIn("exit_code=0", out)
        self.assertIn("42", out)

    def test_run_python_reports_failure(self) -> None:
        out = self.registry.run("run_python", {"code": "raise SystemExit(3)"}, self.ctx)
        self.assertIn("exit_code=3", out)

    def test_run_python_file(self) -> None:
        (self.root / "ok.py").write_text("print('from file')\n", encoding="utf-8")
        out = self.registry.run("run_python_file", {"path": "ok.py"}, self.ctx)
        self.assertIn("from file", out)

    def test_execution_can_be_switched_off(self) -> None:
        frozen = ToolContext(workspace=self.root, allow_exec=False)
        out = self.registry.run("run_python", {"code": "print(1)"}, frozen)
        self.assertTrue(out.startswith("ERROR:"))
        self.assertIn("disabled", out)

    def test_unknown_tool_lists_alternatives(self) -> None:
        out = self.registry.run("delete_everything", {}, self.ctx)
        self.assertTrue(out.startswith("ERROR:"))
        self.assertIn("read_file", out)

    def test_registering_the_same_tool_twice_fails(self) -> None:
        registry = build_default_registry()
        with self.assertRaises(ValueError):
            registry.register(registry.get("read_file"))

    def test_relative_dot_slash_path_stays_inside(self) -> None:
        (self.root / "a.py").write_text("x = 1\n", encoding="utf-8")
        out = self.registry.run("read_file", {"path": "./a.py"}, self.ctx)
        self.assertIn("x = 1", out)

    def test_tool_description_lists_parameters(self) -> None:
        text = self.registry.describe()
        self.assertIn("read_file", text)
        self.assertIn("params:", text)


if __name__ == "__main__":
    unittest.main()
