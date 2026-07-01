# shop-qa-ui

Aplikacja Streamlit — część systemu **ai-bot-playground**. Opisujesz zmianę w języku naturalnym → agent analizuje kod serwisów sklepu, planuje i generuje zmianę → wystawia **Pull Request do repozytorium serwisu** (bramka `preprod-gate` waliduje i wdraża na preprod).

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
| **3 — Piaskownica** | LLM generuje zmienione/nowe pliki; opcjonalne `gradle test` w izolowanym worktree |
| **4 — PR** | PR do `main` serwisu (`git worktree` + `gh pr create`); live status bramki `preprod-gate` co 15 s; merge z UI |

---

## Struktura

```
app.py              — UI Streamlit (4 kroki)
src/
  ingest.py         — AST → CodeChunk
  retriever.py      — keyword_search
  agent.py          — wywołania OpenRouter (run_qa, plan_change, generate_file_change, …)
  sandbox.py        — open_pr_for_files, run_service_tests, pr_checks, merge_pr
manifest.yaml       — lista serwisów shop-* do indeksowania
deploy/k8s/         — manifesty Kubernetes
```

---

## CI

[`pr-check.yml`](.github/workflows/pr-check.yml): build obrazu + smoke test Streamlit (GitHub-hosted runner).
