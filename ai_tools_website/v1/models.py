"""Centralized OpenAI model configuration."""

import os
from typing import Final

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Environment variable {name} must be set to the desired OpenAI model name; no fallback is available."
        )
    return value


CONTENT_ENHANCER_MODEL: Final[str] = _require_env("CONTENT_ENHANCER_MODEL")
SEARCH_MODEL: Final[str] = _require_env("SEARCH_MODEL")
MAINTENANCE_MODEL: Final[str] = _require_env("MAINTENANCE_MODEL")
WEB_SEARCH_MODEL: Final[str] = _require_env("WEB_SEARCH_MODEL")


__all__ = [
    "CONTENT_ENHANCER_MODEL",
    "SEARCH_MODEL",
    "MAINTENANCE_MODEL",
    "WEB_SEARCH_MODEL",
]
