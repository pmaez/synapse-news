# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Common commands

```bash
# Run all tests
python -m unittest discover -s tests

# Run a single test file
python -m unittest tests/test_storage.py

# Run a single test case
python -m unittest tests.test_storage.JsonStoreTest.test_json_store_round_trip

# Initialize state and run the tool
synapse-news init
synapse-news run
synapse-news test-run
```

## Architecture

The app is a CLI tool (`synapse-news`) that polls RSS feeds, fetches article text, and generates LLM summaries. All state lives in a single JSON file (default `data/synapse_news.json`).

### Module layout (`src/synapse_news/`)

- **`models.py`** — Pure dataclasses: `Feed`, `LLMSettings`, `AppSettings`. Each has `from_dict`/`to_dict` for JSON serialization. `retention_days=0` and `max_article_age_days=0` are normalized to `None` (disabled) by `parse_optional_positive_days`.
- **`storage.py`** — `JsonStore`: wraps the JSON state file with `fcntl`-based exclusive locking and atomic writes (temp file + `replace`). The `locked_data()` context manager is the safe write path — read-modify-write within a single lock acquisition.
- **`feeds.py`** — Feed fetching via `feedparser`, full-article fetch via `httpx` + BeautifulSoup, feed discovery (HTML `<link>` tags + known hardcoded patterns). Feed IDs are SHA-1(url)[:12]; article IDs are SHA-256(url).
- **`llm.py`** — LLM dispatch: OpenAI-compatible path (lmstudio, openai, openai-compatible) and Anthropic direct API path. On empty response, the OpenAI-compatible path retries once with a stricter system prompt. `provider=none` uses a sentence-extraction fallback.
- **`cli.py`** — `argparse`-based CLI. `run_once` is the main pipeline: purge → fetch new articles → summarize → mark seen. `test-run` reuses the same pipeline but skips persisting state unless `--save` is passed.

### Key invariants

- The `--data` flag is available on every subcommand to point at an alternate JSON file.
- Article content is truncated to 12,000 characters before the LLM prompt.
- If the LLM check fails before a run, no articles are marked seen so they will be retried on the next run.
- `summaries list` returns newest-first (reversed on read); the JSON file stores them append-order.

### Relevance filtering and ranking

When `interests` is non-empty, a scoring pass runs before summarization:
1. Each article is scored 1–10 by the LLM against `settings.interests` (e.g. `["Apple", "AI"]`).
2. Articles below `min_relevance_score` (default 5) are dropped.
3. Near-duplicate titles are deduplicated via word-overlap (≥60%) — highest-scored article per cluster survives.
4. Survivors are sorted descending by score before summarization.

Starred articles (titles) are injected as few-shot positive examples into every scoring prompt, so the system learns from explicit feedback.

```bash
# Set topics — scoring only activates when interests is non-empty
synapse-news config set-app --interests "Apple,AI"
synapse-news config set-app --min-relevance 7

# Star/unstar articles (short id shown in `summaries list`)
synapse-news article star <id-prefix>
synapse-news article unstar <id-prefix>
synapse-news article list-starred
```

Scoring uses `temperature=0.1` and `max_tokens=80` — a cheap, fast call relative to summarization. If interests is empty or `--provider none`, scoring is bypassed entirely.

### Planned SQLite backend

`docs/sqlite_schema.sql` captures the target schema. The JSON store's structure maps directly to it: `feeds`, `seen_articles`, `summaries`, and a `settings` key-value table. The Docker volume is mounted at `/app/data` so the path stays stable across the migration.
