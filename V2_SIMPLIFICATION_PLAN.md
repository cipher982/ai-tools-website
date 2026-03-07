# AI Tools Website V2 — Simplify First

## Why change

The current site behaves like a broad AI directory with multiple independent pipelines:

- discovery (`search.py`)
- recategorization (`maintenance.py recategorize`)
- tiering (`maintenance.py tier` / `tier-traffic`)
- content enhancement (`content_enhancer_v2.py`)
- comparison detection (`comparison_detector.py`)
- comparison generation (`comparison_generator.py`)
- sitemap publishing (`sitemap_builder.py`)

That stack optimizes for coverage and SEO-shaped completeness, but not for usefulness.

Recent live signals support that:

- most recent traffic is single-page traffic on long-tail pages
- some of the top landing pages are clearly off-strategy (`open-aimbot`, betting/gambling helpers, aimbots)
- the current dataset is largely raw records (`quality_tier` is unset across the live catalog)

The result is a site that can feel machine-filled instead of editorially useful.

## V2 goal

Turn the site from a generic AI directory into a **small, opinionated decision engine**.

The goal is not:

- maximum page count
- maximum schema coverage
- maximum daily freshness across every AI tool on earth

The goal is:

- help a visitor decide quickly whether a tool is worth trying
- focus on legitimate tools for builders / creators / serious users
- prune junk aggressively
- publish fewer, sharper pages

## Product wedge

Recommended wedge:

> **Legitimate AI tools for builders and creators** — coding tools, local/open-source tools, model tooling, creator utilities, and practical workflow tools.

Default exclusions:

- cheating / exploit tools
- gambling/betting “prediction” tools
- obvious spam or scam pages
- dubious “uncensored” or risky pages that create trust drag

This means the site should stop trying to be “the homepage of all AI tools”.

## V2 principle

Keep deterministic systems for facts.
Use agents for judgment.

### Deterministic systems should own

- canonical tool record
- slug generation
- source URLs
- simple stats (GitHub, HF, package registries)
- dedupe keys
- freshness timestamps
- sitemap generation
- outbound click tracking

### Agents should own

- should this page exist?
- keep / noindex / delete / needs_review
- who the tool is actually for
- who should avoid it
- what the page angle should be
- which comparisons are worth making
- what changed enough to deserve a refresh

## What to remove or collapse

### Remove as standalone concepts

- separate recategorization job
- separate tiering jobs as the main editorial control plane
- separate comparison-detection pipeline for the full corpus
- full-corpus enhancement as the default path
- duplicate pipeline-status systems

### Collapse to one scheduler source of truth

Use Sauron only.

Keep `scripts/run-*.sh` as manual wrappers, but stop treating cron/supercronic docs as canonical.

### Merge search surfaces

Unify all web-search usage behind one adapter.

Today the project mixes:

- Tavily in discovery
- Responses API web search in enhancement/comparisons
- an unused `tools/web_search.py`

V2 should expose one `research.py` / `search_provider.py` abstraction.

## V2 architecture

### Core idea

Replace the many-step “discover -> categorize -> tier -> enhance -> compare” machine with **two content loops and one publisher**.

### Loop 1: Discover + triage

Single job: `discover_and_triage`

Responsibilities:

1. gather candidates from search / known sources
2. normalize basic facts deterministically
3. dedupe against existing records
4. run a bounded editorial agent for each new or suspicious record
5. assign:
   - `action = keep | noindex | delete | needs_review`
   - `site_fit`
   - `ideal_user`
   - `not_for`
   - `page_angle`
   - `confidence`
6. persist the result

This job replaces most of:

- discovery prompt chains in `search.py`
- recategorization as a separate mental model
- tiering as a broad quality proxy

### Loop 2: Refresh focus pages

Single job: `refresh_focus_pages`

Input priority should come from:

- pages with real traffic
- pages with outbound clicks
- recently changed tools
- high-confidence keeper pages missing editorial fields
- pages manually pinned by you

Responsibilities:

1. pick a small batch (e.g. 10–20 pages)
2. run a bounded editorial agent with a concrete goal:
   - improve decision value, not length
3. produce a compact editorial payload:
   - `summary`
   - `why_choose`
   - `why_not`
   - `best_for`
   - `alternatives`
   - `comparison_candidates`
   - `last_reviewed_at`
   - `review_confidence`
4. save only if quality improves

This replaces the current full-corpus enhancement mindset.

### Publisher

Single publisher remains:

- render pages from canonical facts + editorial payload
- publish sitemaps only for `keep` pages
- keep `noindex` pages out of sitemap and homepage modules
- never render `delete` pages publicly

## The bounded agent contract

The agent should not be an open-ended loop with full repo/database power.

It should be a **bounded editor** with:

- clear tool inputs
- clear schema outputs
- a limited budget
- no authority to invent core facts
- no authority to publish garbage just because it can fill fields

### Agent output schema

Suggested first schema:

```json
{
  "action": "keep",
  "why": "...",
  "ideal_user": "...",
  "not_for": "...",
  "decision_value": ["..."],
  "page_angle": "...",
  "suggested_sections": ["..."],
  "comparison_candidates": ["..."],
  "confidence": 0.86
}
```

### Hard rules

- if confidence is low, return `needs_review`
- if the tool is harmful / junk / off-strategy, return `delete`
- if the tool may be real but trust-draggy, return `noindex`
- if the tool cannot add specific decision value, do not rewrite the page

## Page model changes

### Current problem

The current page shape pushes toward “overview / features / use cases / pricing / alternatives” for almost everything.

That is too uniform.

### V2 page shape

Use a compact decision-first layout:

1. **What it is**
2. **Who it’s for**
3. **Why choose it**
4. **Why skip it**
5. **Alternatives**
6. **Quick facts**

Optional sections only when earned:

- install / self-host
- benchmarks
- API notes
- model details
- workflow examples

This is a better match for real user intent than padded overview prose.

## Homepage changes

The homepage should stop being a generic category directory first.

Recommended modules:

- **Worth your time this week**
- **Best coding / builder tools**
- **Good open-source options**
- **Newly reviewed**
- **Recently changed**
- **Compare before you pick**

De-emphasize giant category walls and inflated tool counts.

## Comparison strategy

Do not generate comparisons for the full catalog.

Instead:

- only generate comparisons for high-intent pairs
- require both tools to be `keep`
- require credible overlap in use case
- require evidence that the comparison helps an actual decision

Good examples:

- `OpenCode vs Aider`
- `Cursor vs Claude Code`
- `ComfyUI vs InvokeAI`

Bad examples:

- random low-signal pairings just because names are related

## Metrics that matter in V2

Move away from “catalog size” and “pages generated”.

Primary metrics:

- outbound click-through rate on tool pages
- compare-page visits
- multi-page session rate
- return visitor rate
- homepage-to-tool click rate
- pages marked `delete` or `noindex` as a quality-control metric

Guardrail metrics:

- average agent confidence
- pages refreshed but not published
- manual overrides by you
- tool records with missing facts

## Experiment notes (2026-03-07)

Quick bounded-agent experiments were run with `hatch` using the current live tool shapes.

### Experiment 1: current-style page writer vs editorial agent

On `open-aimbot`:

- the current-style writer happily produced a polished directory page
- the editorial agent immediately returned `delete`

On `opencode`:

- the current-style writer produced a competent but generic page
- the editorial agent returned `keep` with a sharp angle:
  - open-source, self-hosted coding agent
  - multi-model flexibility
  - MCP ecosystem
  - likely comparison targets

### Experiment 2: batch triage on top-traffic pages

The editorial agent kept:

- `evomaster`
- `vcclient-real-time-voice-changer`
- `inswapper`
- `opencode`

It deleted:

- `open-aimbot`
- `aviator-prediction`
- `aimbot`
- `primeaim`
- `aimr`

It marked:

- `flux-uncensored` as `noindex`

That is exactly the kind of taste filter V2 needs.

## Recommended implementation order

### Phase 1 — simplify the control plane

1. pick Sauron as the only scheduler truth
2. delete stale cron/supercronic/docs paths
3. unify web search behind one adapter
4. remove duplicate pipeline status path

### Phase 2 — add the editorial action layer

1. extend canonical tool schema with:
   - `action`
   - `site_fit`
   - `ideal_user`
   - `not_for`
   - `page_angle`
   - `review_confidence`
   - `last_reviewed_at`
2. build `editorial_agent.py`
3. build `discover_and_triage.py`
4. stop auto-indexing every discovered tool

### Phase 3 — refresh only the pages that matter

1. build `refresh_focus_pages.py`
2. feed it from traffic + click + freshness signals
3. render compact decision-first pages
4. remove the assumption that every tool needs a long generated page

### Phase 4 — comparisons only where earned

1. make comparisons an extension of editorial judgment
2. only compare `keep` pages
3. only generate pages with strong overlap and clear decision value

## Files likely to change

### In `ai-tools-website`

- `ai_tools_website/v1/search.py`
- `ai_tools_website/v1/maintenance.py`
- `ai_tools_website/v1/content_enhancer_v2.py`
- `ai_tools_website/v1/comparison_detector.py`
- `ai_tools_website/v1/comparison_generator.py`
- `ai_tools_website/v1/web.py`
- `ai_tools_website/v1/data_manager.py`
- `ai_tools_website/v1/storage.py`
- `ai_tools_website/v1/pipeline_db.py`
- `scripts/run-update.sh`
- `scripts/run-enhancement.sh`
- `scripts/run-comparisons.sh`
- `README.md`

### In `sauron-jobs`

- `jobs/ai_tools_website/runner.py`
- `manifest.py`

## The simplest possible V2

If we want to be ruthless about simplification, V2 can start with just three jobs:

1. `aitools-discovery-triage`
2. `aitools-refresh-focus`
3. `aitools-sitemaps`

Everything else becomes implementation detail inside those jobs or gets removed.

## Decision

**Do not build a fully autonomous free-running agent loop.**

Build a **bounded editorial agent inside a much smaller system**.

That gives you the upside of taste, pruning, and stronger page angles without losing control of facts, cost, or quality.
