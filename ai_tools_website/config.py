"""Project configuration and paths."""

from pathlib import Path

# Project structure
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TOOLS_FILE = DATA_DIR / "tools.json"
