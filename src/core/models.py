from dataclasses import dataclass


@dataclass
class AnalysisResult:
    summary: str
    beginner_note: str
    importance: int
    tags: list[str]
    should_notify: bool
    reason: str


@dataclass
class Item:
    source_id: str
    item_key: str       # RSS: entry id / HTML: 本文ハッシュ(将来)
    title: str
    url: str
    content: str        # 正規化済み本文
    published_at: str | None
