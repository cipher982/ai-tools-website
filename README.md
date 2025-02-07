# AI Tools Website

A modern Python web application for aggregating and browsing AI tools. This refactored project demonstrates a modular design using FastHTML, with a clear separation of concerns for data ingestion, web serving, and logging.

## Overview

The AI Tools Website aggregates various AI tools and presents them in a responsive, searchable interface. Key improvements include:

- **Modular Architecture:**
  - Reorganized code in the `src/ai_tools_website` directory.
  - Dedicated modules for configuration (`config.py`), data handling (`data_manager.py`), search (`search.py`), and logging setup (`logging_config.py`).

- **Data Ingestion & Search:**
  - Uses the `duckduckgo-search` library to query DuckDuckGo with multiple search phrases.
  - Processes search results by filtering incomplete entries, deduplicating via tool URL, and categorizing tools.
  - Stores curated tool data in JSON format under the `data/` directory.

- **Web Interface:**
  - Built with FastHTML for dynamic HTML generation.
  - Features a responsive grid layout with real-time client-side search.
  - Clean design supported by custom CSS.

- **Logging & Monitoring:**
  - Comprehensive logging using Python's `logging` module.
  - Logs output to both file and console for improved debugging and monitoring.

## Project Structure

```
ai-tools-website/
├── data/
│   └── tools.json          # JSON datastore for AI tools
├── src/ai_tools_website/
│   ├── __init__.py
│   ├── config.py          # Configuration settings
│   ├── data_manager.py    # Data ingestion and persistence utilities
│   ├── logging_config.py  # Logging setup
│   ├── search.py          # Refactored DuckDuckGo search implementation
│   ├── update_page.py     # Script to update tool data via search
│   └── web.py             # FastHTML-based web server & UI components
├── pyproject.toml         # Dependency & build configuration
├── .gitignore             # Files and directories to ignore in Git
└── README.md              # Project documentation
```

## How It Works

1. **Data Management:**
   - The update script (`update_page.py`) runs queries via `search.py`.
   - Processed results (filtered, deduplicated, categorized) are persisted using `data_manager.py` into `data/tools.json`.

2. **Web Application:**
   - The FastHTML web server in `web.py` dynamically renders a modern UI.
   - Client-side JavaScript handles real-time search and filtering.

3. **Configuration & Logging:**
   - Centralized settings in `config.py` simplify configuration management.
   - Logging is configured in `logging_config.py` to output logs both to file and the console.

## Running the Project

Install dependencies and start the development server using UV:

```bash
# Install dependencies
# optional: `pip install uv` first
uv sync

# Run the web server
uv run python -m ai_tools_website.web

# Update the tools database (in a separate terminal)
uv run python -m ai_tools_website.update_page
```

## Deployment

To deploy the application as a standard Python web application, consider:
- Using Gunicorn/Uvicorn for production WSGI/ASGI serving.
- Configuring Nginx as a reverse proxy.
- Managing processes with Systemd.
- Scheduling regular updates (via `update_page.py`) with Cron.

## Future Improvements

- **Enhanced Categorization:** Implement LLM-based techniques for more accurate tool grouping.
- **Content Filtering:** Improve search result relevance and filtering strategies.
- **Admin Interface:** Develop secured routes for managing tool entries.
- **API Endpoints:** Expose tool data through a RESTful API.
- **Search Analytics:** Track popular searches to enhance tool discovery.

## License

This project is licensed under the [Apache License 2.0](LICENSE).