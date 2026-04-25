from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from .models import AppSettings, Feed


@dataclass(slots=True)
class Article:
    id: str
    feed_id: str
    feed_title: str
    title: str
    url: str
    published: str | None
    excerpt: str
    content: str
    relevance_score: int | None = None
    relevance_reason: str | None = None


@dataclass(slots=True)
class FeedFetchResult:
    feed: Feed
    feed_title: str
    entry_count: int
    selected_count: int
    articles: list[Article]
    error: str | None = None


@dataclass(slots=True)
class FeedDiscovery:
    url: str
    title: str | None
    entry_count: int
    source: str
    error: str | None = None


def feed_id_for_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def article_id_for(feed_id: str, url: str, title: str) -> str:
    source = url or f"{feed_id}:{title}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def parse_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [tag.strip() for tag in tags.split(",") if tag.strip()]


def normalize_published(entry: object) -> str | None:
    published = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if not published:
        return None
    try:
        return parsedate_to_datetime(published).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return str(published)


def entry_published_datetime(entry: object) -> datetime | None:
    published = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if not published:
        return None
    try:
        parsed = parsedate_to_datetime(published)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_entry_too_old(entry: object, max_article_age_days: int | None) -> bool:
    if max_article_age_days is None:
        return False
    published = entry_published_datetime(entry)
    if published is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_article_age_days)
    return published < cutoff


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    return " ".join(soup.get_text(" ").split())


def fetch_article_text(url: str, settings: AppSettings) -> str:
    headers = {"User-Agent": settings.user_agent}
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    return html_to_text(response.text)


def discover_feed_title(url: str, settings: AppSettings) -> str | None:
    parsed = feedparser.parse(url, agent=settings.user_agent)
    return parsed.feed.get("title") if parsed.feed else None


def discover_feed_urls(url: str, settings: AppSettings) -> list[FeedDiscovery]:
    candidates = candidate_feed_urls(url, settings)
    discoveries: list[FeedDiscovery] = []
    seen: set[str] = set()
    for candidate, source in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        parsed = feedparser.parse(candidate, agent=settings.user_agent)
        if parsed.entries:
            discoveries.append(
                FeedDiscovery(
                    url=candidate,
                    title=parsed.feed.get("title"),
                    entry_count=len(parsed.entries),
                    source=source,
                )
            )
        elif getattr(parsed, "bozo", False) and getattr(parsed, "bozo_exception", None):
            discoveries.append(
                FeedDiscovery(
                    url=candidate,
                    title=None,
                    entry_count=0,
                    source=source,
                    error=str(parsed.bozo_exception),
                )
            )
    return discoveries


def candidate_feed_urls(url: str, settings: AppSettings) -> list[tuple[str, str]]:
    candidates = [(url, "provided URL")]
    candidates.extend((candidate, "known pattern") for candidate in known_feed_candidates(url))
    headers = {"User-Agent": settings.user_agent}
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError:
        return candidates
    soup = BeautifulSoup(response.text, "html.parser")
    for link in soup.find_all("link"):
        rel = " ".join(link.get("rel", [])).lower()
        type_ = (link.get("type") or "").lower()
        href = link.get("href")
        if not href:
            continue
        if "alternate" in rel and any(marker in type_ for marker in ("rss", "atom", "xml")):
            candidates.append((urljoin(str(response.url), href), "HTML alternate link"))
    return candidates


def known_feed_candidates(url: str) -> list[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    candidates = {
        "macrumors.com": ["https://feeds.macrumors.com/MacRumors-All"],
        "openai.com": ["https://openai.com/news/rss.xml"],
        "wired.com": ["https://www.wired.com/feed/rss"],
        "slashdot.org": ["http://rss.slashdot.org/Slashdot/slashdotMain"],
        "arstechnica.com": ["https://feeds.arstechnica.com/arstechnica/index"],
        "engadget.com": ["https://www.engadget.com/rss.xml"],
        "techmeme.com": ["https://www.techmeme.com/feed.xml"],
        "macworld.com": ["https://www.macworld.com/feed"],
        "deepmind.google": ["https://deepmind.google/blog/rss.xml"],
    }
    return candidates.get(host, [])


def fetch_new_articles(feeds: list[Feed], settings: AppSettings, seen: set[str], limit_per_feed: int | None = None) -> list[Article]:
    results = fetch_articles_by_feed(feeds, settings, seen, limit_per_feed=limit_per_feed)
    return [article for result in results for article in result.articles]


def fetch_articles_by_feed(feeds: list[Feed], settings: AppSettings, seen: set[str], limit_per_feed: int | None = None) -> list[FeedFetchResult]:
    results: list[FeedFetchResult] = []
    for feed in feeds:
        results.append(fetch_feed_articles(feed, settings, seen, limit_per_feed=limit_per_feed))
    return results


def fetch_feed_articles(feed: Feed, settings: AppSettings, seen: set[str], limit_per_feed: int | None = None) -> FeedFetchResult:
    articles: list[Article] = []
    try:
        parsed = feedparser.parse(feed.url, agent=settings.user_agent)
    except Exception as exc:
        return FeedFetchResult(feed=feed, feed_title=feed.title or feed.url, entry_count=0, selected_count=0, articles=[], error=str(exc))
    feed_title = feed.title or parsed.feed.get("title") or feed.url
    error = str(parsed.bozo_exception) if getattr(parsed, "bozo", False) and getattr(parsed, "bozo_exception", None) else None
    entries = parsed.entries[:limit_per_feed] if limit_per_feed else parsed.entries
    for entry in entries:
        if is_entry_too_old(entry, settings.max_article_age_days):
            continue
        title = entry.get("title", "Untitled")
        url = entry.get("link", "")
        article_id = article_id_for(feed.id, url, title)
        if article_id in seen:
            continue
        excerpt = html_to_text(entry.get("summary", "") or entry.get("description", ""))
        content = excerpt
        if settings.fetch_full_articles and url:
            try:
                fetched = fetch_article_text(url, settings)
                if fetched:
                    content = fetched
            except (httpx.HTTPError, httpx.InvalidURL):
                content = excerpt
        articles.append(
            Article(
                id=article_id,
                feed_id=feed.id,
                feed_title=feed_title,
                title=title,
                url=url,
                published=normalize_published(entry),
                excerpt=excerpt,
                content=content[:12000],
            )
        )
    return FeedFetchResult(
        feed=feed,
        feed_title=feed_title,
        entry_count=len(parsed.entries),
        selected_count=len(entries),
        articles=articles,
        error=error,
    )


_STOPWORDS = {"a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "it", "its"}


def _title_tokens(title: str) -> set[str]:
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def deduplicate_articles(articles_with_scores: list[tuple[Article, int]]) -> list[tuple[Article, int]]:
    """Keep the highest-scored article per story cluster; removes near-duplicate titles."""
    kept: list[tuple[Article, int]] = []
    kept_tokens: list[set[str]] = []
    for article, score in articles_with_scores:
        tokens = _title_tokens(article.title)
        is_dupe = False
        if len(tokens) >= 4:
            for existing_tokens in kept_tokens:
                if not existing_tokens:
                    continue
                overlap = len(tokens & existing_tokens) / max(len(tokens), len(existing_tokens))
                if overlap >= 0.6:
                    is_dupe = True
                    break
        if not is_dupe:
            kept.append((article, score))
            kept_tokens.append(tokens)
    return kept
