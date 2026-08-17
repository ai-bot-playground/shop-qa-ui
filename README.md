# shop-qa-ui

Aplikacja Streamlit — część systemu **ai-bot-playground**. Opisujesz zmianę w języku naturalnym → agent analizuje kod serwisów sklepu, planuje i generuje zmianę → lokalnie kompiluje ją i poprawia na podstawie błędów → wystawia **Pull Request do repozytorium serwisu** (bramka `preprod-gate` wykonuje pełną walidację i wdraża na preprod).

---

## Szybki start

Pełny przepływ działa **natywnie** (na tej maszynie jest tylko Windows PowerShell 5.1 — `pwsh` nie istnieje):

```bash
powershell -File run-local.ps1
```

Tryb offline — cały workflow bez klucza, bez sieci i bez kosztów (atrapa LLM):

```bash
powershell -File run-local.ps1 -Fake
```

Wariant kontenerowy (**tylko indeksowanie i analiza** — patrz „Ograniczenia"):

```bash
cp .env.docker.example .env.docker   # uzupełnij OPENROUTER_API_KEY
podman compose up --build             # http://localhost:8501
```

---

## Konfiguracja

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **Wymagany** (poza trybem offline). Klucz OpenRouter |
| `OPENROUTER_MODEL` | `z-ai/glm-5.2` | Model |
| `OPENROUTER_REASONING_EFFORT` | `high` | Thinking (`high`/`medium`/`low`/`off`) |
| `OPENROUTER_MAX_TOKENS` | `32000` | Cap wyjścia |
| `QA_FAKE_LLM` | — | `1` → atrapa offline ([`src/fake_llm.py`](src/fake_llm.py)): deterministyczne odpowiedzi, zero wywołań sieciowych |
| `SHOP_REPOS_DIR` | katalog nadrzędny | Katalog z lokalnymi klonami serwisów `shop-*` |
| `TOKEN_METRICS_URL` | — | URL serwisu `shop-token-metrics` (opcjonalnie) |

Uwierzytelnienie do GitHuba idzie przez zalogowane `gh` i Windows Credential Manager — aplikacja nie czyta żadnego tokenu ze zmiennych środowiskowych.

Repozytoria do indeksowania: [`manifest.yaml`](manifest.yaml).

---

## Workflow

| Krok | Opis |
|---|---|
| **1 — System Ready** | Indeksuje serwisy `shop-*` z `manifest.yaml` (AST dla `.py`, leksykalnie dla Java/JS/TS) |
| **2 — Analyze** | Pytanie w NL → odpowiedź z cytowaniami `repo/plik:linia` + ocena wykonalności + propozycje |
| **3 — Piaskownica** | Planner dostaje trafne fragmenty realnego kodu; LLM generuje pliki; obowiązkowa walidacja w izolowanym worktree; błąd wraca do LLM do poprawy |
| **4 — PR** | PR jest dostępny dopiero po zielonej walidacji wszystkich zmienionych repo; następnie live status bramki `preprod-gate` co 15 s, podgląd na preprod i **merge z UI** (per repo, za potwierdzeniem człowieka). Gdy wszystkie PR-y osiągną stan końcowy, auto-odświeżanie się wyłącza |

### Lokalna bramka przed PR

- Gradle: `classes testClasses --offline --no-daemon` — kompiluje kod i testy, ale nie uruchamia Testcontainers ani usług.
- React/Vite: `npm ci --offline`, następnie `npm run build`.
- Pozostałe repozytoria: walidacja składni JSON/YAML/Python i `git diff --check`.
- Błędy kompilacji trafiają do kroku naprawczego LLM. Braki JDK, Node lub pakietów w cache są oznaczane jako problemy środowiska i nie są wysyłane do LLM jako błędy kodu.

Pełny workflow uruchamiaj lokalnie z JDK 25, Node/npm i lokalnymi klonami `shop-*`. Przed pierwszą walidacją `shop-ui` wykonaj w nim `npm ci`, aby zapełnić cache używany później w trybie offline.

### Ograniczenia wariantu kontenerowego / k8s

`Containerfile` nie zawiera JDK, Node, `gh` ani repozytoriów siostrzanych, a ConfigMap nie ustawia `SHOP_REPOS_DIR` — pod na `:8501` obsługuje więc **wyłącznie indeksowanie i analizę**. Lokalna walidacja i wystawianie PR-ów działają tylko w wariancie natywnym (`run-local.ps1`, port `8502`).

### Znany bloker środowiskowy

Jeśli walidacja Gradle kończy się `java.io.IOException: Unable to establish loopback connection`, problem jest poza tym repozytorium — na tej maszynie `java.nio.channels.Selector.open()` nie potrafi zestawić pary socketów na loopbacku (dotyczy JDK 21 i 25, więc każdy build Gradle i każdy serwis na Netty). Aplikacja klasyfikuje to jako awarię **środowiska**, nie kodu, i nie wysyła takiego logu do LLM. Szybkie sprawdzenie:

```bash
echo 'try (var s = java.nio.channels.Selector.open()) { System.out.println("LOOPBACK OK"); } catch (Exception e) { System.out.println("FAIL: " + e); }' | jshell -q --execution local -
```

---

## Struktura

```
app.py              — UI Streamlit (4 kroki)
src/
  ingest.py         — AST → CodeChunk (ścieżki POSIX)
  retriever.py      — keyword_search
  agent.py          — OpenRouter: analiza, plan oparty na kodzie, generowanie i naprawa z logu
  fake_llm.py       — atrapa offline (QA_FAKE_LLM=1): deterministyczne odpowiedzi bez sieci
  sandbox.py        — izolowana walidacja worktree, open_pr_for_files, pr_checks, merge_pr
tests/              — planowanie, naprawa, lokalna bramka, tryb offline + testy UI (AppTest)
manifest.yaml       — lista serwisów shop-* do indeksowania
deploy/k8s/         — manifesty Kubernetes (namespace `shop`)
```

---

## Testy

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Testy UI korzystają ze `streamlit.testing.v1.AppTest` — uruchamiają prawdziwe `app.py` na atrapie LLM, bez przeglądarki, klucza i sieci.

---

## CI

[`pr-check.yml`](.github/workflows/pr-check.yml): `pytest` (na atrapie offline) + build obrazu + smoke test Streamlit (GitHub-hosted runner).
