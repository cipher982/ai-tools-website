# AI Tools Website

Slim AI/LLM product directory at `drose.io/aitools`.

This repo is being reset from an autonomous content machine into a simple directory for basic SEO. The canonical reset spec lives in [SLIM_DIRECTORY_RESET.md](SLIM_DIRECTORY_RESET.md).

## Product Scope

The live product is intentionally narrow:

- homepage
- fixed category pages
- tool pages
- honest sitemap freshness

Published tools are projected into a thin public record:

- `name`
- `slug`
- `canonical_url`
- `summary`
- `category`
- `tags`
- `source_type`
- `source_url`
- `metrics`
- `status`
- `risk_flags`
- `discovered_at`
- `updated_at`
- `content_hash`

The projection logic lives in `ai_tools_website/v1/public_catalog.py`.

## Architecture

- `web` container: FastHTML app serving the directory
- `updater` container: UV environment used by Sauron for explicit maintenance commands
- storage: MinIO in production, local JSON in development
- deployment: Coolify on `clifford`

The web process keeps an in-memory tools cache. After changing `tools.json`, redeploy the app or hit the homepage to refresh public listings.

## Runtime Scope

Still part of the intended runtime:

- public page rendering
- publish policy and junk blocking
- slim-record projection
- sitemap generation
- Umami tracking

Retired from the intended runtime:

- autonomous editorial loop
- enhancement jobs
- comparison generation
- daily recategorization and tier churn
- AI-written digest emails

Legacy modules still exist in the repo for now, but they are not part of the slim-directory production loop.

## Scheduled Jobs

Current production jobs:

- `aitools-sitemaps`
- `aitools-umami-watchdog`

Disabled jobs:

- `aitools-discovery`
- `aitools-editorial-loop`
- `aitools-enhancement`
- `aitools-comparisons`
- `aitools-tier-traffic`
- `aitools-digest`

## Local Development

```bash
uv sync
uv run uvicorn "ai_tools_website.v1.web:app" --reload --host 0.0.0.0 --port 8000
```

Useful commands:

```bash
# Project the current dataset into the slim public schema
uv run python -m ai_tools_website.v1.maintenance slim-reset --dry-run --json-output

# Persist the slim public schema
uv run python -m ai_tools_website.v1.maintenance slim-reset

# Rebuild sitemaps
uv run python -m ai_tools_website.v1.sitemap_builder

# Validate changes
uv run pytest
uv run ruff check ai_tools_website tests
```

## Configuration

See `.env.example` for a working baseline. Core runtime settings:

- `WEB_PORT`
- `LOG_LEVEL`
- `BASE_PATH`
- `SERVICE_URL_WEB`
- `AITOOLS_STORAGE_BACKEND`
- `AITOOLS_LOCAL_DATA_DIR`
- `TOOLS_FILE`
- `AITOOLS_SLUG_REGISTRY_FILE`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET_NAME`
- `MINIO_PUBLIC_URL`
- `UMAMI_WEBSITE_ID`
- `UMAMI_SCRIPT_SRC`
- `UMAMI_DOMAINS`
- `UMAMI_DROSE_ID`

Legacy discovery/editorial/comparison modules still require model and API settings such as `OPENAI_API_KEY`, `TAVILY_API_KEY`, `SEARCH_MODEL`, `MAINTENANCE_MODEL`, `CONTENT_ENHANCER_MODEL`, and `WEB_SEARCH_MODEL`. Those are no longer required for the normal slim-directory runtime.

## Deployment Notes

- Coolify deploys both the web container and the updater container.
- Sauron executes maintenance commands inside the updater container with `docker exec`.
- Container-to-LiteLLM traffic should use `http://litellm-proxy:4000`, not the public hostname.
