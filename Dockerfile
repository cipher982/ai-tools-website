FROM python:3.12-slim

WORKDIR /app

# Install UV for better package management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync

# Copy application code
COPY ai_tools_website /app/ai_tools_website/

# Create data directory
RUN mkdir -p ./data

# Use shell form to allow environment variable expansion
CMD uv run uvicorn "ai_tools_website.web:app" --host "0.0.0.0" --port "$WEB_PORT" 