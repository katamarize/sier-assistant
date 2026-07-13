from dataclasses import dataclass


@dataclass
class AnalysisResult:
    summary: str
    beginner_note: str
    importance: int
    tags: list[str]
    should_notify: bool
    reason: str
