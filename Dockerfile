FROM python:3.12-slim

WORKDIR /app

# Install UV for better package management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync

# Copy application code
COPY src/ ./src/

# Create data directory
RUN mkdir -p ./data

CMD ["uv", "run", "python", "src/ai_tools_website/web.py"] 