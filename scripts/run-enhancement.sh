#!/bin/sh
set -e

# Configuration (overridable by ENV)
MAX_PER_RUN=${CONTENT_ENHANCER_MAX_PER_RUN:-50}
TARGET_TIER=${CONTENT_ENHANCER_TIER:-"all"}

echo "[$(date -u)] Starting content enhancement (max: $MAX_PER_RUN, tier: $TARGET_TIER)..."

uv run python -m ai_tools_website.v1.content_enhancer_v2 \
    --max-per-run "$MAX_PER_RUN" \
    --tier "$TARGET_TIER"

echo "[$(date -u)] Content enhancement finished"
