# AI Tools Website

A modern Python web application for aggregating and browsing AI tools. Built with FastHTML for the frontend and featuring AI-powered search capabilities.

## Overview

The AI Tools Website aggregates various AI tools and presents them in a responsive, searchable interface. Recent refactoring has separated core functionalities into distinct modules—web, search, logging, data management, and storage—to better organize and scale the application.

## Key Features

- **Modular Architecture:** Separation of concerns across data processing, logging, search, and storage.
- **Modern Tech Stack:** Built with FastHTML for server-side rendering.
- **Enhanced Search:** AI-powered search with support for OpenAI and Tavily integrations.
- **Flexible Storage:** Supports both local storage and Minio S3-compatible storage.
- **Robust Logging:** Improved logging configuration for easier debugging and monitoring.
- **Efficient Dependency Management:** UV used for dependency synchronization and task execution.

## Project Structure

```
ai_tools_website/
├── __init__.py          # Package initializer
├── config.py            # Application configuration settings
├── data_manager.py      # Data processing and validation
├── logging_config.py    # Logging configuration
├── search.py            # AI-powered search implementation
├── storage.py           # Storage interfaces (local/Minio)
├── web.py               # FastHTML web server
└── static/              # Client-side assets (CSS, JS, images)
```

## How It Works

1. **Web Interface:** 
   - The FastHTML server (web.py) renders a responsive UI with real-time client-side search.
2. **Data Management & Search:** 
   - Data is processed and validated in data_manager.py.
   - search.py leverages AI integrations to provide enhanced search functionality.
3. **Storage & Logging:** 
   - storage.py handles file storage, supporting local and Minio backends.
   - logging_config.py sets up comprehensive logging for monitoring and debugging.

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

# Run background search/updater
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

## Recent Improvements

- Refactored the codebase to separate concerns:
  - data_manager.py now handles data processing and validation.
  - search.py is refactored for clarity and integration with AI services.
  - Improved logging configuration in logging_config.py.
  - Enhanced storage interface in storage.py to support multiple backends.
- Adopted UV for dependency management and task execution best practices.

## Deployment

A Docker-based deployment configuration is available in the `docker/` directory for reference.

## License

This project is licensed under the [Apache License 2.0](LICENSE).