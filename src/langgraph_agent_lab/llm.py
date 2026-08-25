"""LLM factory helper.

Provides a simple interface to create LLM clients for use in nodes.
Students should use this helper so the lab works with any supported provider.

Usage in nodes:
    from .llm import get_llm
    llm = get_llm()
    response = llm.invoke("Hello")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, cast


class InvokableLLM(Protocol):
    """Minimal interface used by workflow nodes."""

    def invoke(self, input: object, **kwargs: object) -> object: ...

    def with_structured_output(self, schema: object, **kwargs: object) -> InvokableLLM: ...


def load_local_environment(path: Path | None = None) -> None:
    """Load simple KEY=VALUE entries from .env without overwriting exported variables.

    Keeping this tiny loader local makes the project runnable without requiring a
    separate dotenv dependency. It intentionally supports the conventional format
    used by .env.example, including comments and quoted values.
    """
    env_path = path or Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _api_key(name: str) -> str | None:
    """Return a usable API key, ignoring instructional placeholder values."""
    value = os.getenv(name)
    return value if value and not value.endswith("...") else None


def get_llm(model: str | None = None, temperature: float = 0.0) -> InvokableLLM:
    """Create an LLM client from environment configuration.

    Checks for API keys in this order:
    1. GEMINI_API_KEY → ChatGoogleGenerativeAI
    2. OPENAI_API_KEY → ChatOpenAI
    3. ANTHROPIC_API_KEY → ChatAnthropic

    Override model with the `model` parameter or LLM_MODEL env var.
    """
    load_local_environment()

    gemini_key = _api_key("GEMINI_API_KEY")
    openai_key = _api_key("OPENAI_API_KEY")
    anthropic_key = _api_key("ANTHROPIC_API_KEY")

    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise RuntimeError("Install: pip install langchain-google-genai") from exc
        return cast(
            InvokableLLM,
            ChatGoogleGenerativeAI(
                model=model or os.getenv("LLM_MODEL") or "gemini-3.6-flash",
                google_api_key=gemini_key,
                temperature=temperature,
            ),
        )

    if openai_key:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("Install: pip install langchain-openai") from exc
        return cast(
            InvokableLLM,
            ChatOpenAI(
                model=model or os.getenv("LLM_MODEL") or "gpt-4o-mini",
                temperature=temperature,
            ),
        )

    if anthropic_key:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError("Install: pip install langchain-anthropic") from exc
        return cast(
            InvokableLLM,
            ChatAnthropic(
                model=model or os.getenv("LLM_MODEL") or "claude-sonnet-4-20250514",
                temperature=temperature,
            ),
        )

    raise RuntimeError(
        "No LLM API key found. Set GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY in .env\n"
        "See .env.example for configuration."
    )
