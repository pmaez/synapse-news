# Synapse News

RSS news monitor and summarizer written in Python. It starts with a simple JSON state file, supports local LM Studio through an OpenAI-compatible API, and can also call OpenAI or Anthropic.

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

Use `--data path/to/file.json` with any command to choose a different JSON state file.

## Commands

```bash
synapse-news feed list
synapse-news feed discover https://example.com/news
synapse-news feed update-url <feed_id> https://example.com/rss.xml
synapse-news feed remove <feed_id>
synapse-news config show
synapse-news config set-app --fetch-full-articles on --request-timeout-seconds 20
synapse-news config set-app --retention-days 14
synapse-news config set-app --max-article-age-days 3
synapse-news summaries list --limit 10
synapse-news summaries list --feed-id <feed_id> --json
synapse-news summaries list --html data/summaries.html
synapse-news reset --yes
synapse-news run --limit-per-feed 5
synapse-news run --max-article-age-days 3
synapse-news run --html data/run.html
synapse-news run --loop --interval-minutes 30
synapse-news test-run
synapse-news test-run --limit-per-feed 3
synapse-news test-run --max-article-age-days 3
synapse-news test-run --html data/test-run.html
synapse-news test-run --all
synapse-news test-run --feed-id <feed_id>
synapse-news test-run --quiet-feeds
```

After a run, view saved summaries:

```bash
synapse-news summaries list
synapse-news summaries list --limit 5
synapse-news summaries list --feed-id <feed_id>
synapse-news summaries list --json
synapse-news summaries list --html data/summaries.html
```

## Review TUI

Launch an interactive terminal UI to read summaries and vote on articles:

```bash
synapse-news review
synapse-news review --limit 50
```

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `u` | Toggle upvote (↑) |
| `d` | Toggle downvote (↓) |
| `o` | Open article URL in browser |
| `q` | Quit |

Upvoted articles are stored as positive examples and injected into every future scoring prompt so the LLM learns what you like. Downvoted articles are stored as negative examples and injected similarly. Voting is mutually exclusive — upvoting clears a downvote and vice versa. No vote has no effect on scoring.

To test summary quality without changing seen history or saved summaries:

```bash
synapse-news test-run
synapse-news test-run --limit-per-feed 3
synapse-news test-run --max-article-age-days 3
synapse-news test-run --html data/test-run.html
synapse-news test-run --all
synapse-news test-run --feed-id <feed_id>
```

Use `--save` if you want the test run to behave like a normal run and persist results.

If `test-run` shows a feed with zero entries, diagnose it:

```bash
synapse-news feed discover <site-or-feed-url>
synapse-news feed update-url <feed_id> <discovered-feed-url>
```

To process existing feed items again from scratch while keeping your feeds and settings:

```bash
synapse-news reset --yes
synapse-news run
```

Use `--keep-summaries` if you only want to clear seen history:

```bash
synapse-news reset --yes --keep-summaries
```

## Retention

By default, `run` purges seen article history and saved summaries older than 14 days. Change the retention window:

```bash
synapse-news config set-app --retention-days 30
```

Disable automatic purging:

```bash
synapse-news config set-app --retention-days 0
```

By default, feed runs consider all feed entries, regardless of age. To only process recent feed entries:

```bash
synapse-news config set-app --max-article-age-days 3
```

You can also override article age for one command without changing saved config:

```bash
synapse-news run --max-article-age-days 3
synapse-news test-run --max-article-age-days 3
```

Return to all articles:

```bash
synapse-news config set-app --max-article-age-days 0
```

## LLM Providers

LM Studio:

```bash
synapse-news config set-llm \
  --provider lmstudio \
  --base-url http://localhost:1234/v1 \
  --model your-local-model
```

OpenAI:

```bash
export OPENAI_API_KEY=...
synapse-news config set-llm \
  --provider openai \
  --base-url https://api.openai.com/v1 \
  --model gpt-4.1-mini \
  --api-key-env OPENAI_API_KEY \
  --reasoning-effort low
```

Anthropic:

```bash
export ANTHROPIC_API_KEY=...
synapse-news config set-llm \
  --provider anthropic \
  --model claude-3-5-sonnet-latest \
  --api-key-env ANTHROPIC_API_KEY \
  --thinking on \
  --thinking-budget-tokens 1024
```

Disable LLM calls and use a basic extractive fallback:

```bash
synapse-news config set-llm --provider none
```

The config includes switches for thinking and vision. Vision is stored now so the config shape is ready, but RSS article summarization currently uses text only.

## Troubleshooting

`[Errno 61] Connection refused` or `LLM check failed` means the configured LLM endpoint is not accepting connections. For LM Studio, start the local server and confirm the base URL:

```bash
synapse-news config set-llm --provider lmstudio --base-url http://localhost:1234/v1 --model your-local-model
```

Inside Docker, use the host URL instead:

```bash
synapse-news config set-llm --provider lmstudio --base-url http://host.docker.internal:1234/v1
```

To keep ingesting while LLM setup is offline:

```bash
synapse-news config set-llm --provider none
```

## Docker

Build and run once:

```bash
docker compose run --rm synapse-news init
docker compose run --rm synapse-news feed add https://example.com/rss --title Example
docker compose run --rm synapse-news run
```

Run on a schedule loop:

```bash
docker compose up --build
```

When LM Studio runs on the host, configure the base URL as:

```bash
synapse-news config set-llm --provider lmstudio --base-url http://host.docker.internal:1234/v1
```

## Storage Roadmap

The app currently persists feeds, seen article IDs, summaries, and LLM settings in `data/synapse_news.json`. The Docker volume is already mounted at `/app/data`, which keeps the storage path stable for a later SQLite backend such as `data/synapse_news.sqlite`.

The planned SQLite shape is captured in `docs/sqlite_schema.sql` so the JSON store can be migrated without changing the CLI surface.
