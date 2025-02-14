# AI Tools Website

A modern Python web application for aggregating and browsing AI tools. Built with FastHTML for the frontend and featuring AI-powered search capabilities.

**🌐 Live at: [aitools.drose.io](https://aitools.drose.io)**

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-312/)
[![FastHTML](https://img.shields.io/badge/frontend-FastHTML-orange.svg)](https://github.com/davidrose/fasthtml)
[![OpenAI](https://img.shields.io/badge/AI-OpenAI-green.svg)](https://openai.com/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![UV](https://img.shields.io/badge/package%20manager-uv-4A4A4A.svg)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

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

Visit `https://aitools.drose.io` or `http://localhost:8000` (for local development) in your browser.

## Configuration

Key environment variables:
- `WEB_PORT`: Web server port (default: 8000)
- `OPENAI_API_KEY`: For enhanced search capabilities
- `TAVILY_API_KEY`: For additional search features
- `MODEL_NAME`: OpenAI model to use (default: "gpt-4o-mini")
- `DEV_MODE`: Enable development mode with caching (default: false)

Minio Storage Configuration:
- `MINIO_ENDPOINT`: Minio server endpoint
- `MINIO_ACCESS_KEY`: Minio access key
- `MINIO_SECRET_KEY`: Minio secret key  
- `MINIO_BUCKET_NAME`: Bucket name for tool storage

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