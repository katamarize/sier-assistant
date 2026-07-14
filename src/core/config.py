from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_SOURCES_PATH = "config/sources.yaml"


@dataclass
class Source:
    id: str
    name: str
    type: str
    url: str
    category: str
    interval_hours: int
    min_importance_to_notify: int
    tags_hint: list[str] = field(default_factory=list)
    selector: str | None = None


def load_sources(path: str | Path = DEFAULT_SOURCES_PATH) -> list[Source]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    defaults = data.get("defaults", {})
    sources = []
    for raw in data.get("sources", []):
        merged = {**defaults, **raw}
        sources.append(
            Source(
                id=merged["id"],
                name=merged["name"],
                type=merged["type"],
                url=merged["url"],
                category=merged["category"],
                interval_hours=merged.get("interval_hours", 6),
                min_importance_to_notify=merged.get("min_importance_to_notify", 3),
                tags_hint=merged.get("tags_hint", []),
                selector=merged.get("selector"),
            )
        )
    return sources
