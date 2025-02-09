FROM python:3.12-slim

WORKDIR /app

# Install UV for better package management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync

# Copy and install application code
COPY src/ai_tools_website /app/ai_tools_website
RUN uv pip install -e .

# Create data directory
RUN mkdir -p ./data

CMD ["uv", "run", "python", "ai_tools_website/web.py"] 