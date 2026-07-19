import sys

from src.collectors.rss import fetch_rss
from src.core import config, log, storage
from src.core.diff import filter_new_items
from src.core.models import Item
from src.llm.llm_client import LLMUnavailableError, analyze
from src.notifiers import slack

logger = log.setup()

_COLLECTORS = {
    "rss": fetch_rss,
}


def collect_new_items(source: config.Source) -> list[Item]:
    collector = _COLLECTORS.get(source.type)
    if collector is None:
        logger.warning("[skip] 未対応のtype: %s (source=%s)", source.type, source.id)
        return []
    items = collector(source.url, source.id)
    return filter_new_items(items)


def run_collection(sources: list[config.Source]) -> None:
    for source in sources:
        try:
            new_items = collect_new_items(source)
        except Exception as e:
            logger.error("[error] 収集失敗: %s: %s", source.id, e)
            continue

        logger.info("%s (%s): 新着 %d 件", source.name, source.id, len(new_items))
        for item in new_items:
            storage.save_item(item)
            storage.mark_seen(item)


def run_analysis() -> None:
    pending_items = storage.fetch_pending_items()
    logger.info("LLM分析対象(pending): %d 件", len(pending_items))

    for pending in pending_items:
        try:
            result = analyze(pending.title, pending.content)
        except LLMUnavailableError as e:
            logger.warning("[pending維持] LLM分析失敗: %s: %s", pending.title[:40], e)
            continue

        status = "analyzed" if result.should_notify else "skipped"
        storage.update_item_analysis(pending.id, result, status)
        logger.info("[%s] importance=%d %s", status, result.importance, pending.title[:40])


def _send_in_chunks(
    items: list[storage.NotifiableItem], webhook_url: str, header: str, done_status: str
) -> None:
    # 重要度の高い順に10件ずつ分割送信。チャンク単位でstatus更新するので、
    # 途中で失敗しても送信済み分は確定し、残りはanalyzed維持で次回再送される
    items = sorted(items, key=lambda i: i.importance, reverse=True)
    size = slack.MAX_ITEMS_PER_MESSAGE
    chunks = [items[i : i + size] for i in range(0, len(items), size)]

    for idx, chunk in enumerate(chunks, 1):
        part = (idx, len(chunks)) if len(chunks) > 1 else None
        try:
            slack.send(slack.build_payload(chunk, header, part), webhook_url)
        except slack.SlackNotifyError as e:
            logger.warning("[analyzed維持] %s 送信失敗(次回再送): %s", header, e)
            return
        storage.update_items_status([i.id for i in chunk], done_status)
        logger.info("[%s] %s: %d 件送信", done_status, header, len(chunk))


def run_notification(sources: list[config.Source]) -> None:
    thresholds = {s.id: s.min_importance_to_notify for s in sources}
    candidates = storage.fetch_notifiable_items()

    # ソース毎の閾値で2レーンに仕分け(sources.yamlから消えたソースは既定値3)
    to_notify = [i for i in candidates if i.importance >= thresholds.get(i.source_id, 3)]
    to_stock = [i for i in candidates if i.importance < thresholds.get(i.source_id, 3)]
    logger.info("通知対象: メイン %d 件 / ストック %d 件", len(to_notify), len(to_stock))

    if to_notify:
        _send_in_chunks(to_notify, slack.SLACK_WEBHOOK_URL, "📰 新着ニュース", "notified")

    if to_stock:
        if slack.SLACK_STOCK_WEBHOOK_URL:
            _send_in_chunks(
                to_stock, slack.SLACK_STOCK_WEBHOOK_URL, "📥 ストック(閾値未満)", "stocked"
            )
        else:
            # ストック用Webhook未設定なら従来どおりskipped(パイプラインを詰まらせない)
            storage.update_items_status([i.id for i in to_stock], "skipped")
            logger.info("[skipped] ストックWebhook未設定のため %d 件をスキップ", len(to_stock))


def main() -> None:
    logger.info("=== daily_news 開始 ===")
    storage.init_db()
    sources = config.load_sources()

    run_collection(sources)
    run_analysis()
    run_notification(sources)
    logger.info("=== daily_news 正常終了 ===")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except Exception:
        # 想定外の例外もログに残す(タスクスケジューラ実行では画面が見えないため)
        logger.exception("=== daily_news 異常終了 ===")
        sys.exit(1)
