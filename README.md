# Synapse News

RSS news monitor and summarizer. Polls feeds, fetches full article text, and generates LLM summaries. Supports LM Studio, OpenAI, Anthropic, or no LLM (extractive fallback). All state lives in a single JSON file.

## Quick Start

**With pipx** (recommended for running as a global CLI tool):

```bash
pipx install /path/to/synapse-news

synapse-news init
synapse-news feed add https://example.com/rss --title "Example"
synapse-news config set-llm --provider lmstudio --base-url http://localhost:1234/v1 --model local-model
synapse-news run
```

**With a virtual environment** (recommended for development):

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

# Set minimum score threshold (1–10, default 8)
synapse-news config set-app --min-relevance 8
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
synapse-news config set-app --retention-days 7        # 0 to disable purging
synapse-news config set-app --max-article-age-days 3  # 0 for all articles
synapse-news config set-app --user-agent "MyBot/1.0"
synapse-news config set-app --interests "Apple,AI"
synapse-news config set-app --min-relevance 8
```

### API key configuration

There are two ways to supply an API key:

- **`--api-key <value>`** — stores the key directly in the JSON state file (plaintext). Simple but the secret is visible in the file.
- **`--api-key-env <VAR>`** — stores only the *name* of an environment variable. The actual key is read from the environment at runtime and never written to the state file. This is the recommended approach.

If both are set, `api_key` takes precedence over `api_key_env`.

**Step 1.** Tell the app which env var to look up:

```bash
synapse-news config set-llm --provider anthropic --api-key-env ANTHROPIC_API_KEY
```

**Step 2.** Set the env var before running. For a one-off run:

```bash
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE synapse-news run
```

Or export it for the duration of your shell session:

```bash
export ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
synapse-news run
```

**Step 3 (optional).** To persist it across sessions, add the export to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE' >> ~/.zshrc
source ~/.zshrc
```

The same pattern works for any provider — substitute the env var name and provider accordingly:

```bash
# OpenAI
synapse-news config set-llm --provider openai --model gpt-4.1-mini --api-key-env OPENAI_API_KEY
export OPENAI_API_KEY=sk-YOUR_KEY_HERE

# Anthropic
synapse-news config set-llm --provider anthropic --model claude-sonnet-4-6 --api-key-env ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
```

### LLM settings

```bash
synapse-news config set-llm --provider lmstudio|openai|openai-compatible|anthropic|none
synapse-news config set-llm --model <model-id>
synapse-news config set-llm --base-url <url>
synapse-news config set-llm --api-key <key>
synapse-news config set-llm --api-key-env <ENV_VAR>
synapse-news config set-llm --temperature 0.3
synapse-news config set-llm --max-summary-tokens 800
synapse-news config set-llm --max-scoring-tokens 120
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

By default `run` purges seen article history and summaries older than 7 days.

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

### Prerequisites

Docker Desktop installed and running (whale icon in the menu bar).

### Quick start

```bash
# Build the image and start the loop in the background
docker compose up -d --build

# View live logs
docker compose logs -f

# Stop
docker compose down
```

The default command in `compose.yml` runs `synapse-news run --loop --interval-minutes 60` using the `docker` profile (see [Local LLM — LM Studio](#local-llm--lm-studio-in-docker) below).

### Running commands

```bash
# One-off command against the image (recommended — container is removed after)
docker compose run --rm synapse-news summaries list
docker compose run --rm synapse-news config show
docker compose run --rm synapse-news feed add https://example.com/rss --title Example

# Run a command inside the already-running container
docker compose exec synapse-news synapse-news summaries list

# Interactive shell inside the running container
docker compose exec synapse-news bash
```

### First-time setup

```bash
# Initialize state file
docker compose run --rm synapse-news init

# Add feeds
docker compose run --rm synapse-news feed add https://example.com/rss --title Example

# Configure LLM (see providers section — use host.docker.internal for local models)
docker compose run --rm synapse-news config set-llm --provider anthropic --api-key-env ANTHROPIC_API_KEY

# Start the loop
docker compose up -d --build
```

### State persistence

`./data` on your Mac is bind-mounted into the container at `/app/data`. The JSON state file, summaries, and HTML reports all live there and persist across restarts. The native app and the container share the same file.

### API keys

`compose.yml` passes `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from your shell into the container. Set them before running:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up -d --build
```

### Local LLM — LM Studio in Docker

Inside Docker, `localhost` refers to the container itself, not your Mac. To reach LM Studio running on your Mac, use `host.docker.internal` instead. The `compose.yml` already includes the `extra_hosts` entry that makes this hostname resolve correctly on Linux hosts too.

The recommended approach is a named profile so the native app (which uses `localhost`) and the container (which needs `host.docker.internal`) don't conflict:

```bash
# Create the docker profile once
docker compose run --rm synapse-news config profile save docker \
  --provider lmstudio \
  --base-url http://host.docker.internal:1234/v1 \
  --model your-model-name
```

`compose.yml` passes `--profile docker` to the run command, so the container automatically picks this up. Your native `synapse-news run` continues using the active settings with `localhost`.

### Applying compose.yml changes

If you edit `compose.yml` while the container is running, restart it to pick up the changes:

```bash
docker compose up -d --force-recreate
```

### How the Dockerfile works

```dockerfile
FROM python:3.12-slim
```
Official Python 3.12 on Debian slim — small base image, no extras.

```dockerfile
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN pip install .
```
Dependencies are installed in a separate layer from the application code. Docker caches layers — if you only change application code (not `requirements.txt`), the dependency install is skipped on the next build.

```dockerfile
ENTRYPOINT ["synapse-news"]
CMD ["run"]
```
`ENTRYPOINT` fixes the executable. `CMD` provides the default argument (`run`). The `command:` in `compose.yml` replaces `CMD`, which is how `run --loop --interval-minutes 60 --profile docker` is passed in.

---

## Storage Roadmap

All state is stored in `data/synapse_news.json`. The Docker volume is mounted at `/app/data` to keep the path stable for a later SQLite migration. The planned schema is in `docs/sqlite_schema.sql`.
