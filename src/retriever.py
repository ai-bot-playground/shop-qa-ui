import re

from .ingest import CodeChunk

# Stopwordy: polskie + angielskie słowa pytające/funkcyjne. W wyszukiwaniu
# leksykalnym są szumem — pasują do niemal każdego fragmentu kodu i zawyżały
# wynik (np. "jest" trafiało wszędzie). Usuwamy je z zapytania.
_STOPWORDS = {
    # PL
    "jak", "czy", "dlaczego", "co", "gdzie", "kiedy", "jest", "są", "sa",
    "być", "byc", "ma", "mają", "maja", "we", "na", "do", "od", "ze",
    "oraz", "lub", "albo", "że", "się", "sie", "to", "ten", "ta", "te",
    "dla", "przez", "po", "za", "jako", "aby", "żeby", "zeby", "nie", "tak",
    "ale", "jaki", "jaka", "jakie", "gdy", "ich", "jej", "jego", "przy",
    "bez", "pod", "nad", "czym", "kto", "który", "ktora", "które", "ktore",
    # EN
    "the", "an", "are", "be", "of", "in", "on", "for", "and", "or", "how",
    "why", "what", "where", "when", "does", "do", "this", "that", "with",
    "as", "by", "from", "at", "you", "we", "can", "should", "will", "would",
    "if", "not", "no", "yes", "was", "were", "has", "have",
}

# Rozbicie identyfikatorów: camelCase / PascalCase / snake_case / kebab-case /
# dotted → osobne słowa. Dzięki temu (po ekspansji polskiego pytania na
# angielskie terminy) słowo "fee" trafia w `calculateLateFee`, a "payment"
# w `PaymentRequestedListener`.
_WORD = re.compile(r"[A-Za-z0-9_.\-]+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _WORD.findall(text or ""):
        for seg in re.split(r"[_.\-]+", raw):
            if not seg:
                continue
            out.add(seg.lower())  # cały segment (dokładne dopasowanie identyfikatora)
            for piece in _CAMEL.findall(seg):  # + części camelCase
                p = piece.lower()
                if len(p) > 1:
                    out.add(p)
    return out


def _query_terms(query: str, extra_terms: list[str] | None) -> set[str]:
    terms = _tokenize(query)
    for t in (extra_terms or []):
        terms |= _tokenize(t)
    return {t for t in terms if len(t) > 1 and t not in _STOPWORDS}


def keyword_search(
    chunks: list[CodeChunk],
    query: str,
    top_k: int = 5,
    extra_terms: list[str] | None = None,
) -> list[CodeChunk]:
    """Leksykalne wyszukiwanie z ważeniem pól i rozbiciem identyfikatorów.

    Punktacja per fragment: term trafiony w nazwie symbolu = 3, w ścieżce/repo = 2,
    w treści = 1 (liczony raz, w polu o najwyższym priorytecie). `extra_terms` to
    dodatkowe hasła z ekspansji zapytania (NL PL → identyfikatory w kodzie).

    Brak sensownych termów w zapytaniu → zwraca `top_k` pierwszych fragmentów
    (nie zgadujemy całości indeksu). Termy są, ale nic nie pasuje → [] (uczciwe
    „nie znaleziono", zamiast zalewania modelu całym repo jak w starej wersji).
    """
    terms = _query_terms(query, extra_terms)
    if not terms:
        return chunks[:top_k]

    scored: list[tuple[int, CodeChunk]] = []
    for chunk in chunks:
        sym = _tokenize(chunk.symbol)
        path = _tokenize(f"{chunk.repo} {chunk.file_path}")
        body = _tokenize(chunk.source)
        score = 0
        for t in terms:
            if t in sym:
                score += 3
            elif t in path:
                score += 2
            elif t in body:
                score += 1
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
