import json
import os
import re

import requests
from dotenv import load_dotenv

from . import fake_llm
from .ingest import ingest_repo, ingest_app, CodeChunk
from .retriever import keyword_search

load_dotenv()

# OpenRouter (OpenAI-compatible) — jedyna aktywna ścieżka LLM.
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

# Procedura, którą LLM ma wykonać, planując i generując zmianę obejmującą CAŁY system.
# Wstrzykiwana do plannera i recenzenta kompletności, aby zmiana była KOMPLETNA
# (wszystkie warstwy) i SPÓJNA (jedna pisownia pojęć) oraz zgodna z bramką preprod-gate.
_CHANGE_PLAYBOOK = """\
PROCEDURA WPROWADZANIA ZMIAN W CAŁYM SYSTEMIE (wykonaj krok po kroku):

KROK 1 — ZASIĘG PRZEZ WARSTWY. Ustal, których warstw dotyka zmiana, i uwzględnij KAŻDĄ
potrzebną (myśl w tej kolejności: dane → logika → zdarzenia → API → frontend → konfiguracja → testy):
  1. DANE: nowa/zmieniona kolumna → NOWA migracja Flyway `V{N+1}__opis.sql` (NIGDY nie edytuj
     już zastosowanej migracji) + encja JPA + repozytorium. `ddl-auto=none`, więc schemat
     musi wynikać z migracji, nie z encji.
  2. LOGIKA: klasa @Service z regułą biznesową; zachowaj niezmienniki sagi, idempotencję
     i outbox (patrz KROK 3).
  3. ZDARZENIA (Kafka): jeśli zmienia się kształt zdarzenia — zmień PRODUCENTA (budowa payloadu
     w service/outbox) ORAZ WSZYSTKICH KONSUMENTÓW tego tematu we WSZYSTKICH serwisach.
     Kontrakty zdarzeń to ręcznie składany JSON (brak wspólnej biblioteki): nowe pole trzeba
     WYPISAĆ u producenta i ODCZYTAĆ tam, gdzie potrzebne; brak pola konsument musi tolerować.
     Zachowaj klucz partycji (order-events/payment-events: orderId; inventory-events: productId).
  4. API: kontroler REST + DTO/response. Nowa publiczna ścieżka → dodaj też trasę w
     shop-gateway `application.yml` (`/api/...` -> serwis, `StripPrefix=1`).
  5. FRONTEND: shop-ui (React/JSX), jeśli zmiana jest widoczna dla użytkownika; wołaj przez
     `/api/*` (gateway); przy zapisie zachowaj nagłówek `Idempotency-Key`.
  6. KONFIGURACJA: `application.yml` (properties, flagi np. `shop.test-support.enabled`),
     `build.gradle` (nowe zależności). Env w helm/compose tylko jeśli konieczne.
  7. TESTY: zaktualizuj/dodaj scenariusze — per-serwis Cucumber (`.feature` + kroki),
     a dla zmian obserwowalnych cross-service scenariusz w shop-acceptance-tests. Testy są
     CZĘŚCIĄ zmiany (bramka je uruchamia), nie opcją.

KROK 2 — JEDEN SŁOWNIK (spójność między plikami). Zanim wygenerujesz pliki, ustal RAZ i używaj
DOKŁADNIE tych samych nazw we wszystkich plikach: pola/kolumny, wartości `type` zdarzeń, nazwy
tematów, ścieżki endpointów, pola DTO, wartości enum statusów. Nigdy nie twórz drugiej pisowni
tego samego pojęcia w innym pliku.

KROK 3 — NIEZMIENNIKI (nie łam ich):
  - baza-na-serwis: nie odpytuj cudzej bazy; dane między serwisami płyną REST-em (sync, np.
    order→catalog po cenę) albo zdarzeniami Kafka (async).
  - idempotencja: konsumenci deduplikują po kluczu (`processed_events`); produkcja przez outbox;
    nie wprowadzaj podwójnego przetwarzania.
  - saga zamówienia: PENDING→RESERVED→CONFIRMED lub kompensacja (CANCELLED/REJECTED),
    `payment_deadline` + skaner timeoutów; zachowaj ścieżki kompensacji.
  - Flyway addytywnie; kod kompilowalny i zgodny ze stylem (Java/Spring: pakiet
    `com.shop.<serwis>...`; React/Vite dla shop-ui).

KROK 4 — MINIMALNIE, ALE KOMPLETNIE. Ruszaj tylko to, co konieczne, ale dołącz KAŻDY plik
potrzebny, by zmiana działała end-to-end (żadnych wiszących odwołań: dodajesz pole DTO →
zaktualizuj mapowanie/użycie; importujesz nową klasę → utwórz ją).

KROK 5 — DEFINICJA UKOŃCZENIA (= bramka preprod-gate). Zestaw plików musi: (a) się kompilować,
(b) utrzymać zielone testy komponentowe każdego dotkniętego serwisu (zaktualizuj je, jeśli
zmieniłeś zachowanie), (c) utrzymać/rozszerzyć zielony pakiet akceptacyjny cross-service.
Zmieniasz zachowanie widoczne z zewnątrz → test to potwierdzający MUSI być w planie.\
"""

# Skrócone zasady spójności — wstrzykiwane przy generowaniu POJEDYNCZEGO pliku
# (tańsze niż pełna procedura, a pilnują najważniejszego: jednej pisowni i kompilowalności).
_CONSISTENCY_RULES = """\
ZASADY SPÓJNOŚCI (dla generowanego pliku, ma pasować do reszty zestawu zmiany):
- Używaj DOKŁADNIE tych samych nazw (pól/kolumn/`type` zdarzeń/tematów/endpointów/DTO/statusów)
  co w pozostałych plikach zmiany — jedna pisownia pojęcia w całym systemie.
- Kod kompilowalny i zgodny ze stylem warstwy (Java/Spring; React/JSX dla shop-ui).
- Zdarzenia Kafka: producent WYPISUJE nowe pole, konsument potrafi je ODCZYTAĆ/zignorować;
  nie zmieniaj klucza partycji.
- Migracje Flyway tylko addytywnie (nowy plik `V{N+1}`), nigdy edycja zastosowanej migracji.
- Nie odwołuj się do klas/plików, których ta zmiana nie tworzy; nie łam idempotencji ani sagi.\
"""


def _openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "")


def _fake_llm_enabled() -> bool:
    """QA_FAKE_LLM=1 → tryb offline: zero wywołań sieciowych, zero kosztów.

    Czytane przy każdym wywołaniu (nie raz przy importcie), żeby dało się
    przełączyć tryb bez restartu procesu Streamlita.
    """
    return os.environ.get("QA_FAKE_LLM", "").strip().lower() not in ("", "0", "false", "no", "off")


def _call(system: str, user_content: str, max_tokens: int = 1024, light: bool = False) -> str:
    if _fake_llm_enabled():
        # `_FAKE_KINDS` mapuje prompt systemowy → rodzaj odpowiedzi atrapy;
        # definicja stoi pod ostatnim promptem (`_EXPAND_SYSTEM`).
        return fake_llm.respond(_FAKE_KINDS.get(system, ""), user_content)
    return _call_openrouter(system, user_content, max_tokens, light=light)


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


def _call_openrouter(system: str, user_content: str, max_tokens: int,
                     light: bool = False) -> str:
    headers = {
        "Authorization": f"Bearer {_openrouter_key()}",
        "Content-Type": "application/json",
    }
    # light=True — tanie zadania pomocnicze (np. ekspansja zapytania): bez
    # rozumowania i bez podłogi 32k na wyjście, żeby nie płacić pełnego thinkingu
    # za drobny krok. Główne wywołania (odpowiedź, analiza, plan, weryfikacja)
    # zostają na pełnym thinkingu z dużym budżetem wyjścia.
    if light:
        out_cap = max_tokens
        reasoning: dict = {"enabled": False}
    else:
        # Duży budżet wyjścia, by rozumowanie nie ucięło odpowiedzi.
        out_cap = max(max_tokens, _OPENROUTER_MAX_TOKENS)
        reasoning = _reasoning_param()
    payload = {
        "model": _OPENROUTER_MODEL,
        "max_tokens": out_cap,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "reasoning": reasoning,
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
Jesteś ekspertem od kodu tego systemu. Odpowiadasz NA PODSTAWIE KODU który dostałeś — nic więcej.

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

Twoje zadanie: zaplanuj KTÓRE pliki zmienić i JAKIE nowe utworzyć, aby zrealizować zmianę
end-to-end w całym systemie. Przejdź PROCEDURĘ WPROWADZANIA ZMIAN krok po kroku i po kolei
przez warstwy: dane (Flyway/encje) → logika (@Service, saga) → zdarzenia (Kafka: producent
+ WSZYSCY konsumenci) → API (kontroler/DTO + trasa w gateway) → frontend (shop-ui) →
konfiguracja (application.yml/build.gradle) → testy (Cucumber per-serwis + acceptance).

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
- "modify" dla istniejących plików (muszą być w MAPIE), "create" dla nowych (ścieżka zgodna
  z konwencją pakietu/katalogu serwisu).
- Uwzględnij KAŻDĄ warstwę, której zmiana dotyka — nie pomijaj migracji Flyway, konsumentów
  zdarzeń, trasy w gateway, frontendu ani TESTÓW (bramka je uruchamia).
- Zmieniasz kształt zdarzenia Kafka → zaplanuj producenta ORAZ wszystkich konsumentów danego
  tematu we wszystkich serwisach.
- Plan minimalny, ale KOMPLETNY (bez wiszących odwołań). Nie dodawaj plików nieistotnych.
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
- czy warstwy się spinają (dane → logika → zdarzenia → API/gateway → UI),
- czy przy zmianie schematu jest migracja Flyway (`V{N+1}`) spójna z encją,
- czy przy zmianie zdarzenia Kafka zmieniono producenta ORAZ wszystkich konsumentów tematu,
- czy nowej publicznej ścieżce API towarzyszy trasa w shop-gateway,
- czy zmiana zachowania ma pokrycie w testach (Cucumber per-serwis / acceptance) — bramka je uruchomi.

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

_REPAIR_FILE_SYSTEM = """\
Jesteś senior developerem naprawiającym wygenerowaną zmianę po lokalnej walidacji.
Otrzymasz pełną treść jednego pliku, zestaw pozostałych plików zmiany oraz dokładny log błędu.

Zasady:
1. Najpierw ustal z LOGU WALIDACJI, czy wskazany plik jest przyczyną błędu.
2. Jeśli tak, zwróć WYŁĄCZNIE pełną poprawioną treść tego pliku — bez markdown i wyjaśnień.
3. Zachowaj żądaną funkcjonalność oraz spójność nazw/kontraktów z pozostałymi plikami.
4. Nie maskuj błędu przez usuwanie funkcjonalności, wyłączanie testów ani pomijanie walidacji.
5. Jeśli ten plik nie wymaga zmiany, odpowiedz DOKŁADNIE: BRAK_ZMIAN.\
"""


def _strip_fences(text: str) -> str:
    """Usuń ewentualne ogrodzenia ```diff / ``` z odpowiedzi modelu."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip("\n")


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
        f"{_CONSISTENCY_RULES}\n\n"
        f"PLIK: {file_path}\n```\n{file_source}\n```\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"Zwróć pełną zaktualizowaną treść pliku:"
    )
    # Realne błędy (np. TLS/serwer) NIE są maskowane — propagujemy je do UI.
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


def plan_change(question: str, repo_map: str, proposals: list[dict],
                retrieved_chunks: list[CodeChunk] | None = None) -> list[dict]:
    """LLM planuje pliki do zmiany/utworzenia w całej aplikacji (zamiast top-5 retrievalu).

    `repo_map` daje pełny zasięg aplikacji, a `retrieved_chunks` dostarcza rzeczywisty
    kod związany z żądaniem. Zwraca listę {repo, path, action: modify|create, reason}.
    Pusta lista przy błędzie lub w trybie demo.
    """
    props = "\n".join(
        f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or [])
    )
    code_context = _build_context(retrieved_chunks or [])
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"{_CHANGE_PLAYBOOK}\n\n"
        f"MAPA REPOZYTORIÓW (istniejące pliki i symbole):\n{repo_map}\n\n"
        f"TRAFNE FRAGMENTY RZECZYWISTEGO KODU (główne źródło decyzji):\n"
        f"{code_context or '(brak trafnych fragmentów)'}\n\n"
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
        f"{_CHANGE_PLAYBOOK}\n\n"
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
        f"{_CONSISTENCY_RULES}\n\n"
        f"NOWY PLIK DO UTWORZENIA: {repo}/{file_path}\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"Zwróć pełną treść nowego pliku:"
    )
    result = _strip_fences(_call(_NEWFILE_SYSTEM, user_msg, max_tokens=4096))
    return "" if _is_no_change(result) else result


def repair_file_change(question: str, proposals: list[dict], repo: str, file_path: str,
                       current_content: str, validation_output: str,
                       related_files: list[dict] | None = None) -> str:
    """Repair one generated file using an exact local build/validation failure.

    Returns the full corrected file, or "" when this file does not need a repair.
    """
    props = "\n".join(
        f"- {p.get('title', '')}: {p.get('description', '')}" for p in (proposals or [])
    )
    related_sections: list[str] = []
    related_budget = 24000
    for related in (related_files or []):
        related_repo = related.get("repo") or repo
        related_path = related.get("path") or related.get("file_path") or ""
        if related_repo == repo and related_path == file_path:
            continue
        content = related.get("content")
        if content is None:
            content = related.get("new_content") or ""
        section = f"### {related_repo}/{related_path}\n{str(content)[:6000]}"
        if related_budget - len(section) < 0:
            break
        related_sections.append(section)
        related_budget -= len(section)
    related_context = "\n\n".join(related_sections) or "(brak innych plików)"
    failure_tail = (validation_output or "")[-16000:]
    user_msg = (
        f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\n"
        f"{_CONSISTENCY_RULES}\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        f"Zaakceptowane propozycje:\n{props or '(brak)'}\n\n"
        f"LOG WALIDACJI (źródło prawdy):\n{failure_tail}\n\n"
        f"POZOSTAŁE PLIKI ZMIANY W TYM REPO:\n{related_context}\n\n"
        f"PLIK DO OCENY I EWENTUALNEJ NAPRAWY: {repo}/{file_path}\n"
        f"```\n{current_content}\n```\n\n"
        f"Zwróć pełną poprawioną treść albo BRAK_ZMIAN:"
    )
    result = _strip_fences(_call(_REPAIR_FILE_SYSTEM, user_msg, max_tokens=4096))
    return "" if _is_no_change(result) else result


_EXPAND_SYSTEM = """\
Jesteś pomocnikiem wyszukiwania kodu w systemie opisanym w KONTEKST SYSTEMU.
Dostajesz pytanie w języku naturalnym (po polsku). Zwróć angielskie słowa-klucze
i prawdopodobne identyfikatory w kodzie (nazwy klas / metod / pól / plików /
tematów Kafka / kolumn), które warto wyszukać, by znaleźć odpowiedni kod.

Odpowiedz WYŁĄCZNIE prawidłowym JSON (bez markdown, bez zdań):
{"terms": ["Payment", "PaymentRequested", "payment-events", "calculateFee", "..."]}

Zasady:
- 8–20 termów, pojedyncze słowa/identyfikatory (NIE całe zdania).
- Tłumacz pojęcia biznesowe z pytania na angielskie terminy techniczne
  (np. "opłata"->fee/charge, "zamówienie"->order, "magazyn"->inventory/stock,
  "płatność"->payment, "powiadomienie"->notification, "anulowanie"->cancel).
- Uwzględnij nazwy serwisów/tematów z KONTEKSTU SYSTEMU, jeśli pasują.\
"""


# Mapa promptów systemowych → rodzaje odpowiedzi atrapy offline (QA_FAKE_LLM=1).
# Musi stać PO definicjach wszystkich promptów; `_call` sięga po nią w czasie
# wywołania, nie importu. Nieobecny prompt → atrapa zwraca BRAK_ZMIAN.
_FAKE_KINDS = {
    _EXPAND_SYSTEM: "expand",
    _TECH_SYSTEM: "tech",
    _BIZ_SYSTEM: "biz",
    _PLAN_SYSTEM: "plan",
    _VERIFY_SYSTEM: "verify",
    _FILECHANGE_SYSTEM: "filechange",
    _NEWFILE_SYSTEM: "newfile",
}


def expand_query(question: str) -> list[str]:
    """NL (PL) → lista angielskich haseł/identyfikatorów do wyszukiwania.

    Domyka lukę słownikową między polskim pytaniem a angielskim kodem. Tanie
    wywołanie (light=bez rozumowania). Pusta lista przy błędzie/braku klucza —
    wtedy keyword_search działa na samym pytaniu (degradacja łagodna).
    """
    user_msg = f"KONTEKST SYSTEMU:\n{_SHOP_FACTS}\n\nPYTANIE: {question}\n\nZwróć JSON z termami:"
    try:
        data = _extract_json(_call(_EXPAND_SYSTEM, user_msg, max_tokens=400, light=True))
    except Exception:
        return []
    terms = data.get("terms") or []
    out: list[str] = []
    for t in terms:
        s = str(t).strip()
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out[:30]


def run_qa(question: str, repo_path: str = "", chunks: list[CodeChunk] | None = None, **_kwargs) -> dict:
    """Odpowiada na pytanie o kod.

    Gdy `chunks` jest podany (pre-indexed, np. z ingest_app dla wielu repo),
    używa go bezpośrednio. W przeciwnym razie indeksuje `repo_path` (compat
    Gdy `chunks` podany używa go bezpośrednio, inaczej indeksuje `repo_path`.
    """
    all_chunks = chunks if chunks is not None else ingest_repo(repo_path)
    # Ekspansja zapytania (NL PL → angielskie identyfikatory w kodzie) domyka lukę
    # słownikową pytanie↔kod; wynik zasila leksykalne keyword_search.
    extra_terms = expand_query(question)
    relevant_chunks = keyword_search(all_chunks, question, top_k=8, extra_terms=extra_terms)

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


