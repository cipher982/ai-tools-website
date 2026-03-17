AI Tools directory at drose.io/aitools. Slim AI/LLM product directory with homepage, category pages, and tool pages. FastHTML/Python app with MinIO or local JSON storage.

## Architecture

- **Web container**: FastHTML app serving the site
- **Updater container**: UV environment for explicit maintenance commands; Sauron `docker exec`s into it
- **Storage**: MinIO in production; local JSON in development

Deployed to clifford VPS via Coolify.
- **LiteLLM from containers:** use `http://litellm-proxy:4000`, not the public `https://llm.drose.io` hostname.
- **Listings cache:** the web process keeps an in-memory tools cache; after `tools.json` edits, redeploy or hit the homepage to refresh public listings.

## Scheduled Jobs

All scheduled jobs run via **Sauron** (centralized scheduler on clifford).

Enabled:

- `aitools-sitemaps`
- `aitools-umami-watchdog`

Disabled by the slim-directory reset:

- `aitools-discovery`
- `aitools-editorial-loop`
- `aitools-enhancement`
- `aitools-comparisons`
- `aitools-tier-traffic`
- `aitools-digest`

**Manual execution:**
```bash
ssh clifford "docker exec aitools-updater uv run python -m ai_tools_website.v1.maintenance slim-reset"
ssh clifford "docker exec aitools-updater uv run python -m ai_tools_website.v1.sitemap_builder"
```

See `~/git/sauron` for job definitions.

## Key Modules

- `v1/public_catalog.py`: fixed taxonomy + slim public record projection
- `v1/editorial.py`: publish policy and junk blocking
- `v1/maintenance.py`: maintenance CLI, including `slim-reset`
- `v1/data_manager.py`: tools.json load/save and optimistic merge behavior
- `v1/sitemap_builder.py`: sitemap generation
- `v1/web.py`: public directory pages
