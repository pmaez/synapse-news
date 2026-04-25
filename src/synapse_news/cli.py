from __future__ import annotations

import argparse
from html import escape
import json
import time
from pathlib import Path

import httpx

from .feeds import Article, FeedFetchResult, deduplicate_articles, discover_feed_title, discover_feed_urls, feed_id_for_url, fetch_articles_by_feed, fetch_new_articles, known_feed_candidates, parse_tags
from .llm import LLMError, check_llm_available, score_article, summarize
from .models import AppSettings, Feed, parse_optional_positive_days, utc_now_iso
from .storage import JsonStore


DEFAULT_DATA_PATH = Path("data/synapse_news.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RSS news monitor and summarizer.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="Path to JSON state file.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create the JSON state file.")
    reset_parser = subparsers.add_parser("reset", help="Clear seen articles so feeds are processed again.")
    reset_parser.add_argument("--yes", action="store_true", help="Confirm the reset without prompting.")
    reset_parser.add_argument("--keep-summaries", action="store_true", help="Keep old summaries while clearing seen articles.")

    summaries_parser = subparsers.add_parser("summaries", help="View saved summaries.")
    summaries_sub = summaries_parser.add_subparsers(dest="summaries_command", required=True)
    summaries_list = summaries_sub.add_parser("list", help="List saved summaries.")
    summaries_list.add_argument("--limit", type=int, default=None, help="Maximum summaries to show. Defaults to 10 for terminal output, all for --html and --json.")
    summaries_list.add_argument("--feed-id", help="Only show summaries for one feed id.")
    summaries_list.add_argument("--json", action="store_true", help="Output summaries as JSON.")
    summaries_list.add_argument("--html", type=Path, help="Write summaries to a readable HTML file.")

    feed_parser = subparsers.add_parser("feed", help="Manage RSS feeds.")
    feed_sub = feed_parser.add_subparsers(dest="feed_command", required=True)
    feed_add = feed_sub.add_parser("add", help="Add or update a feed.")
    feed_add.add_argument("url")
    feed_add.add_argument("--title")
    feed_add.add_argument("--tags", help="Comma-separated tags.")
    feed_add.add_argument("--disabled", action="store_true")
    feed_remove = feed_sub.add_parser("remove", help="Remove a feed by id.")
    feed_remove.add_argument("feed_id")
    feed_update = feed_sub.add_parser("update-url", help="Update a feed URL while keeping its id.")
    feed_update.add_argument("feed_id")
    feed_update.add_argument("url")
    feed_update.add_argument("--title")
    feed_discover = feed_sub.add_parser("discover", help="Discover RSS/Atom feeds from a URL.")
    feed_discover.add_argument("url")
    feed_sub.add_parser("list", help="List feeds.")

    config_parser = subparsers.add_parser("config", help="View or update settings.")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show", help="Show settings.")
    app_parser = config_sub.add_parser("set-app", help="Configure app behavior.")
    app_parser.add_argument("--fetch-full-articles", choices=["on", "off"])
    app_parser.add_argument("--request-timeout-seconds", type=float)
    app_parser.add_argument("--retention-days", type=int, help="Purge seen articles and summaries older than this many days. Use 0 to disable.")
    app_parser.add_argument("--max-article-age-days", type=int, help="Only process feed articles newer than this many days. Use 0 for all articles.")
    app_parser.add_argument("--user-agent")
    app_parser.add_argument("--interests", help="Comma-separated topics of interest used to filter articles (e.g. 'Apple,AI'). Pass empty string to disable filtering.")
    app_parser.add_argument("--min-relevance", type=int, help="Minimum relevance score (1-10) to include an article when interests are set. Default 5.")
    llm_parser = config_sub.add_parser("set-llm", help="Configure LLM provider settings.")
    llm_parser.add_argument("--provider", choices=["lmstudio", "openai", "openai-compatible", "anthropic", "none"])
    llm_parser.add_argument("--model")
    llm_parser.add_argument("--base-url")
    llm_parser.add_argument("--api-key")
    llm_parser.add_argument("--api-key-env")
    llm_parser.add_argument("--temperature", type=float)
    llm_parser.add_argument("--max-tokens", type=int)
    llm_parser.add_argument("--thinking", choices=["on", "off"])
    llm_parser.add_argument("--thinking-budget-tokens", type=int)
    llm_parser.add_argument("--vision", choices=["on", "off"])
    llm_parser.add_argument("--reasoning-effort")

    run_parser = subparsers.add_parser("run", help="Fetch, detect new articles, and summarize them.")
    run_parser.add_argument("--limit-per-feed", type=int)
    run_parser.add_argument("--max-article-age-days", type=int, help="Override configured max article age for this run. Use 0 for all articles.")
    run_parser.add_argument("--html", type=Path, help="Write this run's processed articles to a readable HTML file.")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--loop", action="store_true", help="Run forever on an interval.")
    run_parser.add_argument("--interval-minutes", type=float, default=60.0)

    test_parser = subparsers.add_parser("test-run", help="Summarize sample articles without updating seen history.")
    test_parser.add_argument("--limit-per-feed", type=int, default=1, help="Articles to pull from each feed. Defaults to 1.")
    test_parser.add_argument("--all", action="store_true", help="Pull all articles from each selected feed.")
    test_parser.add_argument("--feed-id", help="Only test one feed id.")
    test_parser.add_argument("--max-article-age-days", type=int, help="Override configured max article age for this test run. Use 0 for all articles.")
    test_parser.add_argument("--html", type=Path, help="Write this test run's processed articles to a readable HTML file.")
    test_parser.add_argument("--dry-run", action="store_true", help="Fetch articles but do not call the LLM.")
    test_parser.add_argument("--save", action="store_true", help="Save summaries and mark articles seen.")
    test_parser.add_argument("--quiet-feeds", action="store_true", help="Hide per-feed diagnostics.")

    article_parser = subparsers.add_parser("article", help="Manage article preferences (starring).")
    article_sub = article_parser.add_subparsers(dest="article_command", required=True)
    article_star = article_sub.add_parser("star", help="Star an article to improve future recommendations.")
    article_star.add_argument("article_id", help="Article id prefix shown in 'summaries list'.")
    article_unstar = article_sub.add_parser("unstar", help="Remove a star from an article.")
    article_unstar.add_argument("article_id", help="Article id prefix.")
    article_sub.add_parser("list-starred", help="Show all starred articles.")

    review_parser = subparsers.add_parser("review", help="Launch TUI to review and vote on articles.")
    review_parser.add_argument("--limit", type=int, default=None, help="Max articles to load. Default: all.")

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    store = JsonStore(args.data)

    if args.command == "init":
        store.init()
        print(f"Initialized {args.data}")
        return

    store.init()
    if args.command == "feed":
        handle_feed(args, store)
    elif args.command == "config":
        handle_config(args, store)
    elif args.command == "reset":
        handle_reset(args, store)
    elif args.command == "summaries":
        handle_summaries(args, store)
    elif args.command == "article":
        handle_article(args, store)
    elif args.command == "review":
        handle_review(args, store)
    elif args.command == "run":
        if args.loop:
            while True:
                run_once(args, store)
                time.sleep(args.interval_minutes * 60)
        else:
            run_once(args, store)
    elif args.command == "test-run":
        test_run(args, store)


def handle_feed(args: argparse.Namespace, store: JsonStore) -> None:
    settings = store.settings()
    if args.feed_command == "add":
        feed_id = feed_id_for_url(args.url)
        title = args.title
        if not title:
            try:
                title = discover_feed_title(args.url, settings)
            except Exception:
                title = None
        feed = Feed(
            id=feed_id,
            url=args.url,
            title=title,
            enabled=not args.disabled,
            tags=parse_tags(args.tags),
        )
        store.upsert_feed(feed)
        print(f"Saved feed {feed.id}: {feed.title or feed.url}")
    elif args.feed_command == "remove":
        removed = store.remove_feed(args.feed_id)
        print("Removed feed." if removed else "No matching feed found.")
    elif args.feed_command == "update-url":
        updated = store.update_feed_url(args.feed_id, args.url, title=args.title)
        print("Updated feed URL." if updated else "No matching feed found.")
    elif args.feed_command == "discover":
        discoveries = discover_feed_urls(args.url, settings)
        if not discoveries:
            print("No RSS/Atom feeds discovered.")
            suggestions = known_feed_candidates(args.url)
            for suggestion in suggestions:
                print(f"Try: {suggestion}")
            return
        for discovery in discoveries:
            status = f"{discovery.entry_count} entrie(s)" if discovery.entry_count else f"warning: {discovery.error}"
            title = discovery.title or "Untitled"
            print(f"{discovery.url}\n  {title} | {status} | {discovery.source}")
    elif args.feed_command == "list":
        feeds = store.feeds(include_disabled=True)
        if not feeds:
            print("No feeds configured.")
            return
        for feed in feeds:
            status = "enabled" if feed.enabled else "disabled"
            title = feed.title or feed.url
            print(f"{feed.id}  {status}  {title}  {feed.url}")


def handle_config(args: argparse.Namespace, store: JsonStore) -> None:
    settings = store.settings()
    if args.config_command == "show":
        print(json.dumps(settings.to_dict(), indent=2, sort_keys=True))
        return
    if args.config_command == "set-app":
        if args.fetch_full_articles is not None:
            settings.fetch_full_articles = args.fetch_full_articles == "on"
        if args.request_timeout_seconds is not None:
            settings.request_timeout_seconds = args.request_timeout_seconds
        if args.retention_days is not None:
            settings.retention_days = args.retention_days if args.retention_days > 0 else None
        if args.max_article_age_days is not None:
            settings.max_article_age_days = args.max_article_age_days if args.max_article_age_days > 0 else None
        if args.user_agent is not None:
            settings.user_agent = args.user_agent
        if args.interests is not None:
            settings.interests = [t.strip() for t in args.interests.split(",") if t.strip()]
        if args.min_relevance is not None:
            settings.min_relevance_score = max(1, min(10, args.min_relevance))
        store.update_settings(settings)
        print("Updated app settings.")
        return
    if args.config_command == "set-llm":
        llm = settings.llm
        previous_provider = llm.provider
        for attr, arg_name in [
            ("provider", "provider"),
            ("model", "model"),
            ("base_url", "base_url"),
            ("api_key", "api_key"),
            ("api_key_env", "api_key_env"),
            ("temperature", "temperature"),
            ("max_tokens", "max_tokens"),
            ("thinking_budget_tokens", "thinking_budget_tokens"),
            ("reasoning_effort", "reasoning_effort"),
        ]:
            value = getattr(args, arg_name)
            if value is not None:
                setattr(llm, attr, value)
        if args.provider and args.base_url is None and args.provider != previous_provider:
            if args.provider == "openai":
                llm.base_url = "https://api.openai.com/v1"
            elif args.provider in {"lmstudio", "openai-compatible"}:
                llm.base_url = "http://localhost:1234/v1"
        if args.thinking is not None:
            llm.thinking_enabled = args.thinking == "on"
        if args.vision is not None:
            llm.vision_enabled = args.vision == "on"
        store.update_settings(AppSettings(llm=llm, fetch_full_articles=settings.fetch_full_articles, request_timeout_seconds=settings.request_timeout_seconds, user_agent=settings.user_agent))
        print("Updated LLM settings.")


def handle_reset(args: argparse.Namespace, store: JsonStore) -> None:
    if not args.yes:
        print("This clears seen article history so current feed items will be processed again.")
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Reset cancelled.")
            return
    seen_count, summary_count = store.reset_articles(keep_summaries=args.keep_summaries)
    print(f"Cleared {seen_count} seen article(s).")
    if args.keep_summaries:
        print("Kept existing summaries.")
    else:
        print(f"Cleared {summary_count} summary record(s).")


def handle_summaries(args: argparse.Namespace, store: JsonStore) -> None:
    if args.summaries_command == "list":
        limit = args.limit if (args.html or args.json) else (args.limit or 10)
        summaries = store.summaries(limit=limit, feed_id=args.feed_id)
        if args.html:
            write_summaries_html(args.html, summaries)
            print(f"Wrote {len(summaries)} summary record(s) to {args.html}")
            return
        if args.json:
            print(json.dumps(summaries, indent=2, sort_keys=True))
            return
        if not summaries:
            print("No summaries found.")
            return
        total = len(summaries)
        for index, summary in enumerate(summaries, start=1):
            title = summary.get("title") or "Untitled"
            url = summary.get("url") or ""
            created_at = summary.get("created_at") or "unknown"
            feed_id = summary.get("feed_id") or "unknown"
            provider = summary.get("provider") or "unknown"
            model = summary.get("model") or "unknown"
            article_id_short = (summary.get("article_id") or "")[:8]
            score = summary.get("relevance_score")
            score_str = f" | Score: {score}/10" if score is not None else ""
            body = (summary.get("summary") or "").strip() or "[empty summary]"
            print(f"{index}/{total}. [{article_id_short}] {title}")
            print(f"   URL: {url}")
            print(f"   Feed: {feed_id} | Created: {created_at} | LLM: {provider}/{model}{score_str}")
            print(f"   {body}")
            if index != len(summaries):
                print()


PAGE_SIZE = 10


def write_summaries_html(path: Path, summaries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now_iso()
    total = len(summaries)
    total_pages = max(1, -(-total // PAGE_SIZE))  # ceil division

    if summaries:
        card_parts = []
        for i, summary in enumerate(summaries):
            page = i // PAGE_SIZE + 1
            card_parts.append(f'<div data-page="{page}">{summary_card_html(summary, i + 1, total)}</div>')
        cards = "\n".join(card_parts)
    else:
        cards = '<p class="empty">No summaries found.</p>'

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synapse News Summaries</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f7f7f4;
      --text: #202124;
      --muted: #5f6368;
      --line: #d8d7d0;
      --card: #ffffff;
      --accent: #0b6bcb;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #151617;
        --text: #e8eaed;
        --muted: #a6adb5;
        --line: #303236;
        --card: #1d1f21;
        --accent: #8ab4f8;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      margin-bottom: 24px;
      padding-bottom: 16px;
    }}
    h1 {{
      font-size: 28px;
      line-height: 1.2;
      margin: 0 0 8px;
    }}
    .meta, .story-meta {{
      color: var(--muted);
      font-size: 14px;
    }}
    article {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 16px 0;
      padding: 18px;
    }}
    h2 {{
      font-size: 20px;
      line-height: 1.3;
      margin: 0 0 8px;
    }}
    a {{
      color: var(--accent);
      text-decoration-thickness: 1px;
      text-underline-offset: 3px;
    }}
    .summary {{
      margin-top: 14px;
      white-space: pre-wrap;
    }}
    .empty {{
      color: var(--muted);
      font-style: italic;
    }}
    .article-num {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 4px;
    }}
    [data-page] {{ display: none; }}
    [data-page].active {{ display: block; }}
    .pagination {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 32px;
      padding-top: 20px;
      border-top: 1px solid var(--line);
    }}
    .pagination button {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--accent);
      cursor: pointer;
      font-size: 15px;
      padding: 6px 14px;
    }}
    .pagination button:disabled {{
      color: var(--muted);
      cursor: default;
      opacity: 0.5;
    }}
    .pagination button:not(:disabled):hover {{
      border-color: var(--accent);
    }}
    .page-info {{
      color: var(--muted);
      font-size: 14px;
      margin: 0 4px;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Synapse News Summaries</h1>
      <div class="meta">Generated {escape(generated_at)} | {total} article(s) | {total_pages} page(s)</div>
    </header>
    {cards}
    <nav class="pagination" aria-label="Pagination">
      <button id="btn-first" title="First page" onclick="goTo(1)">&#171; First</button>
      <button id="btn-prev"  title="Previous page" onclick="goTo(cur-1)">&#8249; Prev</button>
      <span class="page-info" id="page-info"></span>
      <button id="btn-next"  title="Next page" onclick="goTo(cur+1)">Next &#8250;</button>
    </nav>
  </main>
  <script>
    var cur = 1;
    var totalPages = {total_pages};
    var totalArticles = {total};
    var pageSize = {PAGE_SIZE};
    function goTo(p) {{
      if (p < 1 || p > totalPages) return;
      document.querySelectorAll('[data-page].active').forEach(function(el) {{ el.classList.remove('active'); }});
      document.querySelectorAll('[data-page="' + p + '"]').forEach(function(el) {{ el.classList.add('active'); }});
      cur = p;
      var start = (p - 1) * pageSize + 1;
      var end = Math.min(p * pageSize, totalArticles);
      document.getElementById('page-info').textContent = start + '–' + end + ' of ' + totalArticles + ' · Page ' + p + ' of ' + totalPages;
      document.getElementById('btn-first').disabled = cur === 1;
      document.getElementById('btn-prev').disabled  = cur === 1;
      document.getElementById('btn-next').disabled  = cur === totalPages;
      window.scrollTo({{top: 0, behavior: 'smooth'}});
    }}
    goTo(1);
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def article_result_to_summary(result: dict) -> dict:
    article = result["article"]
    record: dict = {
        "article_id": article.id,
        "feed_id": article.feed_id,
        "title": article.title,
        "url": article.url,
        "published": article.published,
        "summary": result.get("summary") or result.get("status") or "",
        "created_at": result.get("created_at") or utc_now_iso(),
        "provider": result.get("provider") or "",
        "model": result.get("model") or "",
    }
    if article.relevance_score is not None:
        record["relevance_score"] = article.relevance_score
        record["relevance_reason"] = article.relevance_reason or ""
    return record


def summary_card_html(summary: dict, index: int | None = None, total: int | None = None) -> str:
    title = escape(str(summary.get("title") or "Untitled"))
    url = str(summary.get("url") or "")
    safe_url = escape(url, quote=True)
    created_at = escape(str(summary.get("created_at") or "unknown"))
    published = escape(str(summary.get("published") or "unknown"))
    feed_id = escape(str(summary.get("feed_id") or "unknown"))
    provider = escape(str(summary.get("provider") or "unknown"))
    model = escape(str(summary.get("model") or "unknown"))
    body = escape((summary.get("summary") or "").strip() or "[empty summary]")
    link = f'<a href="{safe_url}">{safe_url}</a>' if url else ""
    score = summary.get("relevance_score")
    score_html = f' | <strong>Score: {escape(str(score))}/10</strong>' if score is not None else ""
    num_html = f'<div class="article-num">#{index} of {total}</div>' if index is not None and total is not None else ""
    return f"""<article>
  {num_html}<h2>{title}</h2>
  <div class="story-meta">Feed {feed_id} | Published {published} | Saved {created_at} | LLM {provider}/{model}{score_html}</div>
  <div>{link}</div>
  <div class="summary">{body}</div>
</article>"""


def run_once(args: argparse.Namespace, store: JsonStore) -> None:
    data = store.load()
    settings = AppSettings.from_dict(data.get("settings"))
    apply_run_overrides(settings, args)
    purged_seen, purged_summaries = store.purge_older_than(settings.retention_days)
    if purged_seen or purged_summaries:
        print(f"Purged {purged_seen} seen article(s) and {purged_summaries} summary record(s) older than {settings.retention_days} day(s).")
        data = store.load()
    feeds = store.feeds()
    seen = set(data.get("seen_articles", {}).keys())
    articles = fetch_new_articles(feeds, settings, seen, limit_per_feed=args.limit_per_feed)
    if settings.interests and articles and not args.dry_run:
        articles = filter_and_rank_articles(articles, settings, store)
    results = process_articles(articles, settings, store, dry_run=args.dry_run, save=True)
    write_run_html_if_requested(args, results)


def test_run(args: argparse.Namespace, store: JsonStore) -> None:
    settings = store.settings()
    apply_run_overrides(settings, args)
    feeds = select_feeds(store.feeds(), args.feed_id)
    if args.feed_id and not feeds:
        print(f"No enabled feed found for id {args.feed_id}.")
        return
    limit_per_feed = None if args.all else args.limit_per_feed
    results = fetch_articles_by_feed(feeds, settings, seen=set(), limit_per_feed=limit_per_feed)
    if not args.quiet_feeds:
        print_feed_diagnostics(results)
    articles = [article for result in results for article in result.articles]
    if settings.interests and articles and not args.dry_run:
        articles = filter_and_rank_articles(articles, settings, store)
    print("Test run does not save summaries or mark articles seen unless --save is used.")
    processed = process_articles(articles, settings, store, dry_run=args.dry_run, save=args.save)
    write_run_html_if_requested(args, processed)


def apply_run_overrides(settings: AppSettings, args: argparse.Namespace) -> None:
    if getattr(args, "max_article_age_days", None) is not None:
        settings.max_article_age_days = parse_optional_positive_days(args.max_article_age_days)


def select_feeds(feeds: list[Feed], feed_id: str | None) -> list[Feed]:
    if not feed_id:
        return feeds
    return [feed for feed in feeds if feed.id == feed_id]


def print_feed_diagnostics(results: list[FeedFetchResult]) -> None:
    print("Feed diagnostics:")
    for result in results:
        label = result.feed.title or result.feed_title or result.feed.url
        detail = f"{result.feed.id} {label}: {result.entry_count} feed entrie(s), {len(result.articles)} selected"
        if result.error:
            detail += f" | warning: {result.error}"
        if result.entry_count == 0:
            suggestions = known_feed_candidates(result.feed.url)
            if suggestions:
                detail += f" | try: {suggestions[0]}"
        print(f"- {detail}")


def filter_and_rank_articles(articles: list[Article], settings: AppSettings, store: JsonStore) -> list[Article]:
    starred_titles = [v.get("title", "") for v in store.get_starred().values() if v.get("title")]
    downvoted_titles = [v.get("title", "") for v in store.get_downvoted().values() if v.get("title")]
    interests_str = ", ".join(settings.interests)
    total = len(articles)
    print(f"\nScoring {total} article(s) against interests: {interests_str}")
    scored: list[tuple[Article, int]] = []
    for i, article in enumerate(articles, start=1):
        try:
            sc, reason = score_article(article, settings.llm, settings.interests, starred_titles, downvoted_titles)
            article.relevance_score = sc
            article.relevance_reason = reason
            mark = "+" if sc >= settings.min_relevance_score else "-"
            print(f"  [{i}/{total}] [{mark}{sc:2}/10] {article.title[:65]}")
        except Exception as exc:
            article.relevance_score = 5
            article.relevance_reason = ""
            sc = 5
            print(f"  [{i}/{total}] [? 5/10] {article.title[:65]} (scoring error: {exc})")
        scored.append((article, sc))
    passed = [(a, s) for a, s in scored if s >= settings.min_relevance_score]
    filtered_count = len(scored) - len(passed)
    if filtered_count:
        print(f"\nFiltered out {filtered_count} article(s) below score {settings.min_relevance_score}/10.")
    deduped = deduplicate_articles(passed)
    dupe_count = len(passed) - len(deduped)
    if dupe_count:
        print(f"Removed {dupe_count} duplicate article(s).")
    deduped.sort(key=lambda x: x[1], reverse=True)
    print(f"{len(deduped)} article(s) selected.\n")
    return [a for a, _ in deduped]


def handle_article(args: argparse.Namespace, store: JsonStore) -> None:
    if args.article_command == "star":
        summaries = store.summaries(limit=None)
        match = _find_summary_by_id_prefix(args.article_id, summaries)
        if not match:
            print(f"No article found matching id prefix '{args.article_id}'.")
            return
        store.star_article(match["article_id"], {
            "title": match.get("title"),
            "feed_id": match.get("feed_id"),
            "url": match.get("url"),
            "summary": match.get("summary"),
        })
        print(f"Starred: {match.get('title')}")
    elif args.article_command == "unstar":
        starred = store.get_starred()
        article_id = _resolve_id_prefix(args.article_id, starred)
        if not article_id:
            print(f"No starred article found matching id prefix '{args.article_id}'.")
            return
        store.unstar_article(article_id)
        print("Unstarred article.")
    elif args.article_command == "list-starred":
        starred = store.get_starred()
        if not starred:
            print("No starred articles.")
            return
        for i, (article_id, meta) in enumerate(starred.items(), start=1):
            title = meta.get("title") or "Untitled"
            starred_at = meta.get("starred_at") or "unknown"
            print(f"{i}. [{article_id[:8]}] {title}")
            print(f"   Starred: {starred_at}")
            if i != len(starred):
                print()


def _find_summary_by_id_prefix(prefix: str, summaries: list[dict]) -> dict | None:
    for summary in summaries:
        if (summary.get("article_id") or "").startswith(prefix):
            return summary
    return None


def _resolve_id_prefix(prefix: str, mapping: dict) -> str | None:
    if prefix in mapping:
        return prefix
    matches = [k for k in mapping if k.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def write_run_html_if_requested(args: argparse.Namespace, results: list[dict]) -> None:
    html_path = getattr(args, "html", None)
    if not html_path:
        return
    summaries = [article_result_to_summary(result) for result in results]
    write_summaries_html(html_path, summaries)
    print(f"Wrote {len(summaries)} processed article(s) to {html_path}")


def process_articles(articles: list, settings: AppSettings, store: JsonStore, dry_run: bool, save: bool) -> list[dict]:
    results: list[dict] = []
    if not articles:
        print("No new articles.")
        return results
    total = len(articles)
    print(f"Found {total} new article(s).")
    if not dry_run:
        try:
            check_llm_available(settings.llm)
        except LLMError as exc:
            print(f"LLM check failed: {exc}")
            print("No articles were marked seen. Fix the LLM settings or use `synapse-news config set-llm --provider none` for fallback summaries.")
            for article in articles:
                results.append({"article": article, "status": f"LLM check failed: {exc}", "created_at": utc_now_iso(), "provider": settings.llm.provider, "model": settings.llm.model})
            return results
    for i, article in enumerate(articles, start=1):
        print(f"\n[{i}/{total}] {article.title}\n{article.url}")
        summary_text = ""
        if dry_run:
            results.append({"article": article, "status": "Dry run: summary not requested.", "created_at": utc_now_iso(), "provider": settings.llm.provider, "model": settings.llm.model})
        else:
            try:
                summary_text = summarize(article, settings.llm)
            except (LLMError, httpx.HTTPError, KeyError) as exc:
                print(f"Summary failed: {exc}")
                print("Article was not marked seen, so it can be retried on the next run.")
                results.append({"article": article, "status": f"Summary failed: {exc}", "created_at": utc_now_iso(), "provider": settings.llm.provider, "model": settings.llm.model})
                continue
            print(summary_text)
            created_at = utc_now_iso()
            summary_record: dict = {
                "article_id": article.id,
                "feed_id": article.feed_id,
                "title": article.title,
                "url": article.url,
                "published": article.published,
                "summary": summary_text,
                "created_at": created_at,
                "provider": settings.llm.provider,
                "model": settings.llm.model,
            }
            if article.relevance_score is not None:
                summary_record["relevance_score"] = article.relevance_score
                summary_record["relevance_reason"] = article.relevance_reason or ""
            results.append({"article": article, "summary": summary_text, "created_at": created_at, "provider": settings.llm.provider, "model": settings.llm.model})
            if save:
                store.add_summary(summary_record)
        if save and not dry_run:
            store.mark_seen(
                article.id,
                {
                    "feed_id": article.feed_id,
                    "title": article.title,
                    "url": article.url,
                    "published": article.published,
                },
            )
    return results


def handle_review(args: argparse.Namespace, store: JsonStore) -> None:
    try:
        from .tui import ReviewApp
    except ImportError:
        print("The 'review' command requires textual. Install it with: pip install 'textual>=0.52.0'")
        return
    ReviewApp(store, limit=args.limit).run()


if __name__ == "__main__":
    main()
