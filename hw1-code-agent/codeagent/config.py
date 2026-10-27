"""Central configuration for the Code Agent.

Every knob is overridable through environment variables so the same code base
can run (a) fully offline with the deterministic mock model, or (b) against any
OpenAI-compatible endpoint:

    CODEAGENT_PROVIDER    mock | openai            (default: auto-detect)
    CODEAGENT_MODEL       model name               (default: gpt-4o-mini)
    CODEAGENT_BASE_URL    OpenAI-compatible root   (default: https://api.openai.com/v1)
    CODEAGENT_API_KEY     API key                  (falls back to OPENAI_API_KEY)
    CODEAGENT_TEMPERATURE sampling temperature     (default: 0.1)
    CODEAGENT_MAX_TOKENS  max tokens per reply     (default: 1600)
    CODEAGENT_MAX_STEPS   max tool-using turns     (default: 8)
    CODEAGENT_MAX_RETRIES retries on LLM failures  (default: 3)
    CODEAGENT_TIMEOUT     per-request timeout (s)  (default: 60)
    CODEAGENT_ALLOW_EXEC  allow running python     (default: 1)
    CODEAGENT_WORKSPACE   sandbox root for tools   (default: cwd)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(raw: str, default: bool = True) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _int(raw: str, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _float(raw: str, default: float) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings resolved once at start-up."""

    provider: str = "mock"
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 1600
    max_steps: int = 8
    max_retries: int = 3
    retry_backoff: float = 1.5
    request_timeout: float = 60.0
    allow_exec: bool = True
    workspace: Path = Path(".").resolve()

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    def describe(self) -> str:
        return (
            "provider={p} model={m} base_url={u} max_steps={s} "
            "allow_exec={e} workspace={w}"
        ).format(
            p=self.provider,
            m=self.model,
            u=self.base_url,
            # The key is never printed in full.
            e=self.allow_exec,
            s=self.max_steps,
            w=self.workspace,
        )


def load_settings(env=None, **overrides) -> Settings:
    """Build :class:`Settings` from the environment plus explicit overrides."""

    env = os.environ if env is None else env
    get = lambda name, default="": env.get(name, default) or default

    api_key = get("CODEAGENT_API_KEY") or get("OPENAI_API_KEY")
    provider = get("CODEAGENT_PROVIDER", "").strip().lower()
    if not provider:
        provider = "openai" if api_key else "mock"

    base_url = get("CODEAGENT_BASE_URL") or get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    workspace = Path(overrides.pop("workspace", None) or get("CODEAGENT_WORKSPACE", "") or Path.cwd())

    values = dict(
        provider=provider,
        model=get("CODEAGENT_MODEL") or get("OPENAI_MODEL") or "gpt-4o-mini",
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        temperature=_float(get("CODEAGENT_TEMPERATURE"), 0.1),
        max_tokens=_int(get("CODEAGENT_MAX_TOKENS"), 1600),
        max_steps=_int(get("CODEAGENT_MAX_STEPS"), 8),
        max_retries=_int(get("CODEAGENT_MAX_RETRIES"), 3),
        retry_backoff=_float(get("CODEAGENT_RETRY_BACKOFF"), 1.5),
        request_timeout=_float(get("CODEAGENT_TIMEOUT"), 60.0),
        allow_exec=_flag(get("CODEAGENT_ALLOW_EXEC"), True),
        workspace=Path(workspace).expanduser().resolve(),
    )
    values.update(overrides)
    return Settings(**values)
