"""Storage helpers for MinIO vs local file workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _backend() -> str:
    return os.getenv("AITOOLS_STORAGE_BACKEND", "minio").lower()


def use_local_storage() -> bool:
    return _backend() == "local"


def _local_data_dir() -> Path:
    base = Path(os.getenv("AITOOLS_LOCAL_DATA_DIR", "dev_cache"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def local_tools_path() -> Path:
    tools_file = os.getenv("TOOLS_FILE")
    if tools_file:
        return Path(tools_file)
    return _local_data_dir() / "tools.json"


def local_slug_registry_path() -> Path:
    registry_file = os.getenv("AITOOLS_SLUG_REGISTRY_FILE")
    if registry_file:
        return Path(registry_file)
    return _local_data_dir() / "slug_registry.json"


def local_comparison_opportunities_path(filename: str) -> Path:
    return _local_data_dir() / filename


def read_local_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return json.loads(json.dumps(default))
    return json.loads(path.read_text())


def write_local_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
