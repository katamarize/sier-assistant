import os

import requests
from dotenv import load_dotenv

from src.core.storage import NotifiableItem

load_dotenv()

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
SLACK_STOCK_WEBHOOK_URL = os.environ.get("SLACK_STOCK_WEBHOOK_URL", "")

# 1メッセージに詰める上限。超過分は分割送信する。
# Block Kitは1メッセージ50ブロックまでのため、10件×最大3ブロック+ヘッダー+区切りでも上限内に収まる
MAX_ITEMS_PER_MESSAGE = 10

_TIMEOUT_SECONDS = 10


class SlackNotifyError(Exception):
    pass


def _escape(text: str) -> str:
    # Slackのmrkdwnで特別扱いされる3文字のみエスケープする(仕様で定められた最小セット)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _item_blocks(item: NotifiableItem) -> list[dict]:
    stars = "★" * item.importance + "☆" * (5 - item.importance)
    section = (
        f"*<{_escape(item.url)}|{_escape(item.title)}>*\n"
        f"{_escape(item.summary)}"
    )
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": section}}]

    context = [f"重要度 {stars}"]
    if item.beginner_note:
        context.append(f"💡 {_escape(item.beginner_note)}")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "  |  ".join(context)}],
        }
    )
    return blocks


def build_payload(
    items: list[NotifiableItem], header: str, part: tuple[int, int] | None = None
) -> dict:
    suffix = f" ({part[0]}/{part[1]})" if part else ""
    title = f"{header} {len(items)}件{suffix}"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}}
    ]
    for i, item in enumerate(items):
        if i:
            blocks.append({"type": "divider"})
        blocks.extend(_item_blocks(item))

    # textはblocks非対応クライアント・プッシュ通知プレビュー用のフォールバック
    return {"text": title, "blocks": blocks}


def send(payload: dict, webhook_url: str) -> None:
    if not webhook_url:
        raise SlackNotifyError("Webhook URLが未設定(.env を確認)")
    try:
        response = requests.post(webhook_url, json=payload, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as e:
        raise SlackNotifyError(f"Slackへの送信に失敗: {e}") from e
