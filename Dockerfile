FROM python:3.12-slim

WORKDIR /app

# Install UV for better package management
RUN pip install uv

# Copy all necessary files for package installation
COPY pyproject.toml uv.lock ./
COPY ai_tools_website ./ai_tools_website/

# Install dependencies and the package itself
RUN uv sync && \
    uv pip install -e .

# Create data directory
RUN mkdir -p ./data

# Use shell form to allow environment variable expansion
CMD echo "=== Directory Structure ===" && \
    ls -la /app && \
    echo "=== Python Path ===" && \
    python -c "import sys; print('\n'.join(sys.path))" && \
    echo "=== Starting App ===" && \
    uv run uvicorn "ai_tools_website.web:app" --host "0.0.0.0" --port "$WEB_PORT" 