# Synapse News

RSS news monitor and summarizer. Polls feeds, fetches full article text, and generates LLM summaries. Supports LM Studio, OpenAI, Anthropic, or no LLM (extractive fallback). All state lives in a single JSON file.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

synapse-news init
synapse-news feed add https://example.com/rss --title "Example"
synapse-news config set-llm --provider lmstudio --base-url http://localhost:1234/v1 --model local-model
synapse-news run
```

Use `--data path/to/file.json` with any command to point at a different state file.

---

## Feed Management

```bash
# Add or update a feed
synapse-news feed add <url>
synapse-news feed add <url> --title "My Feed"
synapse-news feed add <url> --tags "tech,ai"
synapse-news feed add <url> --disabled

# Discover RSS/Atom feeds from a site URL
synapse-news feed discover <url>

# List all feeds (including disabled)
synapse-news feed list

# Update a feed's URL while keeping its ID
synapse-news feed update-url <feed_id> <new_url>
synapse-news feed update-url <feed_id> <new_url> --title "New Title"

# Remove a feed
synapse-news feed remove <feed_id>
```

---

## Running

```bash
# Fetch new articles and summarize them
synapse-news run

# Limit articles fetched per feed
synapse-news run --limit-per-feed 5

# Only process articles newer than N days
synapse-news run --max-article-age-days 3

# Write this run's summaries to an HTML file
synapse-news run --html data/run.html

# Fetch without calling the LLM
synapse-news run --dry-run

# Run forever on an interval (default 60 minutes)
synapse-news run --loop
synapse-news run --loop --interval-minutes 30
```

### Test run (no side effects)

Fetches and summarizes articles without updating seen history or saving summaries. Useful for checking feed quality and LLM output.

```bash
synapse-news test-run
synapse-news test-run --limit-per-feed 3
synapse-news test-run --all                         # all articles from each feed
synapse-news test-run --feed-id <feed_id>          # one feed only
synapse-news test-run --max-article-age-days 3
synapse-news test-run --html data/test-run.html
synapse-news test-run --dry-run                    # fetch only, skip LLM
synapse-news test-run --save                       # persist results like a normal run
synapse-news test-run --quiet-feeds                # hide per-feed diagnostics
```

---

## Summaries

```bash
# List saved summaries (newest first, default 10)
synapse-news summaries list
synapse-news summaries list --limit 25
synapse-news summaries list --feed-id <feed_id>
synapse-news summaries list --json
synapse-news summaries list --html data/summaries.html
```

---

## Review TUI

Browse summaries and vote on articles interactively. Votes are used as few-shot examples in future relevance scoring.

```bash
synapse-news review
synapse-news review --limit 50
```

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `u` | Toggle upvote (↑) — marks article as positive example |
| `d` | Toggle downvote (↓) — marks article as negative example |
| `o` | Open article URL in browser |
| `q` | Quit |

Votes are mutually exclusive — upvoting clears a downvote and vice versa. No vote has no effect on scoring.

### Article voting via CLI

```bash
# Upvote (star) an article by ID prefix shown in `summaries list`
synapse-news article star <id-prefix>
synapse-news article unstar <id-prefix>
synapse-news article list-starred
```

---

## Relevance Filtering

When interests are set, each article is scored 1–10 by the LLM before summarization. Articles below the minimum score are dropped; survivors are sorted by score.

```bash
# Set topics of interest (scoring only activates when this is non-empty)
synapse-news config set-app --interests "Apple,AI,Python"

# Clear interests (disables scoring entirely)
synapse-news config set-app --interests ""

# Set minimum score threshold (1–10, default 5)
synapse-news config set-app --min-relevance 7
```

Upvoted article titles are injected into the scoring prompt as positive examples; downvoted titles as negative examples. This improves scoring accuracy over time without changing interests or thresholds.

---

## Configuration

```bash
# Show current settings
synapse-news config show
```

### App settings

```bash
synapse-news config set-app --fetch-full-articles on|off
synapse-news config set-app --request-timeout-seconds 30
synapse-news config set-app --retention-days 14       # 0 to disable purging
synapse-news config set-app --max-article-age-days 3  # 0 for all articles
synapse-news config set-app --user-agent "MyBot/1.0"
synapse-news config set-app --interests "Apple,AI"
synapse-news config set-app --min-relevance 7
```

### LLM settings

```bash
synapse-news config set-llm --provider lmstudio|openai|openai-compatible|anthropic|none
synapse-news config set-llm --model <model-id>
synapse-news config set-llm --base-url <url>
synapse-news config set-llm --api-key <key>
synapse-news config set-llm --api-key-env <ENV_VAR>
synapse-news config set-llm --temperature 0.3
synapse-news config set-llm --max-tokens 800
synapse-news config set-llm --thinking on|off
synapse-news config set-llm --thinking-budget-tokens 2048
synapse-news config set-llm --vision on|off
synapse-news config set-llm --reasoning-effort low|medium|high
```

### LLM profiles

Named profiles let you save multiple LLM configurations and switch between them.

```bash
# Save a named profile (accepts all the same flags as set-llm)
synapse-news config profile save haiku --provider anthropic --model claude-haiku-4-5-20251001 --api-key-env ANTHROPIC_API_KEY
synapse-news config profile save local --provider lmstudio --model my-local-model
synapse-news config profile save gpt --provider openai --model gpt-4.1-mini --api-key-env OPENAI_API_KEY

# Set a profile as the active LLM config
synapse-news config profile use haiku

# Use a profile for a single run without changing the active config
synapse-news run --profile haiku
synapse-news test-run --profile haiku

# List all saved profiles
synapse-news config profile list

# Delete a profile
synapse-news config profile delete haiku
```

---

## LLM Providers

**LM Studio** (default):
```bash
synapse-news config set-llm \
  --provider lmstudio \
  --base-url http://localhost:1234/v1 \
  --model your-local-model
```

**OpenAI**:
```bash
export OPENAI_API_KEY=sk-...
synapse-news config set-llm \
  --provider openai \
  --model gpt-4.1-mini \
  --api-key-env OPENAI_API_KEY
```

**Anthropic**:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
synapse-news config set-llm \
  --provider anthropic \
  --model claude-3-5-sonnet-latest \
  --api-key-env ANTHROPIC_API_KEY
```

**No LLM** (extractive sentence fallback):
```bash
synapse-news config set-llm --provider none
```

---

## Retention

By default `run` purges seen article history and summaries older than 14 days.

```bash
synapse-news config set-app --retention-days 30   # keep for 30 days
synapse-news config set-app --retention-days 0    # disable purging

# Only process feed entries newer than N days
synapse-news config set-app --max-article-age-days 3

# Override for a single run without changing saved config
synapse-news run --max-article-age-days 3
synapse-news config set-app --max-article-age-days 0   # back to all articles
```

---

## Reset

Clear seen article history so current feed items are processed again:

```bash
synapse-news reset --yes
synapse-news reset --yes --keep-summaries   # clear seen history but keep old summaries
```

---

## Troubleshooting

**`LLM check failed` / connection refused**

The configured LLM endpoint isn't reachable. For LM Studio, start the local server:
```bash
synapse-news config set-llm --provider lmstudio --base-url http://localhost:1234/v1 --model your-model
```

Inside Docker, use the host bridge URL:
```bash
synapse-news config set-llm --base-url http://host.docker.internal:1234/v1
```

To keep running while LLM setup is offline:
```bash
synapse-news config set-llm --provider none
```

**Feed shows zero entries**
```bash
synapse-news feed discover <site-url>
synapse-news feed update-url <feed_id> <discovered-feed-url>
```

---

## Docker

```bash
docker compose run --rm synapse-news init
docker compose run --rm synapse-news feed add https://example.com/rss --title Example
docker compose run --rm synapse-news run
```

Run on a schedule loop:
```bash
docker compose up --build
```

---

## Storage Roadmap

All state is stored in `data/synapse_news.json`. The Docker volume is mounted at `/app/data` to keep the path stable for a later SQLite migration. The planned schema is in `docs/sqlite_schema.sql`.
