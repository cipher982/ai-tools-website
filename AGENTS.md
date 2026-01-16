AI Tools directory at drose.io/aitools - catalog of 535+ AI tools with categories, comparisons, and search. FastHTML/Python app with MinIO storage.

## Architecture

- **Web container**: FastHTML app serving the site
- **Updater container**: UV environment for maintenance tasks (no scheduler - just keeps alive for docker exec)
- **Storage**: MinIO for sitemaps, tools.json persisted in container volume

Deployed to clifford VPS via Coolify.

## Scheduled Jobs

All scheduled jobs run via **Sauron** (centralized scheduler on clifford). The updater container provides UV and dependencies; Sauron orchestrates when jobs run via `docker exec`.

| Job | Schedule (UTC) | Sauron ID | Description |
|-----|----------------|-----------|-------------|
| Discovery + tier | 02:00 daily | aitools-discovery | Search for new tools, recategorize, re-tier |
| Traffic tier | 01:00 Sunday | aitools-tier-traffic | Fetch Umami pageviews, boost high-traffic tools |
| Enhancement | 03:00 Monday | aitools-enhancement | AI content generation for tool pages |
| Comparisons | 04:00 1st of month | aitools-comparisons | Detect and generate tool comparisons |
| Sitemaps | 05:00 daily | aitools-sitemaps | Regenerate and publish sitemaps to MinIO |

**Manual job execution:**
```bash
# Via Sauron CLI
ssh clifford "docker exec sauron-container python -m sauron.cli run aitools-tier-traffic"

# Direct in updater container
ssh clifford "docker exec aitools-updater uv run python -m ai_tools_website.v1.maintenance tier-traffic"
```

See `~/git/sauron` for job definitions.

## Quality Tiers

Tools are scored and tiered for content generation budget:

- **Tier 1** (top 50): Deep research, 5 web searches, 3 LLM passes
- **Tier 2** (next 150): Standard research, 2 web searches, 2 LLM passes
- **Tier 3** (rest): Basic info, no web searches, 1 LLM pass
- **noindex**: Too thin to index, skip LLM calls

Scoring factors:
- GitHub stars (max 35 pts)
- HuggingFace downloads (max 35 pts)
- Category popularity (max 15 pts)
- Content quality signals (max 10 pts)
- Existing content quality (max 5 pts)
- **Umami traffic** (max 25 pts) - percentile-based, auto-adjusts

## Key Modules

- `v1/maintenance.py`: CLI for tier, tier-traffic, recategorize, deduplicate
- `v1/quality_tiers.py`: Scoring logic and tier assignment
- `v1/data_aggregators/umami_aggregator.py`: Umami PostgreSQL queries
- `v1/content_enhancer_v2.py`: AI content generation
- `v1/sitemap_builder.py`: Sitemap generation
