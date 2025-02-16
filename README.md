# AI Tools Website

A modern Python web application for aggregating and browsing AI tools. Built with FastHTML for the frontend and featuring AI-powered search capabilities.

### 🌐 Live at: [aitools.drose.io](https://aitools.drose.io)
[![Status](https://img.shields.io/uptimerobot/status/m798586414-bbbff2fcd214a94434a62dc7)](https://stats.uptimerobot.com/Jlo4zDIBm8)
[![Uptime](https://img.shields.io/uptimerobot/ratio/30/m798586414-bbbff2fcd214a94434a62dc7)](https://stats.uptimerobot.com/Jlo4zDIBm8)

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
.
├── ai_tools_website/        # Main application package
│   ├── __init__.py         # Package initializer
│   ├── config.py           # Application configuration
│   ├── data_manager.py     # Data processing and validation
│   ├── logging_config.py   # Logging configuration
│   ├── search.py           # AI-powered search implementation
│   ├── storage.py          # Storage interfaces (local/Minio)
│   ├── web.py             # FastHTML web server
│   ├── utils/             # Utility functions
│   └── static/            # Client-side assets
│
├── scripts/                # Automation scripts
│   ├── crontab            # Scheduled task configuration
│   └── run-update.sh      # Tool update script
│
├── data/                  # Data storage directory
├── logs/                  # Application logs
│
├── docker-compose.yml     # Docker Compose configuration
├── Dockerfile            # Web service container
├── Dockerfile.updater    # Update service container
├── pyproject.toml        # Python project configuration
└── uv.lock              # UV dependency lock file
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

## Technical Details

### AI-Powered Tool Discovery
The system uses a multi-stage pipeline for discovering and validating AI tools:

1. **Search Integration**
   - Uses Tavily API for initial tool discovery
   - Focuses on high-quality domains (github.com, producthunt.com, huggingface.co, replicate.com)
   - Implements caching in development mode for faster iteration

2. **Validation Pipeline**
   - Multi-stage verification using LLMs:
     - Initial filtering of search results (confidence threshold: 80%)
     - Page content analysis and verification (confidence threshold: 90%)
     - Category assignment based on existing tool context
   - URL validation to filter out listing/search pages
   - Async processing for improved performance

3. **Deduplication System**
   - Two-pass deduplication:
     - Quick URL-based matching
     - LLM-based semantic comparison for similar tools
   - Confidence-based decision making for updates vs. new entries
   - Smart merging of tool information when duplicates found

4. **Data Models**
   - `ToolUpdate`: Tracks tool verification decisions
   - `SearchAnalysis`: Manages search result analysis
   - `DuplicateStatus`: Handles deduplication decisions
   - Strong typing with Pydantic for data validation

5. **Categorization**
   - Dynamic category management
   - LLM-powered category suggestions
   - Supported categories:
     - Language Models
     - Image Generation
     - Audio & Speech
     - Video Generation
     - Developer Tools
     - Other

### Background Update Process
The updater service (`Dockerfile.updater`) implements:
1. Scheduled tool discovery using supercronic
2. Automatic deduplication of new entries
3. Health monitoring of the update process
4. Configurable update frequency via crontab

### Storage Implementation
The system implements a flexible storage system:

1. **Minio Integration**
   - S3-compatible object storage
   - Automatic bucket creation and management
   - LRU caching for improved read performance
   - Graceful handling of initialization (empty data)
   - Content-type aware storage (application/json)

2. **Data Format**
   - JSON-based storage for flexibility
   - Schema:
     ```json
     {
       "tools": [
         {
           "name": "string",
           "description": "string",
           "url": "string",
           "category": "string"
         }
       ],
       "last_updated": "string"
     }
     ```
   - Atomic updates with cache invalidation
   - Error handling for storage operations

3. **Development Features**
   - Local filesystem fallback
   - Development mode caching
   - Configurable secure/insecure connections
   - Comprehensive logging of storage operations

### Web Implementation
The frontend is built with FastHTML for efficient server-side rendering:

1. **Architecture**
   - Server-side rendering with FastHTML components
   - Async request handling with uvicorn
   - In-memory caching with background refresh
   - Health check endpoint for monitoring

2. **UI Components**
   - Responsive grid layout for tool cards
   - Real-time client-side search filtering
   - Category-based organization
   - Dynamic tool count display
   - GitHub integration corner

3. **Performance Features**
   - Background cache refresh mechanism
   - Efficient DOM updates via client-side JS
   - Static asset serving (CSS, JS, images)
   - Optimized search with data attributes

4. **Development Mode**
   - Hot reload support
   - Configurable port via environment
   - Static file watching
   - Detailed request logging

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

The application uses environment variables for configuration. Copy `.env.example` to `.env` and configure the following:

### Core Settings
- `WEB_PORT`: Web server port (default: 8000)
- `DEV_MODE`: Enable development mode with caching (default: false)
- `LOG_LEVEL`: Logging verbosity (default: INFO)

### AI Service Integration
- `OPENAI_API_KEY`: OpenAI API key for enhanced search
- `TAVILY_API_KEY`: Tavily API key for additional search features
- `MODEL_NAME`: OpenAI model to use (default: "gpt-4-turbo-preview")
- `LANGCHAIN_API_KEY`: Optional LangChain integration
- `LANGCHAIN_TRACING_V2`: Enable LangChain tracing (default: false)
- `LANGCHAIN_PROJECT`: LangChain project name

### Storage Configuration
- `TOOLS_FILE`: Path to tools data file (default: "data/tools.json")

#### Minio Storage (optional)
If using Minio for storage, configure:
- `MINIO_ENDPOINT`: Minio server endpoint
- `MINIO_ACCESS_KEY`: Minio access key
- `MINIO_SECRET_KEY`: Minio secret key
- `MINIO_BUCKET_NAME`: Bucket name for tool storage

See `.env.example` for a template with default values.

## Recent Improvements

- Refactored the codebase to separate concerns:
  - data_manager.py now handles data processing and validation.
  - search.py is refactored for clarity and integration with AI services.
  - Improved logging configuration in logging_config.py.
  - Enhanced storage interface in storage.py to support multiple backends.
- Adopted UV for dependency management and task execution best practices.

## Deployment

The application is containerized using Docker with two services:

1. **Web Service**
   - Serves the main web application
   - Built from `Dockerfile`
   - Exposes the configured web port
   - Includes health checks for reliability

2. **Updater Service**
   - Runs scheduled tool updates using supercronic
   - Built from `Dockerfile.updater`
   - Automatically keeps tool data fresh
   - Includes health monitoring

To deploy using Docker Compose:

```bash
# Build and start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop services
docker compose down
```

Make sure to configure your `.env` file before deployment. See Configuration section above for required variables.

## License

This project is licensed under the [Apache License 2.0](LICENSE).