"""SQLite database operations for pipeline history tracking."""

import json
import logging
import sqlite3
import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Dict
from typing import List

from ai_tools_website.v1.data_manager import BUCKET_NAME
from ai_tools_website.v1.data_manager import get_minio_client

DB_FILE_KEY = "pipeline_history.db"

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline TEXT NOT NULL,           -- 'discovery', 'enhancement', 'maintenance'
    status TEXT NOT NULL,             -- 'success', 'error', 'timeout'
    started_at TEXT NOT NULL,         -- ISO timestamp
    finished_at TEXT,                 -- ISO timestamp
    duration_seconds REAL,            -- For performance tracking
    metrics TEXT,                     -- JSON blob (tools_updated, etc.)
    attributes TEXT,                  -- JSON blob (dry_run, force, etc.)
    error_type TEXT,                  -- Exception class name
    error_note TEXT,                  -- Human readable error
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def pipeline_db():
    """Download SQLite from MinIO, yield connection, upload back with proper binary handling."""

    # Create temporary file for SQLite operations
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)

        try:
            client = get_minio_client()

            # Try to download existing DB
            try:
                response = client.get_object(BUCKET_NAME, DB_FILE_KEY)
                tmp_file.write(response.read())
                tmp_file.flush()
                logger.debug("Downloaded existing pipeline database from MinIO")
            except Exception as e:
                logger.info(f"No existing database found, will create new one: {e}")

            # Open SQLite connection
            conn = sqlite3.connect(str(tmp_path))
            conn.row_factory = sqlite3.Row  # Enable dict-like access

            # Initialize schema if needed
            conn.execute(SCHEMA)
            conn.commit()

            # Yield connection for operations
            yield conn

            # Commit any pending transactions
            conn.commit()
            conn.close()

            # Upload updated database back to MinIO
            with open(tmp_path, "rb") as db_file:
                db_data = db_file.read()
                client.put_object(
                    BUCKET_NAME, DB_FILE_KEY, BytesIO(db_data), len(db_data), content_type="application/octet-stream"
                )
            logger.debug("Uploaded updated pipeline database to MinIO")

        finally:
            # Cleanup temporary file
            tmp_path.unlink(missing_ok=True)


def record_pipeline_run(pipeline: str, run_data: Dict) -> None:
    """Record a completed pipeline run in the database."""

    with pipeline_db() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_runs
            (pipeline, status, started_at, finished_at, duration_seconds,
             metrics, attributes, error_type, error_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                pipeline,
                run_data.get("status"),
                run_data.get("started_at"),
                run_data.get("finished_at"),
                run_data.get("duration_seconds"),
                json.dumps(run_data.get("metrics", {})),
                json.dumps(run_data.get("attributes", {})),
                run_data.get("error_type"),
                run_data.get("error_note"),
            ],
        )

    logger.info(f"Recorded pipeline run: {pipeline} - {run_data.get('status')}")


def get_latest_pipeline_status() -> List[Dict]:
    """Get the latest run status for each pipeline."""

    with pipeline_db() as conn:
        rows = conn.execute("""
            SELECT pipeline, status, started_at, finished_at, duration_seconds,
                   metrics, attributes, error_type, error_note, created_at
            FROM pipeline_runs
            WHERE id IN (
                SELECT MAX(id) FROM pipeline_runs GROUP BY pipeline
            )
            ORDER BY pipeline
        """).fetchall()

        # Convert to list of dicts and parse JSON fields
        results = []
        for row in rows:
            result = dict(row)
            # Parse JSON fields
            if result["metrics"]:
                result["metrics"] = json.loads(result["metrics"])
            if result["attributes"]:
                result["attributes"] = json.loads(result["attributes"])
            results.append(result)

        return results


def get_pipeline_history(pipeline: str = None, limit: int = 50) -> List[Dict]:
    """Get pipeline run history, optionally filtered by pipeline name."""

    with pipeline_db() as conn:
        if pipeline:
            rows = conn.execute(
                """
                SELECT * FROM pipeline_runs
                WHERE pipeline = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                [pipeline, limit],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM pipeline_runs
                ORDER BY created_at DESC
                LIMIT ?
            """,
                [limit],
            ).fetchall()

        # Convert to list of dicts and parse JSON fields
        results = []
        for row in rows:
            result = dict(row)
            # Parse JSON fields
            if result["metrics"]:
                result["metrics"] = json.loads(result["metrics"])
            if result["attributes"]:
                result["attributes"] = json.loads(result["attributes"])
            results.append(result)

        return results


def get_pipeline_stats() -> Dict:
    """Get basic statistics about pipeline runs."""

    with pipeline_db() as conn:
        stats = {}

        # Total runs per pipeline
        total_runs = conn.execute("""
            SELECT pipeline, COUNT(*) as count
            FROM pipeline_runs
            GROUP BY pipeline
        """).fetchall()
        stats["total_runs"] = {row["pipeline"]: row["count"] for row in total_runs}

        # Success rates
        success_rates = conn.execute("""
            SELECT pipeline,
                   AVG(CASE WHEN status = 'success' THEN 1.0 ELSE 0.0 END) as success_rate
            FROM pipeline_runs
            GROUP BY pipeline
        """).fetchall()
        stats["success_rates"] = {row["pipeline"]: row["success_rate"] for row in success_rates}

        # Average duration
        avg_durations = conn.execute("""
            SELECT pipeline, AVG(duration_seconds) as avg_duration
            FROM pipeline_runs
            WHERE duration_seconds IS NOT NULL
            GROUP BY pipeline
        """).fetchall()
        stats["avg_durations"] = {row["pipeline"]: row["avg_duration"] for row in avg_durations}

        return stats
