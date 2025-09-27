"""Helpers for structured pipeline logging."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Optional

SUMMARY_PREFIX = "PIPELINE_SUMMARY"


def _update_pipeline_status() -> None:
    """Update the pipeline status snapshot after a pipeline run completes."""
    try:
        # Use Path to ensure we're working from the project root
        project_root = Path(__file__).parent.parent.parent
        script_path = project_root / "scripts" / "build_pipeline_status.py"

        if not script_path.exists():
            logging.getLogger(__name__).warning(f"Pipeline status script not found at {script_path}")
            return

        # Run the script to update the status snapshot
        result = subprocess.run(
            ["python3", str(script_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logging.getLogger(__name__).error(f"Pipeline status update failed: {result.stderr}")
        else:
            logging.getLogger(__name__).debug("Pipeline status snapshot updated successfully")

    except Exception as exc:
        # Don't let status update failures break the pipeline
        logging.getLogger(__name__).warning(f"Failed to update pipeline status: {exc}")


@dataclass
class _PipelineSummaryState:
    pipeline: str
    logger: logging.Logger
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    start_monotonic: float = field(default_factory=time.perf_counter)
    status: str = "success"
    attributes: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    error_type: Optional[str] = None
    error_note: Optional[str] = None

    def add_metric(self, name: str, value: Optional[float]) -> None:
        """Record a numeric metric if a value is provided."""
        if value is None:
            return
        numeric: Optional[float]
        if isinstance(value, bool):  # treat bools as integers
            numeric = int(value)
        elif isinstance(value, (int, float)):
            numeric = value
        else:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return

        if isinstance(numeric, float) and numeric.is_integer():
            numeric = int(numeric)
        self.metrics[name] = numeric

    def add_attribute(self, name: str, value: Any) -> None:
        """Attach non-sensitive metadata (sanitized before logging)."""
        if value is None:
            return
        if isinstance(value, (str, int, float, bool)):
            self.attributes[name] = value
        else:
            self.attributes[name] = str(value)

    def mark_failed(self, *, error_type: Optional[str] = None, note: Optional[str] = None) -> None:
        self.status = "error"
        if error_type:
            self.error_type = error_type
        if note:
            self.error_note = note

    def finalize(self) -> None:
        finished_at = datetime.now(timezone.utc)
        duration = max(0.0, time.perf_counter() - self.start_monotonic)
        payload: Dict[str, Any] = {
            "pipeline": self.pipeline,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round(duration, 3),
        }
        if self.attributes:
            payload["attributes"] = self.attributes
        if self.metrics:
            payload["metrics"] = self.metrics
        if self.error_type:
            payload["error_type"] = self.error_type
        if self.error_note:
            payload["error_note"] = self.error_note

        message = f"{SUMMARY_PREFIX} {json.dumps(payload, sort_keys=True)}"
        self.logger.info(message)

        # Trigger pipeline status update after logging
        _update_pipeline_status()


@contextmanager
def pipeline_summary(pipeline: str, *, logger_name: Optional[str] = None) -> _PipelineSummaryState:
    """Context manager that logs a structured summary for a pipeline run."""

    logger = logging.getLogger(logger_name or f"pipeline_summary.{pipeline}")
    state = _PipelineSummaryState(pipeline=pipeline, logger=logger)
    try:
        yield state
    except Exception as exc:  # noqa: BLE001
        state.mark_failed(error_type=exc.__class__.__name__)
        state.finalize()
        raise
    else:
        state.finalize()
