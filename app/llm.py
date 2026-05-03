import json
import requests
from typing import Dict, List

from app.schemas import SourceChunk


OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"


def is_llm_enabled() -> bool:
    return True


def build_guidelines_context(sources: List[SourceChunk]) -> str:
    if not sources:
        return "Нет guideline-источников."

    parts = []
    for i, source in enumerate(sources, start=1):
        parts.append(f"Источник {i}:\n{source.text}")

    return "\n\n".join(parts)


def generate_llm_review(
    report_text: str,
    missing_sections: List[str],
    risks: List[str],
    quality_score: float,
    sources: List[SourceChunk],
) -> Dict:

    prompt = f"""
Ты медицинский AI-ассистент. Отвечай ТОЛЬКО валидным JSON.

Не используй markdown.
Не используй ```json.
Не добавляй пояснения после JSON.

Текст заключения:
{report_text}

Недостающие разделы:
{missing_sections}

Риски:
{risks}

Оценка качества:
{quality_score}

Guidelines:
{build_guidelines_context(sources)}

Верни JSON строго по схеме:
{{
  "llm_summary": "краткое резюме на русском",
  "quality_explanation": "объяснение оценки на русском",
  "improved_recommendations": [
    "рекомендация 1 на русском",
    "рекомендация 2 на русском"
  ],
  "doctor_copilot_hint": "короткая подсказка врачу на русском"
}}
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1
            }
        },
        timeout=120,
    )

    result = response.json()
    text = result.get("response", "").strip()

    try:
        return json.loads(text)
    except Exception:
        return {
            "llm_summary": "",
            "quality_explanation": "LLM вернул невалидный JSON.",
            "improved_recommendations": [],
            "doctor_copilot_hint": text,
        }
