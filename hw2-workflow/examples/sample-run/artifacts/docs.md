# Usage: Build a small English word/number counter module with input validation.

## Quick start
```
python main.py "some input text"
```

## API
| Function | Purpose |
|----------|---------|
| `transform(text)` | Split text into words and integers, raising `ValueError` on bad input |
| `render(result)` | Format a result for humans |

## Error handling
Invalid input raises `ValueError`; the CLI prints the message and exits non-zero.