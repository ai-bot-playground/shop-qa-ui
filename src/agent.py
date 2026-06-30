import json
import os
import re

import requests
from dotenv import load_dotenv

from .ingest import ingest_repo, ingest_app, CodeChunk
from .retriever import keyword_search

load_dotenv()

_ENDPOINT = os.environ.get(
    "AZURE_ANTHROPIC_ENDPOINT",
    "https://ai-remik.services.ai.azure.com/anthropic/v1/messages",
)
_MODEL = "claude-opus-4-8"

# OpenRouter (OpenAI-compatible) — używany preferencyjnie, gdy ustawiony klucz.
_OPENROUTER_ENDPOINT = os.environ.get(
    "OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions"
)
_OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "z-ai/glm-5.2")

# Tryb "thinking" (rozumowanie). Dla GLM-5.2 sterowany unified-paramem `reasoning`
# OpenRoutera. Domyślnie effort=high ("max thinking"). Można nadpisać env-em:
#   OPENROUTER_REASONING_EFFORT = high|medium|low|off
#   OPENROUTER_REASONING_MAX_TOKENS = <liczba>  (jawny budżet, ma priorytet)
_OPENROUTER_REASONING_EFFORT = os.environ.get("OPENROUTER_REASONING_EFFORT", "high")
_OPENROUTER_REASONING_MAXTOK = os.environ.get("OPENROUTER_REASONING_MAX_TOKENS", "")
# Maksymalny budżet wyjścia (odpowiedź + rozumowanie). Cap providera GLM-5.2: 32768.
_OPENROUTER_MAX_TOKENS = int(os.environ.get("OPENROUTER_MAX_TOKENS", "32000"))

# Telemetria zużycia tokenów. Po każdym wywołaniu LLM wysyłamy `usage` do serwisu
# shop-token-metrics (Micrometer -> Prometheus -> Grafana). Pusty URL = wyłączone.
#   TOKEN_METRICS_URL = http://localhost:8088   (np. port-forward svc/shop-token-metrics)
_TOKEN_METRICS_URL = os.environ.get("TOKEN_METRICS_URL", "")
_TOKEN_METRICS_SOURCE = os.environ.get("TOKEN_METRICS_SOURCE", "shop-qa-ui")

_NOT_FOUND = (
    "Nie znaleziono w kodzie — nie mogę odpowiedzieć na to pytanie "
    "na podstawie dostępnego źródła. Baza kodu nie zawiera żadnej logiki "
    "związanej z tym tematem."
)

# Stała wiedza o systemie docelowym (sklep ai-bot-playground). Wstrzykiwana do
# kontekstu LLM, aby model oceniał wykonalność i testy ŚWIADOMY naszej architektury.
_SHOP_FACTS = """\
System docelowy: sklep flash-sale na mikroserwisach (organizacja ai-bot-playground).
- Stack: Spring Boot 4 / Java 25 / Gradle; React/Vite (shop-ui); Postgres (database-per-service), Redis, Kafka (KRaft).
- Serwisy: shop-gateway (Spring Cloud Gateway, /api/* -> serwisy, StripPrefix), shop-catalog (katalog + Flyway seed + Caffeine cache + test-support), shop-inventory (atomowa rezerwacja Redis Lua + outbox + idempotencja), shop-order (saga: reserve -> pay -> confirm / kompensacja + outbox multi-topic + timeout scanner), shop-payment (mock PSP; deterministyczny decline gdy kwota konczy sie na .66), shop-notification (konsument terminalnych zdarzen Order*, idempotentny).
- Komunikacja: Kafka topics order-events, inventory-events, payment-events (+ .DLT); wzorzec outbox + idempotencja.
- Testy: per-serwis Cucumber + Testcontainers (component); shop-acceptance-tests (cross-service przez gateway: happy / out-of-stock / payment-declined).
- Bramka jakosci: PR do main -> preprod-gate (component tests -> build obrazu -> deploy kind-preprod -> acceptance). Tylko zielona bramka pozwala na merge.
"""


def _openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "")


def _api_key() -> str:
    return (
        os.environ.get("AZURE_ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    )


def llm_available() -> bool:
    """True gdy skonfigurowano jakikolwiek klucz API (realne wywołania LLM)."""
    return bool(_openrouter_key() or _api_key())


def is_demo_mode() -> bool:
    """True gdy brak klucza API — aplikacja zwraca mockowane odpowiedzi,
    aby można było przeklikać cały workflow bez podłączonego modelu."""
    return not llm_available()


def _call(system: str, user_content: str, max_tokens: int = 1024) -> str:
    # Dyspozytor providera: OpenRouter (OpenAI-compatible) -> Azure Anthropic -> mock.
    if _openrouter_key():
        return _call_openrouter(system, user_content, max_tokens)
    if _api_key():
        return _call_anthropic(system, user_content, max_tokens)
    return _mock_call(system, user_content, max_tokens)


def _reasoning_param() -> dict:
    """Unified OpenRouter `reasoning` — domyślnie najmocniejszy thinking (effort=high)."""
    if _OPENROUTER_REASONING_MAXTOK.isdigit():
        return {"max_tokens": int(_OPENROUTER_REASONING_MAXTOK)}
    eff = (_OPENROUTER_REASONING_EFFORT or "high").lower()
    if eff in ("off", "none", "disabled", "false", "0"):
        return {"enabled": False}
    if eff in ("low", "medium", "high"):
        return {"effort": eff}
    return {"effort": "high"}


def _strip_think(text: str) -> str:
    """Defensywnie usuń ewentualne bloki <think>…</think> z treści (gdyby wpadły inline)."""
    if not text:
        return text
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _emit_token_metrics(model: str, usage: dict) -> None:
    """Best-effort: wyślij zużycie tokenów do shop-token-metrics. Nigdy nie psuje
    wywołania LLM — błędy (brak serwisu, timeout) są połykane."""
    if not _TOKEN_METRICS_URL or not usage:
        return
    try:
        details = usage.get("completion_tokens_details") or {}
        payload = {
            "model": model,
            "source": _TOKEN_METRICS_SOURCE,
            "promptTokens": usage.get("prompt_tokens"),
            "completionTokens": usage.get("completion_tokens"),
            "reasoningTokens": details.get("reasoning_tokens"),
            "totalTokens": usage.get("total_tokens"),
            # OpenRouter zwraca koszt w `usage.cost` gdy w żądaniu jest usage.include=true.
            "costUsd": usage.get("cost"),
        }
        requests.post(
            _TOKEN_METRICS_URL.rstrip("/") + "/api/usage", json=payload, timeout=2
        )
    except Exception:
        pass  # metryki są pomocnicze — cisza przy awarii


def _call_openrouter(system: str, user_content: str, max_tokens: int) -> str:
    headers = {
        "Authorization": f"Bearer {_openrouter_key()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _OPENROUTER_MODEL,
        # Duży budżet wyjścia, by rozumowanie nie ucięło odpowiedzi.
        "max_tokens": max(max_tokens, _OPENROUTER_MAX_TOKENS),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "reasoning": _reasoning_param(),
        # Poproś o pełne `usage` (w tym koszt) w odpowiedzi — do telemetrii tokenów.
        "usage": {"include": True},
    }
    # Thinking bywa wolny — dłuższy timeout.
    resp = requests.post(_OPENROUTER_ENDPOINT, headers=headers, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    _emit_token_metrics(_OPENROUTER_MODEL, data.get("usage") or {})
    # GLM-5.2 bywa zwraca content=null (gdy całość budżetu poszła w reasoning lub
    # odpowiedź była pusta). `or ""` chroni dalszy _strip_* przed AttributeError.
    content = data["choices"][0]["message"].get("content") or ""
    return _strip_think(content)


def _call_anthropic(system: str, user_content: str, max_tokens: int) -> str:
    headers = {
        "x-api-key": _api_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": _MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    resp = requests.post(_ENDPOINT, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from text (handles markdown code fences)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return {}


def _build_context(chunks: list[CodeChunk]) -> str:
    def _header(c: CodeChunk) -> str:
        loc = f"{c.repo}/{c.file_path}" if c.repo else c.file_path
        return f"# REPO/PLIK: {loc} | FUNKCJA: {c.symbol} | LINIE: {c.start_line}–{c.end_line}"
    return "\n\n".join(f"{_header(c)}\n{c.source}" for c in chunks)


_TECH_SYSTEM = """\
Jesteś ekspertem od legacy code. Odpowiadasz NA PODSTAWIE KODU który dostałeś — nic więcej.

Zasady:
1. Każde stwierdzenie musi zawierać cytowanie w formacie [source: plik:linia].
2. Jeśli informacja NIE jest w kodzie, odpowiedz dokładnie: "Nie znaleziono w kodzie."
3. Odpowiadaj po polsku. Bądź zwięzły — najpierw bezpośrednia odpowiedź, potem cytowania.\
"""

_BIZ_SYSTEM = """\
Jesteś architektem i analitykiem biznesowym systemu opisanego w KONTEKST SYSTEMU.
Na podstawie KODU i KONTEKSTU SYSTEMU wygeneruj analizę w JSON.

Odpowiedz WYŁĄCZNIE prawidłowym JSON (bez markdown, bez wyjaśnień):
{
  "business_context": {
    "impact": "Wysoki|Średni|Niski",
    "area": "<obszar biznesowy po polsku>",
    "time_dev": "<np. '1–2 dni'>",
    "time_test": "<np. '0,5 dnia'>",
    "time_total": "<np. '2–3 dni'>",
    "dependencies": ["<zależność 1>", "<zależność 2>"],
    "risk": "<opis ryzyka po polsku>",
    "summary": "<1–2 zdania streszczenia problemu biznesowego po polsku>"
  },
  "feasibility": {
    "verdict": "Tak|Z zastrzeżeniami|Nie",
    "reason": "<czy zmianę da się wprowadzić w TYM systemie i dlaczego — oparte na KODZIE i KONTEKŚCIE SYSTEMU>",
    "impacted_services": ["<np. shop-order>"],
    "impacted_files": ["<plik:linia z kodu>"]
  },
  "test_plan": {
    "existing": ["<istniejący scenariusz Cucumber/acceptance który to pokrywa>"],
    "new": ["<proponowany nowy scenariusz Cucumber/acceptance, jeśli potrzebny>"]
  },
  "proposals": [
    {
      "title": "<krótki tytuł po polsku>",
      "description": "<opis zmiany i uzasadnienie po polsku>",
      "effort": "Bardzo niski|Niski|Średni|Wysoki",
      "risk": "Bardzo niski|Niski|Średni|Wysoki",
      "commit_hint": "<sugestia git commit, np. fix: ...>"
    }
  ],
  "recommended_index": <0-based indeks JEDNEJ propozycji, którą sam wybierasz jako najbardziej optymalną>,
  "recommended_reason": "<1 zdanie: dlaczego TA propozycja jest najlepsza — najlepszy stosunek wartości do nakładu/ryzyka i zgodność z dobrymi praktykami>"
}

Zasady:
- "feasibility.verdict" oceniaj realnie wobec naszej architektury (saga, Kafka, bramka preprod).
- "test_plan" odwołuj się do naszych testów (per-serwis Cucumber + shop-acceptance-tests).
- Wygeneruj dokładnie 3 propozycje. Odpowiadaj po polsku.
- "recommended_index" MUSI wskazywać tę jedną propozycję, którą rekomendujesz wdrożyć — wybierasz
  ją Ty (najbardziej zasadną, zgodną z dobrymi praktykami inżynierskimi), użytkownik nie wybiera.\
"""


_FIX_SYSTEM = """\
Jesteś senior developerem. Wygeneruj poprawioną wersję funkcji Python.

Zasady:
1. Zwróć WYŁĄCZNIE kod funkcji — bez wyjaśnień, bez markdown, bez ogrodzeń ```.
2. Zachowaj tę samą sygnaturę funkcji.
3. Zastosuj opisaną zmianę.
4. Kod musi być gotowy do wklejenia bezpośrednio do pliku Python.\
"""

_FIX_TESTS_SYSTEM = """\
Jesteś senior developerem. Popraw funkcję Python tak by przechodziła wszystkie podane testy.

Zasady:
1. Zwróć WYŁĄCZNIE kod funkcji — bez wyjaśnień, bez markdown, bez ogrodzeń ```.
2. Zachowaj tę samą sygnaturę funkcji.
3. Logika musi zwracać dokładnie oczekiwane wartości testów.\
"""

_DIFF_SYSTEM = """\
Jesteś senior developerem pracującym nad systemem opisanym w KONTEKST SYSTEMU.
Wygeneruj żądaną zmianę jako UNIFIED DIFF gotowy dla `git apply`.

Zasady:
1. Zwróć WYŁĄCZNIE diff — bez wyjaśnień, bez markdown, bez ogrodzeń ```.
2. Ścieżki względem korzenia repozytorium serwisu: nagłówki "--- a/<path>" i "+++ b/<path>".
3. Poprawne hunki "@@ ... @@" z ~3 liniami kontekstu, zgodne z dostarczonym KODEM.
4. Zmiana minimalna i skupiona; zachowaj styl, konwencje i kompilowalność (Java/Spring).
5. Jeśli zmiany nie da się bezpiecznie wykonać na podstawie dostarczonego kodu — zwróć pusty wynik.\
"""

_FILECHANGE_SYSTEM = """\
Jesteś senior developerem systemu opisanego w KONTEKST SYSTEMU. Otrzymasz PEŁNĄ treść
jednego pliku oraz opis żądanej zmiany.

Zasady:
1. Zwróć WYŁĄCZNIE pełną, zaktualizowaną treść TEGO pliku — bez wyjaśnień, bez markdown, bez ```.
2. Zachowaj wszystko bez zmian poza żądaną modyfikacją (importy, formatowanie, resztę kodu).
3. Kod musi pozostać kompilowalny i zgodny ze stylem/konwencjami projektu (Java/Spring).
4. Jeśli ten plik NIE jest związany z żądaną zmianą albo zmiany nie da się w nim bezpiecznie
   wykonać — odpowiedz DOKŁADNIE jednym słowem: BRAK_ZMIAN (bez cudzysłowów, bez nic więcej).
   NIE zwracaj pustego pliku ani opisu — sam token BRAK_ZMIAN.\
"""

# Sentinel + echo-frazy oznaczające „ten plik nie jest celem zmiany". Model bywa
# zwraca to jako treść pliku zamiast faktycznie odmówić — wykrywamy i mapujemy na "".
_NO_CHANGE_SENTINEL = "brak_zmian"
_NO_CHANGE_PHRASES = (
    "brak_zmian", "brakzmian", "zwrocpustaodpowiedz", "zwróćpustąodpowiedź",
    "pustaodpowiedz", "pustąodpowiedź", "nochange", "brakzmiany",
)


def _is_no_change(text: str) -> bool:
    """True gdy odpowiedź modelu to faktycznie „nie zmieniam tego pliku" (pustka,
    sentinel BRAK_ZMIAN albo echo instrukcji), a nie realna treść pliku."""
    if not text or not text.strip():
        return True
    norm = re.sub(r"[^\w]", "", text.strip().lower())
    # Krótka odpowiedź bez cech kodu, pasująca do sentinela/echa → brak zmiany.
    if len(norm) <= 40 and any(p in norm for p in _NO_CHANGE_PHRASES):
        return True
    return False


_PLAN_SYSTEM = """\
Jesteś architektem systemu opisanego w KONTEKST SYSTEMU. Dostajesz MAPĘ REPOZYTORIÓW
(istniejące pliki i symbole każdego serwisu) oraz żądaną zmianę biznesową.

Twoje zadanie: zaplanuj KTÓRE pliki trzeba zmienić i JAKIE nowe utworzyć, aby zrealizować
zmianę w całym systemie (frontend + gateway + serwisy). Myśl warstwami: UI, propagacja przez
gateway, logika w serwisie, kontrakt/dane.

Odpowiedz WYŁĄCZNIE prawidłowym JSON (bez markdown, bez wyjaśnień):
{
  "files": [
    {
      "repo": "<nazwa repo z MAPY, np. shop-catalog>",
      "path": "<ścieżka pliku względem korzenia repo>",
      "action": "modify|create",
      "reason": "<po co ten plik — 1 zdanie po polsku>"
    }
  ]
}

Zasady:
- Używaj WYŁĄCZNIE repozytoriów występujących w MAPIE REPOZYTORIÓW.
- "modify" dla istniejących plików (muszą być w MAPIE), "create" dla nowych (ścieżka zgodna z
  konwencją pakietu/katalogu danego serwisu).
- Uwzględnij WSZYSTKIE warstwy potrzebne do działania zmienia (np. komponent UI + filtr w
  gateway + logika w serwisie). Nie pomijaj frontendu, jeśli zmiana go dotyczy.
- Plan minimalny ale KOMPLETNY. Nie dodawaj plików nieistotnych dla zmiany.
- Odpowiadaj po polsku w polu reason.\
"""

_VERIFY_SYSTEM = """\
Jesteś recenzentem kompletności zmiany w systemie opisanym w KONTEKST SYSTEMU.
Otrzymujesz żądaną zmianę, MAPĘ REPOZYTORIÓW oraz listę WYGENEROWANYCH PLIKÓW (z fragmentami
treści i statusem: ok = ma treść, empty = model nie wygenerował treści).

Oceń, czy zestaw plików jest KOMPLETNY i spójny, by zmiana RZECZYWIŚCIE działała end-to-end:
- czy brakuje plików, do których odwołuje się wygenerowany kod (komponent zaimportowany, ale
  nieutworzony; DTO/encja/endpoint/konfiguracja; rejestracja beana; routing; nagłówek po stronie
  klienta i jego odbiór po stronie serwera),
- czy pliki ze statusem "empty" trzeba jednak wygenerować, bo są potrzebne,
- czy warstwy się spinają (UI → gateway → serwis → dane).

Odpowiedz WYŁĄCZNIE prawidłowym JSON (bez markdown):
{
  "complete": true|false,
  "notes": "<zwięźle po polsku: czego brakuje albo że jest kompletne>",
  "missing": [
    {"repo": "<repo z MAPY>", "path": "<ścieżka>", "action": "create|modify", "reason": "<po co>"}
  ]
}

Zasady:
- "repo" wyłącznie z MAPY REPOZYTORIÓW.
- NIE powtarzaj plików już poprawnie wygenerowanych (status ok), chyba że wymagają korekty.
- Jeśli wszystko jest na miejscu → "complete": true oraz "missing": [].
- Odpowiadaj po polsku w polach tekstowych.\
"""

_NEWFILE_SYSTEM = """\
Jesteś senior developerem systemu opisanego w KONTEKST SYSTEMU. Tworzysz NOWY plik od zera.

Zasady:
1. Zwróć WYŁĄCZNIE pełną treść nowego pliku — bez wyjaśnień, bez markdown, bez ```.
2. Kod kompilowalny i zgodny ze stylem/konwencjami warstwy (Java/Spring dla serwisów,
   React/Vite/JSX dla shop-ui).
3. Plik ma realizować swoją część żądanej zmiany (zgodnie z jego ścieżką/warstwą).
4. Jeśli tego pliku nie da się sensownie utworzyć dla tej zmiany — odpowiedz DOKŁADNIE jednym
   słowem: BRAK_ZMIAN.\
"""


def _strip_fences(text: str) -> str:
    """Usuń ewentualne ogrodzenia ```diff / ``` z odpowiedzi modelu."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip("\n")


def fix_code_with_tests(source_code: str, failing_tests: list[dict]) -> str:
    """Regenerate source_code so it passes the given failing tests."""
    failures_desc = "\n".join(
        f"- {t['name']}: oczekiwano {t['expected']!r}, otrzymano {t['got']!r}"
        + (f" [błąd: {t['error']}]" if t.get("error") else "")
        for t in failing_tests
        if not t["passed"]
    )
    user_msg = (
        f"Funkcja:\n{source_code}\n\n"
        f"Nieprzechodzące testy:\n{failures_desc}\n\n"
        f"Poprawiona funkcja:"
    )
    try:
        return _call(_FIX_TESTS_SYSTEM, user_msg, max_tokens=1024).strip()
    except Exception:
        return source_code


def generate_code_fix(original_source: str, proposal: dict, question: str) -> str:
    """Return modified function source code based on the accepted proposal."""
    user_msg = (
        f"Oryginalna funkcja:\n{original_source}\n\n"
        f"Pytanie użytkownika: {question}\n\n"
        f"Proponowana zmiana: {proposal['title']}\n"
        f"Opis: {proposal['description']}\n\n"
        f"Wygeneruj poprawioną funkcję:"
    )
    try:
        return _call(_FIX_SYSTEM, user_msg, max_tokens=1024).strip()
    except Exception as exc:
        return f"# Błąd generowania kodu: {exc}\n{original_source}"


def generate_change_diff(question: str, proposals: list[dict], chunks: list[CodeChunk]) -> str:
    """Generate the requested change as a unified diff (git apply) for a service.

    System-aware (uses _SHOP_FACTS) and grounded in the retrieved code chunks.
    Returns an empty string when no diff can be produced (incl. demo mode).
    """
    code_ctx = _build_context(chunks)
    props = "\n".join(
        f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or [])
    )
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"KOD (fragmenty z repo serwisu):\n{code_ctx}\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"Wygeneruj unified diff:"
    )
    try:
        return _strip_fences(_call(_DIFF_SYSTEM, user_msg, max_tokens=2048))
    except Exception:
        return ""


def generate_file_change(question: str, proposals: list[dict],
                         file_path: str, file_source: str) -> str:
    """Return the FULL updated content of one file for the requested change.

    Robust alternative to LLM-emitted unified diffs (which often produce corrupt
    patches): the model returns the whole file, and git computes the real diff.
    Returns an empty string when no change can be made (incl. demo mode).
    """
    props = "\n".join(
        f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or [])
    )
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"PLIK: {file_path}\n```\n{file_source}\n```\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"Zwróć pełną zaktualizowaną treść pliku:"
    )
    # W trybie demo (brak klucza) _mock_call zwraca "" bez wyjątku. Realne błędy
    # (np. TLS/serwer) NIE są maskowane jako pustka — propagujemy je, by UI mógł
    # pokazać prawdziwą przyczynę zamiast mylącego "brak klucza API".
    result = _strip_fences(_call(_FILECHANGE_SYSTEM, user_msg, max_tokens=4096))
    # Sentinel/echo „BRAK_ZMIAN" → traktuj jako brak zmiany (nie wstawiaj tego
    # zdania jako treści pliku, co dawało diff kasujący cały plik).
    return "" if _is_no_change(result) else result


def build_repo_map(chunks: list[CodeChunk]) -> str:
    """Zwięzła mapa: per repo lista plików i ich symboli — wejście dla plannera.

    Buduje hierarchię repo → plik → [symbole] z zaindeksowanych chunków, by LLM
    rozumował o strukturze całej aplikacji zamiast polegać na top-5 z retrievalu.
    """
    by_repo: dict[str, dict[str, list[str]]] = {}
    for c in chunks:
        repo = c.repo or "(root)"
        by_repo.setdefault(repo, {}).setdefault(c.file_path, []).append(c.symbol)
    lines: list[str] = []
    for repo in sorted(by_repo):
        lines.append(f"## {repo}")
        for path in sorted(by_repo[repo]):
            syms = ", ".join(by_repo[repo][path][:8])
            lines.append(f"- {path}  [{syms}]")
    return "\n".join(lines)


def plan_change(question: str, repo_map: str, proposals: list[dict]) -> list[dict]:
    """LLM planuje pliki do zmiany/utworzenia w całej aplikacji (zamiast top-5 retrievalu).

    Zwraca listę {repo, path, action: modify|create, reason}. Pusta lista przy błędzie
    lub w trybie demo.
    """
    props = "\n".join(
        f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or [])
    )
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"MAPA REPOZYTORIÓW (istniejące pliki i symbole):\n{repo_map}\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"Zwróć plan zmian jako JSON:"
    )
    try:
        raw = _call(_PLAN_SYSTEM, user_msg, max_tokens=2048)
        data = _extract_json(raw)
    except Exception:
        return []
    out: list[dict] = []
    seen: set = set()
    for f in (data.get("files") or []):
        repo = (f.get("repo") or "").strip()
        path = (f.get("path") or "").strip().lstrip("/")
        action = (f.get("action") or "modify").strip().lower()
        if not repo or not path or (repo, path) in seen:
            continue
        seen.add((repo, path))
        out.append({
            "repo": repo, "path": path,
            "action": "create" if action == "create" else "modify",
            "reason": (f.get("reason") or "").strip(),
        })
    return out


def verify_completeness(question: str, proposals: list[dict], repo_map: str,
                        generated_files: list[dict]) -> dict:
    """Agent-recenzent: czy wygenerowany zestaw plików jest kompletny i spójny.

    `generated_files`: lista {repo, path, action, status: ok|empty, head}.
    Zwraca {complete: bool, notes: str, missing: [{repo, path, action, reason}]}.
    """
    listing = "\n\n".join(
        f"### {g['repo']}/{g['path']}  [{g.get('action', 'modify')}, {g.get('status', 'ok')}]\n"
        f"{g.get('head', '')}"
        for g in generated_files
    )
    props = "\n".join(f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or []))
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"MAPA REPOZYTORIÓW:\n{repo_map}\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"WYGENEROWANE PLIKI:\n{listing}\n\n"
        f"Zwróć ocenę kompletności jako JSON:"
    )
    try:
        data = _extract_json(_call(_VERIFY_SYSTEM, user_msg, max_tokens=2048))
    except Exception:
        return {"complete": True, "notes": "", "missing": []}
    missing: list[dict] = []
    seen: set = set()
    for f in (data.get("missing") or []):
        repo = (f.get("repo") or "").strip()
        path = (f.get("path") or "").strip().lstrip("/")
        action = (f.get("action") or "create").strip().lower()
        if not repo or not path or (repo, path) in seen:
            continue
        seen.add((repo, path))
        missing.append({
            "repo": repo, "path": path,
            "action": "modify" if action == "modify" else "create",
            "reason": (f.get("reason") or "").strip(),
        })
    return {
        "complete": bool(data.get("complete")) and not missing,
        "notes": (data.get("notes") or "").strip(),
        "missing": missing,
    }


def generate_new_file(question: str, proposals: list[dict], repo: str, file_path: str) -> str:
    """Pełna treść NOWEGO pliku (action=create z planu). "" gdy nie da się utworzyć/demo."""
    props = "\n".join(
        f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or [])
    )
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"NOWY PLIK DO UTWORZENIA: {repo}/{file_path}\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"Zwróć pełną treść nowego pliku:"
    )
    result = _strip_fences(_call(_NEWFILE_SYSTEM, user_msg, max_tokens=4096))
    return "" if _is_no_change(result) else result


def run_qa(question: str, repo_path: str = "", chunks: list[CodeChunk] | None = None, **_kwargs) -> dict:
    """Odpowiada na pytanie o kod.

    Gdy `chunks` jest podany (pre-indexed, np. z ingest_app dla wielu repo),
    używa go bezpośrednio. W przeciwnym razie indeksuje `repo_path` (compat
    z run_qa_eval w sandbox.py i starym flow).
    """
    all_chunks = chunks if chunks is not None else ingest_repo(repo_path)
    relevant_chunks = keyword_search(all_chunks, question, top_k=5)

    if not relevant_chunks:
        return {
            "answer": _NOT_FOUND,
            "retrieved_chunks": [],
            "business_context": None,
            "feasibility": None,
            "test_plan": None,
            "proposals": [],
        }

    code_ctx = _build_context(relevant_chunks)
    user_msg = f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\nKOD:\n{code_ctx}\n\nPYTANIE: {question}"

    # ── Wywołanie 1: odpowiedź techniczna ────────────────────────────────────
    try:
        technical_answer = _call(_TECH_SYSTEM, user_msg)
    except Exception as exc:
        technical_answer = f"Błąd API: {exc}"

    # ── Wywołanie 2: kontekst biznesowy + propozycje ─────────────────────────
    business_context: dict | None = None
    feasibility: dict | None = None
    test_plan: dict | None = None
    proposals: list[dict] = []
    recommended_index: int | None = None
    recommended_reason: str | None = None
    try:
        biz_raw = _call(_BIZ_SYSTEM, user_msg, max_tokens=2560)
        biz_data = _extract_json(biz_raw)
        business_context = biz_data.get("business_context")
        feasibility = biz_data.get("feasibility")
        test_plan = biz_data.get("test_plan")
        proposals = biz_data.get("proposals", [])
        recommended_index = biz_data.get("recommended_index")
        recommended_reason = biz_data.get("recommended_reason")
    except Exception:
        pass  # brak kontekstu biznesowego nie blokuje odpowiedzi technicznej

    return {
        "answer": technical_answer,
        "retrieved_chunks": relevant_chunks,
        "business_context": business_context,
        "feasibility": feasibility,
        "test_plan": test_plan,
        "proposals": proposals,
        "recommended_index": recommended_index,
        "recommended_reason": recommended_reason,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRYB DEMONSTRACYJNY (mock) — używany automatycznie, gdy brak klucza API.
# Cel: pełny workflow GUI (Analyze → Piaskownica → PR) działa bez podłączonego
# modelu. Każda odpowiedź jest oznaczona jako przykładowa. Po ustawieniu
# AZURE_ANTHROPIC_API_KEY (lub ANTHROPIC_API_KEY) kod automatycznie wraca do
# realnych wywołań — nie trzeba nic przełączać.
# ══════════════════════════════════════════════════════════════════════════════
_DEMO_NOTE = (
    "> ℹ️ *Tryb demonstracyjny (brak klucza API). To przykładowa odpowiedź "
    "pokazująca format — uzupełnij `AZURE_ANTHROPIC_API_KEY`, aby uzyskać realną "
    "analizę.*"
)


def _parse_first_chunk(user_content: str) -> tuple[str, str, str]:
    """Wyłuskaj plik / symbol / pierwszą linię z kontekstu kodu (jeśli jest)."""
    m = re.search(
        r"# PLIK:\s*(.+?)\s*\|\s*FUNKCJA:\s*(.+?)\s*\|\s*LINIE:\s*(\d+)", user_content
    )
    if m:
        return m.group(1), m.group(2), m.group(3)
    return ("sample/module.py", "funkcja", "1")


def _mock_tech_answer(user_content: str) -> str:
    file, symbol, line = _parse_first_chunk(user_content)
    return (
        f"{_DEMO_NOTE}\n\n"
        f"Na podstawie kodu logika powiązana z pytaniem znajduje się w funkcji "
        f"`{symbol}`. Funkcja przyjmuje parametry wejściowe i zwraca wynik na "
        f"podstawie wartości zaszytych bezpośrednio w jej ciele. "
        f"[source: {file}:{line}]\n\n"
        f"Najważniejsze obserwacje:\n"
        f"- Wartości progowe / kody są zdefiniowane lokalnie w `{symbol}`, więc ich "
        f"zmiana wymaga edycji kodu. [source: {file}:{line}]\n"
        f"- Nieobsłużone przypadki zwracają wartość domyślną, co może maskować błędne "
        f"dane wejściowe. [source: {file}:{line}]"
    )


def _mock_biz_json(user_content: str) -> str:
    file, symbol, _line = _parse_first_chunk(user_content)
    data = {
        "business_context": {
            "impact": "Średni",
            "area": "Logika domenowa (przykład demo)",
            "time_dev": "1–2 dni",
            "time_test": "0,5 dnia",
            "time_total": "2–3 dni",
            "dependencies": [file, "Testy regresyjne modułu"],
            "risk": "Średni — zmiana dotyka logiki obliczeniowej; wymaga regresji.",
            "summary": (
                f"[DEMO] Funkcja {symbol} zawiera logikę powiązaną z pytaniem. "
                f"Poniższe propozycje są przykładowe — podłącz klucz API, aby "
                f"otrzymać realną analizę biznesową."
            ),
        },
        "feasibility": {
            "verdict": "Z zastrzeżeniami",
            "reason": (
                f"[DEMO] Zmiana w {symbol} jest realna w naszym systemie, ale wymaga "
                f"przejścia przez bramkę preprod (component -> build -> deploy -> acceptance). "
                f"Podłącz klucz API, aby uzyskać realną ocenę wykonalności."
            ),
            "impacted_services": [file.split("/")[0] if "/" in file else file],
            "impacted_files": [f"{file}:{_line}"],
        },
        "test_plan": {
            "existing": ["[DEMO] Component Cucumber danego serwisu", "[DEMO] shop-acceptance-tests (cross-service)"],
            "new": [f"[DEMO] Nowy scenariusz pokrywający zmianę w {symbol}"],
        },
        "proposals": [
            {
                "title": f"Wydziel parametry z {symbol} do konfiguracji",
                "description": (
                    "Przenieś zaszyte wartości/kody do stałej lub configu, aby zmiana "
                    "nie wymagała edycji logiki funkcji."
                ),
                "effort": "Niski",
                "risk": "Niski",
                "commit_hint": f"refactor: wydziel parametry z {symbol} do konfiguracji",
            },
            {
                "title": "Dodaj jawną obsługę nieznanych przypadków",
                "description": (
                    "Zwracaj czytelny błąd lub log zamiast cichej wartości domyślnej."
                ),
                "effort": "Średni",
                "risk": "Średni",
                "commit_hint": f"fix: jawna obsługa nieznanych wejść w {symbol}",
            },
            {
                "title": "Uzupełnij testy jednostkowe",
                "description": "Dodaj testy brzegowe pokrywające warianty wejścia.",
                "effort": "Bardzo niski",
                "risk": "Niski",
                "commit_hint": f"test: dodaj testy brzegowe dla {symbol}",
            },
        ],
        "recommended_index": 0,
        "recommended_reason": (
            "[DEMO] Wydzielenie parametrów daje najlepszy stosunek wartości do "
            "nakładu i ryzyka — usuwa zaszyte wartości bez zmiany logiki."
        ),
    }
    return json.dumps(data, ensure_ascii=False)


def _mock_fix_code(user_content: str) -> str:
    """Zwróć oryginalną funkcję (z adnotacją demo), aby piaskownica pozostała
    uruchamialna — realny fix wymaga podłączonego modelu."""
    m = re.search(
        r"(?:Oryginalna funkcja|Funkcja):\n(.*?)\n\n"
        r"(?:Pytanie użytkownika|Nieprzechodzące testy):",
        user_content,
        re.DOTALL,
    )
    source = (m.group(1) if m else user_content).strip()
    return f"# [demo] Podłącz klucz API, aby wygenerować realną poprawkę.\n{source}"


def _mock_call(system: str, user_content: str, max_tokens: int = 1024) -> str:
    """Dyspozytor mocków — wybiera kształt odpowiedzi po systemowym promptcie."""
    if system is _BIZ_SYSTEM:
        return _mock_biz_json(user_content)
    if system in (_FIX_SYSTEM, _FIX_TESTS_SYSTEM):
        return _mock_fix_code(user_content)
    if system in (_DIFF_SYSTEM, _FILECHANGE_SYSTEM, _NEWFILE_SYSTEM):
        return ""  # tryb demo: realna zmiana wymaga podłączonego modelu
    if system is _PLAN_SYSTEM:
        return "{}"  # tryb demo: brak planu
    if system is _VERIFY_SYSTEM:
        return '{"complete": true, "notes": "[demo]", "missing": []}'
    return _mock_tech_answer(user_content)
