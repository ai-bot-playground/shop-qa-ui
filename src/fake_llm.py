"""Deterministyczne odpowiedzi „LLM" dla trybu offline (`QA_FAKE_LLM=1`).

Po co: cały 4-krokowy przepływ (analiza → plan → generacja → recenzja → PR)
da się przeklikać i przetestować **bez klucza, bez kosztów i bez losowości
modelu**. To atrapa do sprawdzania MECHANIKI aplikacji, nie generator kodu —
odpowiedzi są celowo trywialne, ale STRUKTURALNIE zgodne z tym, czego oczekują
parsery w `agent.py` (JSON dla expand/biz/plan/verify, czysta treść pliku dla
filechange/newfile, sentinel `BRAK_ZMIAN` dla naprawy).

Dwie zasady, których atrapa się trzyma, żeby nie psuć lokalnej bramki:
  * modyfikuje wyłącznie pliki, dla których zna składnię komentarza, i dopisuje
    jedną linię na końcu — kod dalej się kompiluje;
  * jako nowy plik tworzy `.md`, którego żaden build nie kompiluje.

Wejście parsowane jest z `user_content` po tych samych znacznikach, które składa
`agent.py` (`PLIK:`, `NOWY PLIK DO UTWORZENIA:`, `MAPA REPOZYTORIÓW`, `# REPO/PLIK:`).
"""

import json
import re

MARKER = "[QA_FAKE_LLM]"

# Rozszerzenie → token komentarza. Brak wpisu = atrapa odmawia zmiany
# (`BRAK_ZMIAN`), bo nie umie bezpiecznie dopisać linii (np. .json).
_COMMENT_TOKENS = {
    ".java": "//", ".js": "//", ".jsx": "//", ".ts": "//", ".tsx": "//",
    ".mjs": "//", ".gradle": "//", ".kt": "//",
    ".yml": "#", ".yaml": "#", ".properties": "#", ".sh": "#", ".py": "#",
    ".sql": "--",
}

# Preferencja przy wyborze pliku do modyfikacji: najpierw realny kod źródłowy,
# potem frontend, na końcu skrypty builda. Pliki poza tą listą są pomijane —
# atrapa nie rusza migracji Flyway (checksum) ani JSON-ów (brak komentarza).
_MODIFY_RANK = {
    ".java": 0,
    ".jsx": 1, ".js": 1, ".ts": 1, ".tsx": 1, ".mjs": 1,
    ".gradle": 2,
}

_NOTE_PATH = "docs/ai-change-note.md"

_SHOP_TERMS = (
    "order", "payment", "inventory", "catalog", "notification",
    "reservation", "stock", "saga", "outbox", "idempotency",
)


# ── parsowanie wejścia ────────────────────────────────────────────────────────

def _ext(path: str) -> str:
    idx = path.rfind(".")
    return path[idx:].lower() if idx >= 0 else ""


def _field(user_content: str, label: str) -> str:
    """Wartość jednolinijkowego znacznika `label: <wartość>`."""
    match = re.search(rf"^{re.escape(label)}:[ \t]*(.+)$", user_content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _question(user_content: str) -> str:
    return _field(user_content, "ŻĄDANA ZMIANA") or _field(user_content, "PYTANIE") or "(brak opisu)"


def _fenced(user_content: str) -> str:
    """Treść pierwszego bloku ``` … ``` (oryginał pliku)."""
    match = re.search(r"```\n(.*?)\n```", user_content, re.DOTALL)
    return match.group(1) if match else ""


def _citations(user_content: str) -> list[tuple[str, str, str]]:
    """(repo/plik, symbol, pierwsza linia) z nagłówków `_build_context`."""
    pattern = r"^# REPO/PLIK: (.+?) \| FUNKCJA: (.+?) \| LINIE: (\d+)"
    return re.findall(pattern, user_content, re.MULTILINE)


def _repo_map(user_content: str) -> dict[str, list[str]]:
    """Mapa repo → ścieżki z bloku `## <repo>` / `- <path>  [symbole]`.

    Zbiera TYLKO wewnątrz bloku rozpoczętego `## ` i przerywa na pierwszej linii,
    która nie jest wpisem listy — inaczej wchłonęłaby listę propozycji stojącą
    dalej w prompcie (też zaczyna się od `- `).
    """
    out: dict[str, list[str]] = {}
    repo = ""
    for line in user_content.splitlines():
        if line.startswith("## "):
            repo = line[3:].strip()
            out.setdefault(repo, [])
            continue
        if not repo:
            continue
        if line.startswith("- "):
            path = re.sub(r"\s*\[.*\]\s*$", "", line[2:]).strip()
            if path and "/" in path and ": " not in path:
                out[repo].append(path)
            continue
        repo = ""  # koniec bloku mapy
    return {r: p for r, p in out.items() if p}


# ── generatory odpowiedzi per rodzaj wywołania ────────────────────────────────

def _expand(user_content: str) -> str:
    question = _question(user_content)
    terms: list[str] = []
    for token in re.findall(r"\w{3,}", question.lower()):
        if token not in terms:
            terms.append(token)
    for term in _SHOP_TERMS:
        if term not in terms:
            terms.append(term)
    return json.dumps({"terms": terms[:20]}, ensure_ascii=False)


def _tech(user_content: str) -> str:
    cites = _citations(user_content)
    if not cites:
        return f"{MARKER} Tryb offline — brak fragmentów kodu w kontekście."
    loc, symbol, line = cites[0]
    listing = "\n".join(f"- `{c[0]}:{c[2]}` — {c[1]}" for c in cites[:5])
    return (
        f"{MARKER} Odpowiedź atrapowa (tryb offline, bez wywołania modelu).\n\n"
        f"Żądanie dotyczy `{symbol}` w `{loc}`. [source: {loc}:{line}]\n\n"
        f"Trafione fragmenty:\n{listing}"
    )


def _biz(user_content: str) -> str:
    cites = _citations(user_content)
    services = []
    for loc, _symbol, _line in cites:
        repo = loc.split("/", 1)[0]
        if repo and repo not in services:
            services.append(repo)
    payload = {
        "business_context": {
            "impact": "Średni",
            "area": "Atrapa offline",
            "time_dev": "1 dzień",
            "time_test": "0,5 dnia",
            "time_total": "1,5 dnia",
            "dependencies": ["brak — tryb offline"],
            "risk": f"{MARKER} Analiza nie pochodzi od modelu; służy testowaniu przepływu.",
            "summary": f"{MARKER} Deterministyczna analiza atrapowa dla żądania: {_question(user_content)}",
        },
        "feasibility": {
            "verdict": "Tak",
            "reason": f"{MARKER} Tryb offline zawsze uznaje zmianę za wykonalną.",
            "impacted_services": services or ["shop-catalog"],
            "impacted_files": [f"{loc}:{line}" for loc, _s, line in cites[:5]],
        },
        "test_plan": {
            "existing": ["shop-acceptance-tests: purchase.feature — happy path"],
            "new": ["Scenariusz Cucumber potwierdzający zmianę w dotkniętym serwisie"],
        },
        "proposals": [
            {
                "title": "Atrapa A — zmiana minimalna",
                "description": "Dopisanie znacznika do istniejących plików; służy sprawdzeniu mechaniki.",
                "effort": "Bardzo niski",
                "risk": "Bardzo niski",
                "commit_hint": "chore: znacznik trybu offline",
            },
            {
                "title": "Atrapa B — zmiana z nowym plikiem",
                "description": "Jak A, plus utworzenie notatki markdown w repozytorium.",
                "effort": "Niski",
                "risk": "Bardzo niski",
                "commit_hint": "chore: notatka zmiany",
            },
            {
                "title": "Atrapa C — bez zmian",
                "description": "Wariant kontrolny: nic nie modyfikuj.",
                "effort": "Bardzo niski",
                "risk": "Bardzo niski",
                "commit_hint": "chore: brak zmian",
            },
        ],
        "recommended_index": 0,
        "recommended_reason": f"{MARKER} Rekomendacja jest stała — wariant A jest najprostszy do zweryfikowania.",
    }
    return json.dumps(payload, ensure_ascii=False)


def _plan(user_content: str) -> str:
    """Plan: po jednym pliku do modyfikacji z dwóch pierwszych repo mapy + nowy plik."""
    repo_map = _repo_map(user_content)
    files: list[dict] = []
    for repo in sorted(repo_map):
        candidates = sorted(
            (p for p in repo_map[repo] if _ext(p) in _MODIFY_RANK),
            key=lambda p: (_MODIFY_RANK[_ext(p)], p),
        )
        if not candidates:
            continue
        files.append({
            "repo": repo,
            "path": candidates[0],
            "action": "modify",
            "reason": f"{MARKER} Dopisanie znacznika — sprawdzenie ścieżki modyfikacji.",
        })
        if len(files) == 2:
            break
    if files:
        files.append({
            "repo": files[0]["repo"],
            "path": _NOTE_PATH,
            "action": "create",
            "reason": f"{MARKER} Nowy plik — sprawdzenie ścieżki tworzenia.",
        })
    return json.dumps({"files": files}, ensure_ascii=False)


def _verify(user_content: str) -> str:
    return json.dumps(
        {
            "complete": True,
            "notes": f"{MARKER} Recenzja atrapowa — zestaw plików uznany za kompletny bez analizy.",
            "missing": [],
        },
        ensure_ascii=False,
    )


def _filechange(user_content: str) -> str:
    path = _field(user_content, "PLIK")
    original = _fenced(user_content)
    token = _COMMENT_TOKENS.get(_ext(path))
    if not original.strip() or not token:
        return "BRAK_ZMIAN"
    note = f"{token} {MARKER} atrapa zmiany: {_question(user_content)}"
    return f"{original.rstrip()}\n{note.rstrip()}\n"


def _newfile(user_content: str) -> str:
    target = _field(user_content, "NOWY PLIK DO UTWORZENIA")
    ext = _ext(target)
    if ext and ext != ".md":
        token = _COMMENT_TOKENS.get(ext)
        if not token:
            return "BRAK_ZMIAN"
        return f"{token} {MARKER} plik utworzony przez atrapę offline\n"
    return (
        f"# Notatka zmiany {MARKER}\n\n"
        f"Plik utworzony przez atrapę offline (`QA_FAKE_LLM=1`).\n\n"
        f"Żądana zmiana: {_question(user_content)}\n"
    )


_RESPONDERS = {
    "expand": _expand,
    "tech": _tech,
    "biz": _biz,
    "plan": _plan,
    "verify": _verify,
    "filechange": _filechange,
    "newfile": _newfile,
}


def respond(kind: str, user_content: str) -> str:
    """Deterministyczna odpowiedź atrapy dla danego rodzaju wywołania.

    `repair` i nieznane rodzaje zwracają `BRAK_ZMIAN` — atrapa nigdy nie udaje,
    że naprawiła kod po nieudanej walidacji.
    """
    responder = _RESPONDERS.get(kind)
    return responder(user_content) if responder else "BRAK_ZMIAN"
