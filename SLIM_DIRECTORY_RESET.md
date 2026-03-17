# Slim Directory Reset

## Goal

Turn the site into a simple, durable AI/LLM product directory for basic SEO.

The site should be good at:

- publishing clean tool pages that match real search intent
- keeping junk out of the index
- staying cheap to operate
- sending honest freshness signals

The site should stop trying to be an autonomous editorial machine.

## Product Definition

This is a directory, not a research engine.

Primary use case:

- a visitor already knows a tool, model, or product name
- a visitor searches a narrow category plus a tool type
- a visitor lands on a page and quickly understands what the product is

Non-goals for this reset:

- broad "best AI tools" editorial coverage
- autonomous long-form AI-written pages
- auto-generated comparisons across the full corpus
- daily taxonomy churn
- fake "freshness" created by background jobs touching metadata

## V1 of the Reset

Keep only three public page types:

- homepage
- category pages
- tool pages

Keep the page model intentionally thin:

- `name`
- `slug`
- `canonical_url`
- `summary`
- `category`
- `tags`
- optional source metadata
- optional structured metrics when cheap to fetch

## Canonical Tool Record

Target schema:

```json
{
  "slug": "qwen-code",
  "name": "Qwen Code",
  "canonical_url": "https://github.com/QwenLM/qwen-code",
  "summary": "Terminal-first AI coding agent for large codebases.",
  "category": "Code Assistants",
  "tags": ["coding", "agent", "terminal"],
  "source_type": "github",
  "source_url": "https://github.com/QwenLM/qwen-code",
  "metrics": {
    "github_stars": 0,
    "hf_downloads": 0,
    "npm_downloads_30d": 0,
    "pypi_downloads_30d": 0
  },
  "status": "candidate",
  "risk_flags": [],
  "discovered_at": "2026-03-17T00:00:00+00:00",
  "updated_at": "2026-03-17T00:00:00+00:00",
  "content_hash": "sha256:..."
}
```

Status meanings:

- `published`: indexable and included in listings + sitemap
- `hidden`: optionally accessible, not indexable, not listed
- `candidate`: not public yet
- `rejected`: not public

## Publish Policy

### Fixed rules

Categories are fixed by code and changed rarely by humans. They are not re-litigated by an LLM every day.

Hard-deny content should never be indexable:

- aimbots / cheats / exploit tooling
- gambling or betting predictors
- obvious NSFW SEO bait
- obvious scam / spam / malware-ish entries
- pages outside the intended AI/LLM product scope

### Public visibility

- only `published` tools appear on homepage, category pages, and tool sitemaps
- `hidden` tools may exist during migration but should not be listed or indexed
- `candidate` and `rejected` tools are not public

### Freshness

Freshness must be tied to real public changes.

Allowed reasons to bump `updated_at`:

- summary changed
- category changed
- tags changed
- canonical/source URL changed
- metrics changed in a way worth republishing
- publish status changed

Not allowed:

- save-without-change
- recategorization sweeps
- background review timestamps
- scheduler jobs touching records without changing public content

## Automation Model

AI stays backstage and bounded.

Use AI only where it adds real value:

- normalize a raw candidate into name / summary / category / tags
- emit risk flags
- decide whether a new candidate should be `published`, `hidden`, or `rejected`

Do not use AI for:

- daily full-corpus rewrites
- daily recategorization
- comparison generation across the corpus
- synthetic daily digests

Deterministic code should own:

- slug generation
- canonical URL normalization
- dedupe
- source/metric collection
- sitemap generation
- publish gating

## Jobs

### Keep

- candidate ingestion
- sitemap generation on actual published-data change
- analytics health checks
- lightweight traffic reporting

### Remove or disable

- autonomous editorial loop
- content enhancer
- comparison detection/generation
- daily recategorization
- traffic-based tiering as a publish control plane
- AI-written digest emails

## Rollout Plan

### Stage 0

Formalize the reset in-repo.

Deliverables:

- this spec
- README note pointing to the reset

### Stage 1

Add one publish policy layer and hard block obvious junk.

Deliverables:

- explicit visibility/status helpers
- denylist-based public gating
- sitemap and page rendering aligned with the same policy

### Stage 2

Remove fake freshness and category churn.

Deliverables:

- stop bulk-updating review timestamps
- stop using review metadata as sitemap freshness
- prevent no-op saves from looking like content updates

### Stage 3

Freeze taxonomy and slim the canonical record.

Deliverables:

- fixed category allowlist
- slim record shape
- migration path from current records

### Stage 4

Simplify the public UI.

Deliverables:

- homepage as a straightforward directory entry point
- cleaner category pages
- simple tool pages with summary + facts

### Stage 5

Replace the current discovery loop with a smaller candidate pipeline.

Deliverables:

- deterministic ingestion
- bounded AI normalization
- review queue for low-confidence candidates

## Commit Strategy

Keep each stage small and atomic.

Preferred order:

1. spec / docs
2. publish policy
3. freshness cleanup
4. schema slimming
5. UI simplification
6. job removal / scheduler cleanup

Do not land large mixed refactors that combine policy, UI, data migration, and scheduler changes in one commit.
