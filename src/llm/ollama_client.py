import json
import os
from pathlib import Path

import ollama
from dotenv import load_dotenv

from src.core.models import AnalysisResult

load_dotenv()

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

_TIMEOUT_SECONDS = 120
_TEMPERATURE = 0.2
_MAX_ATTEMPTS = 2

_PROMPT_PATH = Path(__file__).parent / "prompts" / "analyze_item.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "beginner_note": {"type": "string"},
        "importance": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "should_notify": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "summary",
        "beginner_note",
        "importance",
        "tags",
        "should_notify",
        "reason",
    ],
}


class LLMUnavailableError(Exception):
    pass


def analyze(title: str, content: str) -> AnalysisResult:
    prompt = _PROMPT_TEMPLATE.format(title=title, content=content)
    client = ollama.Client(host=OLLAMA_HOST, timeout=_TIMEOUT_SECONDS)

    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        try:
            response = client.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format=_RESPONSE_SCHEMA,
                options={"temperature": _TEMPERATURE},
            )
            data = json.loads(response["message"]["content"])
            return AnalysisResult(**data)
        except Exception as e:
            last_error = e

    raise LLMUnavailableError(
        f"Ollama analysis failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
