import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from src.core.models import AnalysisResult

load_dotenv()

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8080/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "local")

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
    # llama-serverはAPIキー不要だがopenaiパッケージは値を要求するためダミーを渡す
    client = OpenAI(base_url=LLM_BASE_URL, api_key="no-key", timeout=_TIMEOUT_SECONDS)

    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=_TEMPERATURE,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "analysis", "schema": _RESPONSE_SCHEMA},
                },
            )
            data = json.loads(response.choices[0].message.content)
            return AnalysisResult(**data)
        except Exception as e:
            last_error = e

    raise LLMUnavailableError(
        f"LLM analysis failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
