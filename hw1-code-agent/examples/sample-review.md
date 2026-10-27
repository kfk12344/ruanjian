# CodePilot review of `examples/buggy_calculator.py`

Reproduced with `python main.py review examples/buggy_calculator.py -v` using the offline model (no API key, no network).

## Agent trace (stderr)

```text
  [step 0] read_file({"path": "examples/buggy_calculator.py", "max_lines": 400})
  [step 1] search_code({"pattern": "except|eval|exec|== *None|print\\(|while True|TODO|open\\(", "path": "examples/buggy_calculator.py"})
--- agent trace ---
[0] thought: call read_file to gather evidence
    -> read_file({"path": "examples/buggy_calculator.py", "max_lines": 400})
    <- examples/buggy_calculator.py (73 lines)
           1 | """Deliberately flawed module used as the demo subject for CodePilot.
           2 |
           3 | Every defect here is realistic: this is the kind of code that passes a casual
           4 | review and then fails in production.
           5 | """
           6 |
           7 | import math
           8 | import os
           9 |
          10 |
          11 | CACHE = {}
          12 |
          13 |
          14 | def average(values=[]):
          15 |     # TODO: handle the empty list case properly
          16 |     total = 0
[1] thought: call search_code to gather evidence
    -> search_code({"pattern": "except|eval|exec|== *None|print\\(|while True|TODO|open\\(", "path": "examples/buggy_calculator.py"})
    <- examples/buggy_calculator.py:15: # TODO: handle the empty list case properly
       examples/buggy_calculator.py:24: return eval(raw)
       examples/buggy_calculator.py:25: except:
       examples/buggy_calculator.py:30: fh = open(path)
       examples/buggy_calculator.py:42: if user == None:
       examples/buggy_calculator.py:50: while True:
       examples/buggy_calculator.py:59: print("cached", key)
[2] thought: I have the source and the grep hits; writing the review.
    -> final answer (1948 chars)
--- end trace (3 steps, 0.01s) ---
```

## Report (stdout)

```markdown
# Code review: examples/buggy_calculator.py

**Verdict:** request changes  
**Lines reviewed:** 73  
**Findings:** 11 (3 high / 5 medium / 3 low)

## Findings

| # | Severity | Line | Finding | Evidence | Suggested fix |
|---|----------|------|---------|----------|---------------|
| 1 | HIGH | 14 | Mutable default argument | `def average(values=[]):` | Default to `None` and create the list/dict inside the function. |
| 2 | HIGH | 24 | `eval()` executes arbitrary code | `return eval(raw)` | Use `ast.literal_eval` for data or an explicit parser. |
| 3 | HIGH | 25 | Bare `except:` swallows every exception | `except:` | Catch the specific exception you can handle, e.g. `except ValueError`. |
| 4 | MEDIUM | 30 | File opened without a context manager | `fh = open(path)` | Use `with open(...) as fh:` so the handle is always closed. |
| 5 | MEDIUM | 42 | Comparison with `None` using `==` | `if user == None:` | Use `is None` / `is not None`. |
| 6 | MEDIUM | 44 | Boolean compared with `==` | `if user.get("age") == True:` | Use `if flag:` / `if not flag:`. |
| 7 | MEDIUM | 50 | Unbounded `while True` loop | `while True:` | Add an explicit exit condition or a maximum iteration count. |
| 8 | MEDIUM | 63 | `assert` disappears under `python -O` | `assert b != 0` | Raise `ValueError` for input validation that must always run. |
| 9 | LOW | 17 | Index loop over a sequence | `for i in range(len(values)):` | Prefer `for item in items` or `enumerate(items)`. |
| 10 | LOW | 57 | Mutable global state | `global CACHE` | Pass the value explicitly or wrap it in a small class. |
| 11 | LOW | 59 | `print()` used for diagnostics | `print("cached", key)` | Use the `logging` module so output can be filtered. |

## Suggestions

1. Add type hints to public functions and a module-level docstring.
2. Cover the error paths with `unittest` cases; the happy path alone is not enough.
3. Keep functions under ~30 lines so each has one reason to change.
```
