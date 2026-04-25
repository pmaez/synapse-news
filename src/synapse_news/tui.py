from __future__ import annotations

import webbrowser

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, ListItem, ListView, Static

from .storage import JsonStore


def _short_date(iso: str | None) -> str:
    return (iso or "")[:10]


class ReviewApp(App[None]):
    TITLE = "Synapse News · Review"

    CSS = """
    #body {
        layout: horizontal;
        height: 1fr;
    }
    #list-panel {
        width: 46%;
        border-right: tall $primary-darken-3;
    }
    #article-list {
        height: 1fr;
    }
    #detail-panel {
        width: 54%;
        overflow-y: scroll;
        padding: 1 2;
    }
    #detail {
        height: auto;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "↓", show=False),
        Binding("k", "cursor_up", "↑", show=False),
        Binding("u", "upvote", "↑ Upvote"),
        Binding("d", "downvote", "↓ Downvote"),
        Binding("o", "open_url", "Open URL"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, store: JsonStore, limit: int | None = None) -> None:
        super().__init__()
        self.store = store
        self._limit = limit
        self._summaries: list[dict] = []
        self._upvoted: dict = {}
        self._downvoted: dict = {}

    def _load(self) -> None:
        self._summaries = self.store.summaries(limit=self._limit)
        self._upvoted = self.store.get_starred()
        self._downvoted = self.store.get_downvoted()

    def _item_text(self, idx: int) -> Text:
        s = self._summaries[idx]
        aid = s.get("article_id", "")
        if aid in self._upvoted:
            vote = "↑"
        elif aid in self._downvoted:
            vote = "↓"
        else:
            vote = " "
        score = s.get("relevance_score")
        score_s = f"{score:2d}" if score is not None else "  "
        title = (s.get("title") or "Untitled")[:58]
        return Text(f" {vote} [{score_s}]  {title}", no_wrap=True)

    def _make_items(self) -> list[ListItem]:
        return [
            ListItem(Static(self._item_text(i)), id=f"sitem-{i}")
            for i in range(len(self._summaries))
        ]

    def _refresh_item(self, idx: int) -> None:
        try:
            self.query_one(f"#sitem-{idx} Static", Static).update(self._item_text(idx))
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        self._load()
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="list-panel"):
                yield ListView(*self._make_items(), id="article-list")
            with ScrollableContainer(id="detail-panel"):
                yield Static(Text(""), id="detail")
        yield Footer()

    def on_mount(self) -> None:
        lv = self.query_one("#article-list", ListView)
        lv.focus()
        if self._summaries:
            self._show_detail(0)

    @on(ListView.Highlighted)
    def _on_highlight(self, event: ListView.Highlighted) -> None:
        idx = self.query_one("#article-list", ListView).index
        if idx is not None and idx < len(self._summaries):
            self._show_detail(idx)

    def _show_detail(self, idx: int) -> None:
        s = self._summaries[idx]
        aid = s.get("article_id", "")

        title = s.get("title") or "Untitled"
        url = s.get("url") or ""
        feed = s.get("feed_id") or ""
        score = s.get("relevance_score")
        score_s = f"{score}/10" if score is not None else "—"
        reason = (s.get("relevance_reason") or "").strip()
        saved = _short_date(s.get("created_at"))
        published = _short_date(s.get("published"))
        provider = s.get("provider") or ""
        model = s.get("model") or ""
        body = (s.get("summary") or "").strip()

        badges = []
        if aid in self._upvoted:
            badges.append("↑ upvoted")
        if aid in self._downvoted:
            badges.append("↓ downvoted")

        lines = [title, "─" * min(len(title), 60), ""]
        if badges:
            lines += ["  ".join(badges), ""]
        lines += [
            f"Score:     {score_s}",
            f"Feed:      {feed}",
            f"Published: {published}",
            f"Saved:     {saved}",
            f"LLM:       {provider}/{model}",
            f"URL:       {url}",
        ]
        if reason:
            lines += ["", f"Reason: {reason}"]
        lines += ["", "Summary:", "", body]

        self.query_one("#detail", Static).update(Text("\n".join(lines)))

    def _current_idx(self) -> int | None:
        idx = self.query_one("#article-list", ListView).index
        if idx is not None and idx < len(self._summaries):
            return idx
        return None

    def action_upvote(self) -> None:
        idx = self._current_idx()
        if idx is None:
            return
        s = self._summaries[idx]
        aid = s.get("article_id", "")
        if aid in self._upvoted:
            self.store.unstar_article(aid)
            self._upvoted.pop(aid, None)
        else:
            self.store.star_article(aid, {
                "title": s.get("title"),
                "feed_id": s.get("feed_id"),
                "url": s.get("url"),
                "summary": s.get("summary"),
            })
            self._upvoted[aid] = {"title": s.get("title")}
            if aid in self._downvoted:
                self.store.remove_downvote(aid)
                self._downvoted.pop(aid, None)
        self._refresh_item(idx)
        self._show_detail(idx)

    def action_downvote(self) -> None:
        idx = self._current_idx()
        if idx is None:
            return
        s = self._summaries[idx]
        aid = s.get("article_id", "")
        if aid in self._downvoted:
            self.store.remove_downvote(aid)
            self._downvoted.pop(aid, None)
        else:
            self.store.downvote_article(aid, {
                "title": s.get("title"),
                "feed_id": s.get("feed_id"),
                "url": s.get("url"),
            })
            self._downvoted[aid] = {"title": s.get("title")}
            if aid in self._upvoted:
                self.store.unstar_article(aid)
                self._upvoted.pop(aid, None)
        self._refresh_item(idx)
        self._show_detail(idx)

    def action_open_url(self) -> None:
        idx = self._current_idx()
        if idx is None:
            return
        url = self._summaries[idx].get("url") or ""
        if url:
            webbrowser.open(url)

    def action_cursor_down(self) -> None:
        self.query_one("#article-list", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#article-list", ListView).action_cursor_up()
