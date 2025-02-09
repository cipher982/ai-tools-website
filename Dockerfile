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

# Create directories
RUN mkdir -p ./data ./static

# Copy static files
COPY src/ai_tools_website/static/* ./static/

CMD ["uv", "run", "python", "src/ai_tools_website/web.py"] 