#!/bin/sh
set -e

echo "[$(date -u)] Starting tools database update..."
if uv run python -m ai_tools_website.search; then
    echo "[$(date -u)] Update completed successfully"
else
    echo "[$(date -u)] Update failed with exit code $?"
    exit 1
fi 