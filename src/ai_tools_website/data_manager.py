"""Data management functionality for AI tools."""

import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


def load_tools() -> Dict:
    """Load tools data from JSON file."""
    data_path = Path("data/tools.json")
    if not data_path.exists():
        logger.error(f"Data file not found at {data_path}")
        raise FileNotFoundError(f"Data file not found at {data_path}")

    with open(data_path, "r") as f:
        return json.load(f)


def save_tools(tools_data: Dict) -> None:
    """Save tools data to JSON file."""
    data_path = Path("data/tools.json")
    with open(data_path, "w") as f:
        json.dump(tools_data, f, indent=4)
    logger.info(f"Saved {len(tools_data['tools'])} tools to {data_path}")
