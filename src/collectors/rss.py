import re

import feedparser

from src.core.models import Item

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = _TAG_RE.sub("", text or "")
    return _WHITESPACE_RE.sub(" ", text).strip()


def fetch_rss(url: str, source_id: str) -> list[Item]:
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries:
        item_key = entry.get("id") or entry.get("link")
        items.append(
            Item(
                source_id=source_id,
                item_key=item_key,
                title=_normalize(entry.get("title", "")),
                url=entry.get("link", ""),
                content=_normalize(entry.get("summary", "") or entry.get("description", "")),
                published_at=entry.get("published") or entry.get("updated"),
            )
        )
    return items
