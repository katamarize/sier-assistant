from src.core import storage
from src.core.models import Item


def filter_new_items(items: list[Item]) -> list[Item]:
    return [item for item in items if not storage.is_seen(item.source_id, item.item_key)]
