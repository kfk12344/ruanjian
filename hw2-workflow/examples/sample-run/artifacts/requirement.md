# Requirements: Build a small English word/number counter module with input validation.

## 1. Goal
Deliver a small, runnable tool for: Build a small English word/number counter module with input validation.

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