import sys

from src.collectors.rss import fetch_rss
from src.core import config, storage
from src.core.diff import filter_new_items
from src.core.models import Item
from src.llm.ollama_client import LLMUnavailableError, analyze

_COLLECTORS = {
    "rss": fetch_rss,
}


def collect_new_items(source: config.Source) -> list[Item]:
    collector = _COLLECTORS.get(source.type)
    if collector is None:
        print(f"  [skip] 未対応のtype: {source.type} (source={source.id})")
        return []
    items = collector(source.url, source.id)
    return filter_new_items(items)


def run_collection(sources: list[config.Source]) -> None:
    for source in sources:
        try:
            new_items = collect_new_items(source)
        except Exception as e:
            print(f"  [error] 収集失敗: {source.id}: {e}")
            continue

        print(f"{source.name} ({source.id}): 新着 {len(new_items)} 件")
        for item in new_items:
            storage.save_item(item)
            storage.mark_seen(item)


def run_analysis() -> None:
    pending_items = storage.fetch_pending_items()
    print(f"LLM分析対象(pending): {len(pending_items)} 件")

    for pending in pending_items:
        try:
            result = analyze(pending.title, pending.content)
        except LLMUnavailableError as e:
            print(f"  [pending維持] LLM分析失敗: {pending.title[:40]}: {e}")
            continue

        status = "analyzed" if result.should_notify else "skipped"
        storage.update_item_analysis(pending.id, result, status)
        print(f"  [{status}] importance={result.importance} {pending.title[:40]}")


def main() -> None:
    storage.init_db()
    sources = config.load_sources()

    run_collection(sources)
    run_analysis()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
