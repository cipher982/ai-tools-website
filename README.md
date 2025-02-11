# AI Tools Website

A modern Python web application for aggregating and browsing AI tools. Built with FastHTML for the frontend and featuring AI-powered search capabilities.

## Overview

The AI Tools Website aggregates various AI tools and presents them in a responsive, searchable interface. Key features include:

- **Modern Tech Stack:**
  - FastHTML for server-side rendering
  - OpenAI and Tavily integration for enhanced search
  - Minio S3-compatible storage
  - UV for Python dependency management

- **Web Interface:**
  - Real-time client-side search
  - Responsive grid layout
  - Category-based organization
  - Clean, modern design

## Project Structure

```
ai_tools_website/
├── __init__.py
├── config.py              # Configuration settings
├── data_manager.py        # Data processing and validation
├── logging_config.py      # Logging setup
├── search.py             # AI-powered search implementation
├── storage.py            # Storage interface (Minio/local)
├── web.py               # FastHTML web server
└── static/              # CSS and client-side JS
```

## How It Works

1. **Web Interface:**
   - FastHTML server (`web.py`) provides a modern, responsive UI
   - Client-side search for instant filtering
   - Category-based organization of tools

2. **Data Management:**
   - AI-powered search aggregates tool data
   - Flexible storage backend (local or Minio)
   - Automatic categorization and deduplication

3. **Development:**
   - UV manages dependencies for consistent environments
   - Environment variables for easy configuration
   - Comprehensive logging for debugging

## Quick Start

```bash
# Install UV if you haven't already
pip install uv

# Install dependencies
uv sync

# Set up environment variables (copy from .env.example)
cp .env.example .env

# Run the web server
uv run python -m ai_tools_website.web

# In a separate terminal, run the updater
uv run python -m ai_tools_website.search
```

Visit `http://localhost:8000` (or configured port) in your browser.

## Configuration

Key environment variables:
- `WEB_PORT`: Web server port (default: 8000)
- `OPENAI_API_KEY`: For enhanced search capabilities
- `TAVILY_API_KEY`: For additional search features
- `STORAGE_TYPE`: "local" or "minio"

See `.env.example` for all options.

## Future Improvements

- **Enhanced Search:** Implement more AI-powered search features
- **Content Filtering:** Improve result relevance and filtering
- **Admin Interface:** Add tool management UI
- **API:** RESTful endpoints for programmatic access
- **Analytics:** Track popular searches and tools

## Deployment

A Docker-based deployment configuration is available in the `docker/` directory for reference.

## License

This project is licensed under the [Apache License 2.0](LICENSE).