# ai-tools-website

A collection of AI tools aggregated and displayed on a static website. This project serves as both a directory of AI tools and an example of modern, modular Python development using a static site generator approach.

## Overview

This project periodically searches for new AI tools on the web via DuckDuckGo and updates a static HTML page. The key components include:

- **Data Ingestion & Search:**
  - Uses the `duckduckgo-search` library to query DuckDuckGo with multiple search phrases.
  - Processes the search results by filtering out incomplete data, deduplicating based on tool URL, and categorizing each tool based on keywords in its title.

- **Static HTML Generation:**
  - Uses Jinja2 templates to generate a responsive HTML page (with Pico CSS).
  - Tools are grouped by category, and the page displays a "last updated" timestamp.

- **Logging & Monitoring:**
  - Structured logging is implemented using Python's `logging` module via a dedicated `logging_config.py`.
  - Logs are output both to a file (in the `logs` directory) and the console for easier debugging.

- **Deployment & Scheduling:**
  - The generated HTML (in the `public` directory) can be served by any static file server (e.g., Nginx).
  - The update script (`update_page.py`) can be run manually using `uv run python -m ai_tools_website.update_page` or scheduled via cron or systemd on a VPS.

## Project Structure

```
ai-tools-website/
├── data/
│   └── tools.json          # Data store for AI tools
├── logs/                   # Directory for log files
├── public/                 # Generated static HTML files
├── src/ai_tools_website/
│   ├── __init__.py
│   ├── update_page.py      # Main script to update tools and regenerate the site
│   ├── search.py           # Module to search for AI tools via DuckDuckGo
│   └── logging_config.py   # Logging configuration module
├── templates/
│   └── index.html         # Jinja2 template for the website
├── pyproject.toml          # Project configuration and dependencies
└── README.md               # This file
```

## How It Works

1. **Data Ingestion:**
   - The update script calls `find_new_tools()` from `search.py` which executes several DuckDuckGo queries.
   - Results are processed to filter out entries missing key data (title, link, description) and then deduplicated based on their URL.
   - Each tool is assigned a category based on keywords in its title.

2. **HTML Generation:**
   - The tools (from `data/tools.json`) are grouped by category and rendered using a Jinja2 template (`templates/index.html`).
   - The output HTML is written to `public/index.html`.

3. **Logging:**
   - Logging is configured via `logging_config.py` and outputs detailed information about the ingestion and generation process.

## Running the Project

Install dependencies via UV and build in editable mode using Hatchling:

```bash
uv run python -m ai_tools_website.update_page
```

This command updates the tools list by performing web searches, saves new data to `data/tools.json`, and regenerates the HTML page.

## Deployment

Deploy the contents of the `public` directory on any static file server (e.g., Nginx, Apache, GitHub Pages, Netlify). For scheduled updates on a VPS, consider using cron or a systemd service to run the update script periodically.

## Future Improvements

- **Enhanced Categorization:** Use more advanced techniques or even an LLM to categorize tools more accurately.
- **Content Filtering:** Refine the search results to filter out blog posts or articles that are not direct tool listings.
- **Admin Interface:** Develop a simple CMS-style interface for administrators to manually curate and edit tools.
- **Improved Description Processing:** Better text cleaning and summarization of tool descriptions.

## License

This project is released under the [Apache License 2.0](LICENSE).