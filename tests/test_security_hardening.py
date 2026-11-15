"""Security hardening tests for ai_tools_website."""

import os

os.environ.setdefault("BASE_PATH", "/aitools")

import asyncio  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from io import BytesIO  # noqa: E402
from pathlib import Path  # noqa: E402

from minio.error import S3Error  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_tools_website.v1 import pipeline_db as pipeline_db_module  # noqa: E402
from ai_tools_website.v1 import web as web_module  # noqa: E402
from ai_tools_website.v1.public_catalog import build_public_tool_record  # noqa: E402
from ai_tools_website.v1.public_catalog import canonicalize_url  # noqa: E402


def _make_sqlite_bytes() -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
    try:
        conn = sqlite3.connect(str(tmp_path))
        conn.execute(pipeline_db_module.SCHEMA)
        conn.execute(
            """
            INSERT INTO pipeline_runs (pipeline, status, started_at, duration_seconds, metrics)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("maintenance", "success", "2026-08-01T12:00:00+00:00", 1.5, "{}"),
        )
        conn.commit()
        conn.close()
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


class _FakeMinIOResponse:
    def __init__(self, data: bytes):
        self._buf = BytesIO(data)
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self._buf.read()

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


def test_pipeline_db_readonly_does_not_upload_and_closes_response(monkeypatch):
    db_bytes = _make_sqlite_bytes()
    fake_response = _FakeMinIOResponse(db_bytes)
    put_calls = []

    class _FakeClient:
        def get_object(self, bucket, key):
            return fake_response

        def put_object(self, *args, **kwargs):
            put_calls.append((args, kwargs))

    monkeypatch.setattr(pipeline_db_module, "get_minio_client", lambda: _FakeClient())

    with pipeline_db_module.pipeline_db() as conn:
        rows = conn.execute("SELECT pipeline, status FROM pipeline_runs").fetchall()
        assert len(rows) == 1
        assert rows[0]["pipeline"] == "maintenance"

    assert fake_response.closed is True
    assert fake_response.released is True
    assert put_calls == []


def test_pipeline_status_route_never_uploads_db(monkeypatch):
    db_bytes = _make_sqlite_bytes()
    fake_response = _FakeMinIOResponse(db_bytes)
    put_calls = []

    class _FakeClient:
        def get_object(self, bucket, key):
            return fake_response

        def put_object(self, *args, **kwargs):
            put_calls.append((args, kwargs))

    monkeypatch.setattr(web_module, "_pipeline_status_cache", None)
    monkeypatch.setattr(web_module, "_pipeline_status_cache_at", None)
    monkeypatch.setattr(pipeline_db_module, "get_minio_client", lambda: _FakeClient())

    client = TestClient(web_module.app, raise_server_exceptions=False)
    resp = client.get("/pipeline-status")
    assert resp.status_code == 200
    assert fake_response.closed is True
    assert fake_response.released is True
    assert put_calls == []


def test_pipeline_db_transient_error_never_overwrites_minio(monkeypatch):
    put_calls = []

    class _ErrorClient:
        def get_object(self, bucket, key):
            raise S3Error(
                "InternalError",
                "transient backend error",
                "/aitools/pipeline_history.db",
                "req-1",
                "host-1",
                None,
            )

        def put_object(self, *args, **kwargs):
            put_calls.append((args, kwargs))

    monkeypatch.setattr(pipeline_db_module, "get_minio_client", lambda: _ErrorClient())

    # Readonly read degrades to an empty local DB without writing to MinIO.
    with pipeline_db_module.pipeline_db(readonly=True) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()
        assert rows[0] == 0
    assert put_calls == []

    # Read-write mode refuses to proceed so MinIO cannot be overwritten with an empty DB.
    raised = False
    try:
        with pipeline_db_module.pipeline_db(readonly=False):
            pass
    except S3Error:
        raised = True
    assert raised is True
    assert put_calls == []


def test_pipeline_db_nosuchkey_readwrite_creates_and_uploads(monkeypatch):
    uploaded = []

    class _MissingClient:
        def get_object(self, bucket, key):
            raise S3Error(
                "NoSuchKey",
                "Object does not exist",
                "/aitools/pipeline_history.db",
                "req-2",
                "host-2",
                None,
            )

        def put_object(self, bucket, key, stream, length, **kwargs):
            uploaded.append((bucket, key, len(stream.read()), length))

    monkeypatch.setattr(pipeline_db_module, "get_minio_client", lambda: _MissingClient())

    pipeline_db_module.record_pipeline_run(
        "maintenance",
        {"status": "success", "started_at": "2026-08-01T12:00:00+00:00", "duration_seconds": 2.0},
    )
    assert len(uploaded) == 1
    assert uploaded[0][1] == pipeline_db_module.DB_FILE_KEY
    assert uploaded[0][2] > 0


def test_build_enhanced_pipeline_data_cached_60s(monkeypatch):
    monkeypatch.setattr(web_module, "_pipeline_status_cache", None)
    monkeypatch.setattr(web_module, "_pipeline_status_cache_at", None)

    calls = 0
    now = 1000.0

    def fake_latest():
        nonlocal calls
        calls += 1
        return [
            {
                "pipeline": "discovery",
                "status": "success",
                "started_at": "2026-08-01T12:00:00+00:00",
                "finished_at": "2026-08-01T12:00:01+00:00",
                "duration_seconds": 1.0,
                "metrics": {},
            }
        ]

    monkeypatch.setattr(web_module, "get_latest_pipeline_status", fake_latest)
    monkeypatch.setattr(web_module, "get_cron_schedules", lambda: {})
    monkeypatch.setattr(
        web_module,
        "calculate_health_score",
        lambda _p, days=7: {"score": 100, "status": "healthy", "durations": [1.0]},
    )
    monkeypatch.setattr(web_module, "generate_insights", lambda _p, _h: ["OK"])
    monkeypatch.setattr(web_module, "get_contextual_summary", lambda _p, days=1: "Healthy")
    monkeypatch.setattr(web_module.time, "monotonic", lambda: now)

    first = web_module._build_enhanced_pipeline_data()
    assert calls == 1
    first[0]["status"] = "mutated"

    now = 1030.0
    second = web_module._build_enhanced_pipeline_data()
    assert calls == 1
    assert second[0]["status"] == "success"

    now = 1061.0
    web_module._build_enhanced_pipeline_data()
    assert calls == 2


def test_refresh_tools_background_ttl_lock_and_thread(monkeypatch):
    monkeypatch.setattr(web_module, "tools_cache", {})
    monkeypatch.setattr(web_module, "_tools_refresh_at", None)
    monkeypatch.setattr(web_module, "_tools_refresh_lock", None)
    monkeypatch.setattr(web_module, "_tools_refresh_lock_loop", None)

    calls = 0
    caller_thread_id = threading.get_ident()
    observed_threads = []
    now = 2000.0

    def fake_load_tools():
        nonlocal calls
        calls += 1
        observed_threads.append(threading.get_ident())
        time.sleep(0.02)
        return {
            "tools": [
                {
                    "name": "Alpha Tool",
                    "url": "https://alpha.example.com",
                    "description": "Test tool",
                    "category": "Developer Tools",
                }
            ]
        }

    monkeypatch.setattr(web_module, "load_tools", fake_load_tools)
    monkeypatch.setattr(web_module.time, "monotonic", lambda: now)

    async def _run_concurrent():
        await asyncio.gather(
            web_module.refresh_tools_background(),
            web_module.refresh_tools_background(),
        )
        # Subsequent call within 300s TTL must skip reload.
        monkeypatch.setattr(web_module.time, "monotonic", lambda: 2100.0)
        await web_module.refresh_tools_background()

    asyncio.run(_run_concurrent())
    assert calls == 1
    assert len(observed_threads) == 1
    assert observed_threads[0] != caller_thread_id

    # After 300s TTL expires, refresh runs again.
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 2305.0)
    asyncio.run(web_module.refresh_tools_background())
    assert calls == 2


def test_canonicalize_url_http_https_only():
    assert canonicalize_url("https://Example.COM/path/") == "https://example.com/path"
    assert canonicalize_url("http://example.com/") == "http://example.com"
    assert canonicalize_url("javascript:alert(1)") == ""
    assert canonicalize_url("data:text/html,<script>alert(1)</script>") == ""
    assert canonicalize_url("ftp://example.com/archive.tar.gz") == ""
    assert canonicalize_url("//evil.example.com/path") == ""
    assert canonicalize_url("/relative/path") == ""


def test_external_links_noopener_and_json_ld_escaping(monkeypatch):
    monkeypatch.setattr(web_module, "tools_cache", {})
    monkeypatch.setattr(web_module, "_tools_refresh_at", None)
    monkeypatch.setattr(
        web_module,
        "load_tools",
        lambda: {
            "tools": [
                {
                    "name": "Evil </script><script>alert(1)</script>",
                    "slug": "evil-tool",
                    "url": "https://example.com/tool",
                    "source_url": "https://github.com/org/evil-tool",
                    "description": "Checks JSON-LD escaping </script>",
                    "category": "Developer Tools",
                    "editorial": {
                        "public": True,
                        "index": True,
                        "summary": "Safe summary.",
                        "what_it_is": "Safe detail.",
                    },
                }
            ]
        },
    )

    client = TestClient(web_module.app, raise_server_exceptions=False)
    detail_resp = client.get("/tools/evil-tool")
    assert detail_resp.status_code == 200
    assert 'rel="noopener noreferrer"' in detail_resp.text
    assert "</script><script>" not in detail_resp.text
    assert r"\u003c/script>" in detail_resp.text

    record = build_public_tool_record(
        {
            "name": "Card Tool",
            "url": "https://example.org",
            "description": "External card",
            "category": "Developer Tools",
        }
    )
    card_html = web_module.to_xml(web_module.tool_card_external(record))
    assert 'target="_blank"' in card_html
    assert 'rel="noopener noreferrer"' in card_html


def test_trailing_slash_middleware_relative_redirect(monkeypatch):
    monkeypatch.setattr(web_module, "tools_cache", {})
    monkeypatch.setattr(web_module, "load_tools", lambda: {"tools": []})
    client = TestClient(web_module.app, raise_server_exceptions=False)

    resp = client.get("/tools/chatgpt/?q=1", headers={"Host": "evil.example"}, follow_redirects=False)
    assert resp.status_code == 308
    location = resp.headers["location"]
    assert not location.startswith("http")
    assert not location.startswith("//")
    assert "evil.example" not in location
    assert location == "/aitools/tools/chatgpt?q=1"

    evil_slash = client.get(
        "http://testserver//evil.example/", headers={"Host": "evil.example"}, follow_redirects=False
    )
    assert evil_slash.status_code == 308
    assert evil_slash.headers["location"] == "/aitools/evil.example"
