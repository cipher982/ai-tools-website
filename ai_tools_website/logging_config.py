"""Logging configuration for the AI tools website."""

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration."""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Configure logging format
    formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")

    # File handler for all logs
    file_handler = logging.FileHandler(log_dir / "ai_tools.log")
    file_handler.setFormatter(formatter)

    # Stream handler for INFO and above
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
