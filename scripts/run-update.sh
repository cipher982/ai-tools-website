#!/bin/sh
set -e

echo "[$(date -u)] Starting tools database update..."
if uv run python -m ai_tools_website.v1.search; then
    echo "[$(date -u)] Initial tool update completed, starting automatic recategorization..."

    # Automatically reorganize categories using the maintenance task.
    if uv run python -m ai_tools_website.v1.maintenance recategorize -y; then
        echo "[$(date -u)] Recategorization finished successfully"
        echo "[$(date -u)] Update workflow completed successfully"
    else
        echo "[$(date -u)] Recategorization failed with exit code $?"
        exit 1
    fi
else
    echo "[$(date -u)] Tool update failed with exit code $?"
    exit 1
fi 