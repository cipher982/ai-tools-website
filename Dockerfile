FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install UV for better package management
RUN pip install uv

# Copy all necessary files for package installation
COPY pyproject.toml uv.lock ./
COPY ai_tools_website ./ai_tools_website/

# Install dependencies
RUN uv sync

# Use shell form to allow environment variable expansion
CMD uv run uvicorn "ai_tools_website.web:app" --host "0.0.0.0" --port "$WEB_PORT" 