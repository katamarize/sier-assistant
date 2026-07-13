"""Step 2 動作確認用スクリプト。

AWS What's New のRSSを取得し、新着のみをDBに保存する。
同一フィードを2回実行し、2回目は新着0件になることを確認する。
"""

import sys

from src.collectors.rss import fetch_rss
from src.core import storage
from src.core.diff import filter_new_items

sys.stdout.reconfigure(encoding="utf-8")

SOURCE_ID = "aws-whats-new"
FEED_URL = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"


def main() -> None:
    storage.init_db()

    items = fetch_rss(FEED_URL, SOURCE_ID)
    print(f"取得件数: {len(items)}")

    new_items = filter_new_items(items)
    print(f"新着件数: {len(new_items)}")

    for item in new_items:
        storage.save_item(item)
        storage.mark_seen(item)
        print(f"  + {item.title}")


if __name__ == "__main__":
    main()
