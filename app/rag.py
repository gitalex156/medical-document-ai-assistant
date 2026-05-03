from pathlib import Path
from typing import List

from app.schemas import SourceChunk


GUIDELINES_PATH = Path("data/guidelines.md")


def load_guidelines() -> str:
    if not GUIDELINES_PATH.exists():
        return ""
    return GUIDELINES_PATH.read_text(encoding="utf-8")


def split_into_chunks(text: str) -> List[str]:
    chunks = []
    current = []

    for line in text.splitlines():
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def retrieve_relevant_chunks(query: str, top_k: int = 2) -> List[SourceChunk]:
    text = load_guidelines()
    chunks = split_into_chunks(text)

    query_words = set(query.lower().split())
    scored_chunks = []

    for chunk in chunks:
        chunk_words = set(chunk.lower().split())
        score = len(query_words.intersection(chunk_words))
        scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, chunk in scored_chunks[:top_k]:
        if score > 0:
            results.append(
                SourceChunk(
                    source="data/guidelines.md",
                    text=chunk,
                )
            )

    return results
