import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.core.models import AnalysisResult, Item

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "data/assistant.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    source_id    TEXT,
    item_key     TEXT,
    content_hash TEXT,
    first_seen   TEXT,
    PRIMARY KEY (source_id, item_key)
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,
    source_id     TEXT,
    title         TEXT,
    url           TEXT,
    content       TEXT,
    status        TEXT DEFAULT 'pending',
    importance    INTEGER,
    summary       TEXT,
    beginner_note TEXT,
    tags          TEXT,
    should_notify INTEGER,
    reason        TEXT,
    created_at    TEXT
);
"""


@dataclass
class PendingItem:
    id: int
    title: str
    content: str


@dataclass
class NotifiableItem:
    id: int
    source_id: str
    title: str
    url: str
    summary: str
    beginner_note: str
    importance: int


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def is_seen(source_id: str, item_key: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_items WHERE source_id = ? AND item_key = ?",
            (source_id, item_key),
        ).fetchone()
    return row is not None


def mark_seen(item: Item) -> None:
    content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_items "
            "(source_id, item_key, content_hash, first_seen) VALUES (?, ?, ?, ?)",
            (item.source_id, item.item_key, content_hash, datetime.now(timezone.utc).isoformat()),
        )


def save_item(item: Item) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO items (source_id, title, url, content, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (item.source_id, item.title, item.url, item.content, datetime.now(timezone.utc).isoformat()),
        )


def fetch_pending_items() -> list[PendingItem]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, title, content FROM items WHERE status = 'pending'").fetchall()
    return [PendingItem(id=row[0], title=row[1], content=row[2]) for row in rows]


def fetch_notifiable_items() -> list[NotifiableItem]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, source_id, title, url, summary, beginner_note, importance "
            "FROM items WHERE status = 'analyzed' AND should_notify = 1"
        ).fetchall()
    return [NotifiableItem(*row) for row in rows]


def update_items_status(item_ids: list[int], status: str) -> None:
    if not item_ids:
        return
    with _connect() as conn:
        conn.executemany(
            "UPDATE items SET status = ? WHERE id = ?",
            [(status, item_id) for item_id in item_ids],
        )


def update_item_analysis(item_id: int, result: AnalysisResult, status: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE items SET status = ?, importance = ?, summary = ?, beginner_note = ?, "
            "tags = ?, should_notify = ?, reason = ? WHERE id = ?",
            (
                status,
                result.importance,
                result.summary,
                result.beginner_note,
                json.dumps(result.tags, ensure_ascii=False),
                int(result.should_notify),
                result.reason,
                item_id,
            ),
        )
