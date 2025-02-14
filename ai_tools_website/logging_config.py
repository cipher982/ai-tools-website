"""Logging configuration for the AI tools website."""

import logging
import sys
from pathlib import Path
from typing import Optional


class IndentLogger:
    """Logger wrapper that manages absolute indentation levels."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._indent = 0

    def indent(self, level: Optional[int] = None) -> None:
        """Set absolute indent level."""
        if level is not None:
            self._indent = max(0, level)
        else:
            self._indent += 1

    def dedent(self) -> None:
        """Decrease indent level."""
        self._indent = max(0, self._indent - 1)

    def _log(self, level: int, msg: str, *args, **kwargs) -> None:
        indent = "  " * self._indent
        prefix = "•" if self._indent > 0 else "▶"
        self._logger.log(level, f"{indent}{prefix} {msg}", *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration."""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # File handler for all logs
    file_handler = logging.FileHandler(log_dir / "ai_tools.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(file_handler)

    # Stream handler for INFO and above
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    root_logger.addHandler(stream_handler)

    # Silence httpx logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
