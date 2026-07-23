# shop-qa-ui

Aplikacja Streamlit — część systemu **ai-bot-playground**. Opisujesz zmianę w języku naturalnym → agent analizuje kod serwisów sklepu, planuje i generuje zmianę → lokalnie kompiluje ją i poprawia na podstawie błędów → wystawia **Pull Request do repozytorium serwisu** (bramka `preprod-gate` wykonuje pełną walidację i wdraża na preprod).

---

## Szybki start

```bash
cp .env.docker.example .env.docker   # uzupełnij OPENROUTER_API_KEY
podman compose up --build             # http://localhost:8501
```

Lokalnie:

```bash
pip install -r requirements.txt
cp .env.example .env                  # uzupełnij OPENROUTER_API_KEY
streamlit run app.py
```

---

## Konfiguracja

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **Wymagany.** Klucz OpenRouter |
| `OPENROUTER_MODEL` | `z-ai/glm-5.2` | Model |
| `OPENROUTER_REASONING_EFFORT` | `high` | Thinking (`high`/`medium`/`low`/`off`) |
| `OPENROUTER_MAX_TOKENS` | `32000` | Cap wyjścia |
| `SHOP_REPOS_DIR` | katalog nadrzędny | Katalog z lokalnymi klonami serwisów `shop-*` |
| `GH_TOKEN` / `GITHUB_TOKEN` | — | Token GitHub do wystawiania PR-ów |
| `TOKEN_METRICS_URL` | — | URL serwisu `shop-token-metrics` (opcjonalnie) |

Repozytoria do indeksowania: [`manifest.yaml`](manifest.yaml).

---

## Workflow

| Krok | Opis |
|---|---|
| **1 — System Ready** | Indeksuje serwisy `shop-*` z `manifest.yaml` (AST dla `.py`, leksykalnie dla Java/JS/TS) |
| **2 — Analyze** | Pytanie w NL → odpowiedź z cytowaniami `repo/plik:linia` + ocena wykonalności + propozycje |
| **3 — Piaskownica** | Planner dostaje trafne fragmenty realnego kodu; LLM generuje pliki; obowiązkowa walidacja w izolowanym worktree; błąd wraca do LLM do poprawy |
| **4 — PR** | PR jest dostępny dopiero po zielonej walidacji wszystkich zmienionych repo; następnie live status pełnej bramki `preprod-gate` co 15 s i merge z UI |

### Lokalna bramka przed PR

- Gradle: `classes testClasses --offline --no-daemon` — kompiluje kod i testy, ale nie uruchamia Testcontainers ani usług.
- React/Vite: `npm ci --offline`, następnie `npm run build`.
- Pozostałe repozytoria: walidacja składni JSON/YAML/Python i `git diff --check`.
- Błędy kompilacji trafiają do kroku naprawczego LLM. Braki JDK, Node lub pakietów w cache są oznaczane jako problemy środowiska i nie są wysyłane do LLM jako błędy kodu.

Pełny workflow uruchamiaj lokalnie z JDK 25, Node/npm i lokalnymi klonami `shop-*`. Przed pierwszą walidacją `shop-ui` wykonaj w nim `npm ci`, aby zapełnić cache używany później w trybie offline. Obecny `Containerfile` nie zawiera JDK/Node ani repozytoriów siostrzanych, więc sam wariant compose obsługuje UI/analizę, ale nie pełną lokalną bramkę.

---

## Struktura

```
app.py              — UI Streamlit (4 kroki)
src/
  ingest.py         — AST → CodeChunk
  retriever.py      — keyword_search
  agent.py          — OpenRouter: analiza, plan oparty na kodzie, generowanie i naprawa z logu
  sandbox.py        — izolowana walidacja worktree, open_pr_for_files, pr_checks, merge_pr
tests/              — testy planowania, naprawy i lokalnej bramki
manifest.yaml       — lista serwisów shop-* do indeksowania
deploy/k8s/         — manifesty Kubernetes
```

---

## CI

[`pr-check.yml`](.github/workflows/pr-check.yml): build obrazu + smoke test Streamlit (GitHub-hosted runner).
