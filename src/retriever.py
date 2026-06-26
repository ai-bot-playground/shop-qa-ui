import re
from .ingest import CodeChunk


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def keyword_search(chunks: list[CodeChunk], query: str, top_k: int = 5) -> list[CodeChunk]:
    query_tokens = _tokenize(query)
    scored: list[tuple[int, CodeChunk]] = []

    for chunk in chunks:
        haystack = _tokenize(f"{chunk.symbol} {chunk.source}")
        score = len(query_tokens & haystack)
        if score > 0:
            scored.append((score, chunk))

    if not scored:
        return chunks  # fallback: return everything

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
