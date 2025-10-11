## Deployment
- Deployed to clifford VPS via Coolify
- Two containers: `aitools-web` (FastHTML app) and `aitools-updater` (cron jobs)

## Sitemaps
- Main sitemap served at: `https://drose.io/aitools/sitemap.xml`
- Individual sitemaps stored in MinIO at `sitemaps/` prefix
- Daily regeneration at 05:00 UTC via cron job in updater container
- Architecture:
  - `sitemap-static.xml` - Homepage/static pages
  - `sitemap-tools.xml` - All 535+ tool pages
  - `sitemap-categories.xml` - Category pages
  - `sitemap-comparisons.xml` - Comparison pages
- All sitemaps served with proper `Content-Length` headers for HEAD requests
- Submitted to Google Search Console via main portfolio sitemap index