#!/bin/sh
set -e

# Configuration with environment variable defaults
DETECTOR_MAX_COMPARISONS=${COMPARISON_DETECTOR_MAX_COMPARISONS:-50}
DETECTOR_STALE_DAYS=${COMPARISON_DETECTOR_STALE_DAYS:-30}
GENERATOR_MAX_PER_RUN=${COMPARISON_GENERATOR_MAX_PER_RUN:-10}
GENERATOR_STALE_DAYS=${COMPARISON_GENERATOR_STALE_DAYS:-7}

echo "[$(date -u)] Starting comparison pipeline..."

# Step 1: Detect comparison opportunities
echo "[$(date -u)] Step 1: Detecting comparison opportunities..."
if uv run python -m ai_tools_website.v1.comparison_detector \
    --max-comparisons "$DETECTOR_MAX_COMPARISONS" \
    --stale-days "$DETECTOR_STALE_DAYS"; then
    echo "[$(date -u)] Comparison detection completed successfully"
else
    echo "[$(date -u)] Comparison detection failed with exit code $?"
    exit 1
fi

# Step 2: Generate comparison content
echo "[$(date -u)] Step 2: Generating comparison content..."
if uv run python -m ai_tools_website.v1.comparison_generator \
    --max-per-run "$GENERATOR_MAX_PER_RUN" \
    --stale-days "$GENERATOR_STALE_DAYS"; then
    echo "[$(date -u)] Comparison generation completed successfully"
    echo "[$(date -u)] Comparison pipeline finished successfully"
else
    echo "[$(date -u)] Comparison generation failed with exit code $?"
    exit 1
fi