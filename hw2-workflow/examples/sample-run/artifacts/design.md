# Design: Build a small English word/number counter module with input validation.

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