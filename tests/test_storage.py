import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from synapse_news.feeds import is_entry_too_old
from synapse_news.models import AppSettings, Feed
from synapse_news.storage import JsonStore, parse_datetime
from synapse_news.llm import clean_summary_text, extract_openai_compatible_text


class JsonStoreTest(unittest.TestCase):
    def test_json_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonStore(Path(directory) / "state.json")
            store.init()
            feed = Feed(id="example", url="https://example.com/rss", title="Example")
            store.upsert_feed(feed)

            self.assertEqual(store.feeds()[0].title, "Example")

            article_id = "article-1"
            self.assertFalse(store.has_seen(article_id))
            store.mark_seen(article_id, {"title": "A"})
            self.assertTrue(store.has_seen(article_id))

            store.add_summary({"article_id": article_id, "feed_id": "example", "summary": "A"})
            store.add_summary({"article_id": "article-2", "feed_id": "other", "summary": "B"})

            self.assertEqual(len(store.summaries(limit=1)), 1)
            self.assertEqual(store.summaries(feed_id="example")[0]["summary"], "A")

            seen_count, summary_count = store.reset_articles()

            self.assertEqual(seen_count, 1)
            self.assertEqual(summary_count, 2)
            self.assertFalse(store.has_seen(article_id))
            self.assertEqual(store.load()["summaries"], [])

    def test_extract_openai_compatible_text(self):
        self.assertEqual(
            extract_openai_compatible_text({"choices": [{"message": {"content": " hello "}}]}),
            "hello",
        )
        self.assertEqual(
            extract_openai_compatible_text({"choices": [{"message": {"content": [{"text": "hello"}]}}]}),
            "hello",
        )
        self.assertEqual(
            clean_summary_text("Here is my thinking process.\n\nSummary:\nFinal only."),
            "Summary:\nFinal only.",
        )
        self.assertEqual(
            clean_summary_text("Draft notes first.\n\nWhy it matters:\nFinal only."),
            "Why it matters:\nFinal only.",
        )
        self.assertEqual(clean_summary_text("Here is my thinking process with no final."), "")
        self.assertEqual(
            extract_openai_compatible_text({"choices": [{"message": {"reasoning_content": "thinking text"}}]}),
            "",
        )

    def test_purge_older_than(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonStore(Path(directory) / "state.json")
            old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
            recent = datetime.now(timezone.utc).isoformat()

            store.save(
                {
                    "version": 1,
                    "settings": AppSettings().to_dict(),
                    "feeds": [],
                    "seen_articles": {
                        "old": {"seen_at": old, "title": "Old"},
                        "recent": {"seen_at": recent, "title": "Recent"},
                    },
                    "summaries": [
                        {"article_id": "old", "created_at": old, "summary": "Old"},
                        {"article_id": "recent", "created_at": recent, "summary": "Recent"},
                    ],
                }
            )

            purged_seen, purged_summaries = store.purge_older_than(14)

            self.assertEqual(purged_seen, 1)
            self.assertEqual(purged_summaries, 1)
            self.assertIn("recent", store.load()["seen_articles"])
            self.assertEqual(store.load()["summaries"][0]["article_id"], "recent")

    def test_settings_retention_days(self):
        self.assertEqual(AppSettings.from_dict({}).retention_days, 7)
        self.assertIsNone(AppSettings.from_dict({"retention_days": 0}).retention_days)
        self.assertEqual(AppSettings.from_dict({"retention_days": 30}).retention_days, 30)
        self.assertIsNone(AppSettings.from_dict({}).max_article_age_days)
        self.assertIsNone(AppSettings.from_dict({"max_article_age_days": 0}).max_article_age_days)
        self.assertEqual(AppSettings.from_dict({"max_article_age_days": 3}).max_article_age_days, 3)
        self.assertEqual(parse_datetime("2026-04-25T12:00:00Z").tzinfo, timezone.utc)

    def test_entry_age_filter(self):
        class Entry:
            published = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%a, %d %b %Y %H:%M:%S %z")

        self.assertFalse(is_entry_too_old(Entry(), None))
        self.assertFalse(is_entry_too_old(Entry(), 7))
        self.assertTrue(is_entry_too_old(Entry(), 1))


if __name__ == "__main__":
    unittest.main()
