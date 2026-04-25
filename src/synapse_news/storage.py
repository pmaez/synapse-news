from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import tempfile
from pathlib import Path
from typing import Any

from .models import AppSettings, Feed, utc_now_iso


DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "settings": AppSettings().to_dict(),
    "feeds": [],
    "seen_articles": {},
    "summaries": [],
    "starred_articles": {},
    "downvoted_articles": {},
    "llm_profiles": {},
}


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def _with_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        merged = json.loads(json.dumps(DEFAULT_STATE))
        merged.update(data)
        merged["settings"] = {
            **DEFAULT_STATE["settings"],
            **data.get("settings", {}),
            "llm": {
                **DEFAULT_STATE["settings"]["llm"],
                **data.get("settings", {}).get("llm", {}),
            },
        }
        return merged

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(DEFAULT_STATE))
        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return self._with_defaults(data)

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            tmp_path = Path(file.name)
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")
        tmp_path.replace(self.path)

    @contextmanager
    def locked_data(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                data = self._read_unlocked()
                yield data
                self._write_unlocked(data)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def load(self) -> dict[str, Any]:
        return self._read_unlocked()

    def save(self, data: dict[str, Any]) -> None:
        with self.locked_data() as locked:
            locked.clear()
            locked.update(data)

    def init(self) -> None:
        if not self.path.exists():
            self.save(DEFAULT_STATE)

    def settings(self) -> AppSettings:
        return AppSettings.from_dict(self.load().get("settings"))

    def update_settings(self, settings: AppSettings) -> None:
        with self.locked_data() as data:
            data["settings"] = settings.to_dict()

    def feeds(self, include_disabled: bool = False) -> list[Feed]:
        feeds = [Feed.from_dict(item) for item in self.load().get("feeds", [])]
        if include_disabled:
            return feeds
        return [feed for feed in feeds if feed.enabled]

    def upsert_feed(self, feed: Feed) -> None:
        with self.locked_data() as data:
            feeds = data.setdefault("feeds", [])
            for index, existing in enumerate(feeds):
                if existing["id"] == feed.id:
                    feeds[index] = feed.to_dict()
                    break
            else:
                feeds.append(feed.to_dict())

    def remove_feed(self, feed_id: str) -> bool:
        with self.locked_data() as data:
            feeds = data.setdefault("feeds", [])
            updated = [feed for feed in feeds if feed["id"] != feed_id]
            if len(updated) == len(feeds):
                return False
            data["feeds"] = updated
            return True

    def update_feed_url(self, feed_id: str, url: str, title: str | None = None) -> bool:
        with self.locked_data() as data:
            for feed in data.setdefault("feeds", []):
                if feed["id"] == feed_id:
                    feed["url"] = url
                    if title is not None:
                        feed["title"] = title
                    return True
            return False

    def has_seen(self, article_id: str) -> bool:
        return article_id in self.load().get("seen_articles", {})

    def mark_seen(self, article_id: str, metadata: dict[str, Any]) -> None:
        with self.locked_data() as data:
            seen = data.setdefault("seen_articles", {})
            seen[article_id] = {"seen_at": utc_now_iso(), **metadata}

    def add_summary(self, summary: dict[str, Any]) -> None:
        with self.locked_data() as data:
            data.setdefault("summaries", []).append(summary)

    def summaries(self, limit: int | None = None, feed_id: str | None = None) -> list[dict[str, Any]]:
        summaries = list(self.load().get("summaries", []))
        if feed_id:
            summaries = [summary for summary in summaries if summary.get("feed_id") == feed_id]
        summaries.reverse()
        if limit is not None:
            summaries = summaries[:limit]
        return summaries

    def purge_older_than(self, retention_days: int | None) -> tuple[int, int]:
        if retention_days is None:
            return 0, 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self.locked_data() as data:
            seen = data.get("seen_articles", {})
            kept_seen = {
                article_id: metadata
                for article_id, metadata in seen.items()
                if not is_record_older_than(metadata, cutoff, ("seen_at", "published"))
            }
            summaries = data.get("summaries", [])
            kept_summaries = [
                summary
                for summary in summaries
                if not is_record_older_than(summary, cutoff, ("created_at", "published"))
            ]
            data["seen_articles"] = kept_seen
            data["summaries"] = kept_summaries
            return len(seen) - len(kept_seen), len(summaries) - len(kept_summaries)

    def star_article(self, article_id: str, metadata: dict[str, Any]) -> None:
        with self.locked_data() as data:
            data.setdefault("starred_articles", {})[article_id] = {"starred_at": utc_now_iso(), **metadata}

    def unstar_article(self, article_id: str) -> bool:
        with self.locked_data() as data:
            starred = data.setdefault("starred_articles", {})
            if article_id not in starred:
                return False
            del starred[article_id]
            return True

    def get_starred(self) -> dict[str, Any]:
        return self.load().get("starred_articles", {})

    def downvote_article(self, article_id: str, metadata: dict[str, Any]) -> None:
        with self.locked_data() as data:
            data.setdefault("downvoted_articles", {})[article_id] = {"downvoted_at": utc_now_iso(), **metadata}

    def remove_downvote(self, article_id: str) -> bool:
        with self.locked_data() as data:
            downvoted = data.setdefault("downvoted_articles", {})
            if article_id not in downvoted:
                return False
            del downvoted[article_id]
            return True

    def get_downvoted(self) -> dict[str, Any]:
        return self.load().get("downvoted_articles", {})

    def save_llm_profile(self, name: str, llm: "LLMSettings") -> None:
        with self.locked_data() as data:
            data.setdefault("llm_profiles", {})[name] = llm.to_dict()

    def get_llm_profile(self, name: str) -> "LLMSettings | None":
        from .models import LLMSettings
        profiles = self.load().get("llm_profiles", {})
        if name not in profiles:
            return None
        return LLMSettings.from_dict(profiles[name])

    def delete_llm_profile(self, name: str) -> bool:
        with self.locked_data() as data:
            profiles = data.setdefault("llm_profiles", {})
            if name not in profiles:
                return False
            del profiles[name]
            return True

    def list_llm_profiles(self) -> dict[str, Any]:
        return self.load().get("llm_profiles", {})

    def reset_articles(self, keep_summaries: bool = False) -> tuple[int, int]:
        with self.locked_data() as data:
            seen_count = len(data.get("seen_articles", {}))
            summary_count = len(data.get("summaries", []))
            data["seen_articles"] = {}
            if not keep_summaries:
                data["summaries"] = []
            return seen_count, 0 if keep_summaries else summary_count


def is_record_older_than(record: dict[str, Any], cutoff: datetime, fields: tuple[str, ...]) -> bool:
    for field in fields:
        value = record.get(field)
        if not value:
            continue
        parsed = parse_datetime(value)
        if parsed is None:
            continue
        return parsed < cutoff
    return False


def parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
