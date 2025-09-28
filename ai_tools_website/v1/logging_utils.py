"""Helpers for structured pipeline logging."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

from ai_tools_website.v1.pipeline_db import record_pipeline_run

SUMMARY_PREFIX = "PIPELINE_SUMMARY"


def _update_pipeline_status() -> None:
    """Record pipeline run in database after completion."""
    # This will be called from finalize() method with the pipeline data
    pass


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

        # Record pipeline run in database
        try:
            record_pipeline_run(self.pipeline, payload)
            logging.getLogger(__name__).debug(f"Recorded pipeline run in database: {self.pipeline}")
        except Exception as exc:
            # Don't let database failures break the pipeline
            logging.getLogger(__name__).warning(f"Failed to record pipeline run: {exc}")


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
