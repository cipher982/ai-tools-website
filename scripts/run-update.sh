#!/bin/sh
set -e

echo "Starting tools database update..."
uv run python -m ai_tools_website.update_page
echo "Update completed successfully" 