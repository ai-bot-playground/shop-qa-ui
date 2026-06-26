# CLAUDE.md — Legacy Code Documenter & Tribal-Knowledge Q&A (T09)

Zwięzły przewodnik dla Claude Code. Pełna dokumentacja techniczna: [README.md](../README.md).
Przewodnik dla użytkownika (nietechniczny): [docs/PRZEWODNIK_UZYTKOWNIKA.md](../docs/PRZEWODNIK_UZYTKOWNIKA.md).

## Czym jest projekt

Monolit Streamlit (port `8501`): indeksuje kod Pythona (AST), odpowiada na pytania w języku
naturalnym **z cytowaniami `plik:linia`** (LLM Claude przez Azure AI Foundry), generuje i
testuje poprawki w piaskownicy, commituje zmianę i otwiera PR. Retrieval jest **leksykalny
(bez embeddingów)** — to celowe uproszczenie.

## Mapa kodu

- [app.py](../app.py) — UI Streamlit; workflow 4-krokowy: `System Ready → Analyze → Piaskownica → PR`.
- [src/ingest.py](../src/ingest.py) — AST → `CodeChunk` (`ingest_repo`).
- [src/retriever.py](../src/retriever.py) — `keyword_search` (dopasowanie po tokenach).
- [src/agent.py](../src/agent.py) — orkiestracja LLM: `_call` → Azure Anthropic Messages API;
  `run_qa`, `generate_code_fix`, `fix_code_with_tests`. **Tryb demo (mock)** gdy brak klucza
  (`is_demo_mode`).
- [src/sandbox.py](../src/sandbox.py) — `STATIC_TESTS`, `run_static_tests` (**`exec`!**),
  `replace_function_in_file`, `commit_and_push_change`.
- [src/answer_types.py](../src/answer_types.py) — szablony odpowiedzi (biznesowy/techniczny).
- [sample/](../sample/) — dataset (billing/inventory/orders + `questions.csv`).
  **UWAGA:** katalog `examples/` został usunięty — używaj `sample/`.
- [scripts/](../scripts/) — `ci_sandbox_check.py`, `ci_validate_sample.py`, `smoke_health.sh`, `check_endpoints.py`.
- [Containerfile](../Containerfile), [compose.yaml](../compose.yaml), [docker/](../docker/) — konteneryzacja.
- [.github/workflows/sandbox-pr.yml](../.github/workflows/sandbox-pr.yml) — CI: push na `ai-sandbox/**`
  → walidacja w Dockerze → PR do `develop`.

## Uruchomienie i testy (Windows)

- **Demo lokalnie:** użyj skilla `/run-demo` (venv + Streamlit headless na `:8501`, wymusza tryb demo).
- **Testy silnika:** `/sandbox-check` (= `scripts/ci_*.py`).
- Python: lokalnie **3.14** w `.venv` (zależności z [requirements.txt](../requirements.txt)); obraz: **3.12**.
- Na Windows ustawiaj `PYTHONUTF8=1` — domyślna konsola (cp1250) wywala się na znakach Unicode/emoji.
- Ścieżka venv: `.venv/Scripts/python.exe`.

## Zasady (WAŻNE)

- **Nie zmieniaj sposobu działania aplikacji**, chyba że użytkownik wprost o to prosi.
- **Piaskownica wykonuje REALNE operacje git.** `commit_and_push_change` commituje na bieżącym
  branchu i pushuje `ai-sandbox/<ts>` (uruchamia CI). Branch `main` zasila PR-y do `develop` —
  **przy commitach najpierw twórz osobny branch; nie commituj przypadkiem na `main`.**
- `run_static_tests` używa `exec` na kodzie — bezpieczne tylko dla zaufanego `sample/`, nie dla
  niezaufanego kodu bez izolacji.
- **Tryb demo:** bez klucza API odpowiedzi są mockowane (patrz `src/agent.py`). Placeholdery klucza:
  [.env.example](../.env.example), [.env.docker.example](../.env.docker.example). Kod czyta
  `AZURE_ANTHROPIC_API_KEY` → fallback `ANTHROPIC_API_KEY`, oraz `AZURE_ANTHROPIC_ENDPOINT`.
- **Język:** UI, komentarze i dokumentacja są po polsku — zachowaj tę konwencję.
- Nie commituj: `__pycache__`, `.venv`, `.env*` (poza `*.example`), `streamlit.log`.

## Model LLM

Domyślny model: **`claude-opus-4-8`** (Azure AI Foundry, Anthropic Messages API,
`anthropic-version: 2023-06-01`). Najnowsze modele Claude to rodzina 4.X (Opus 4.8, Sonnet 4.6,
Haiku 4.5) oraz Fable 5 — przy nowych integracjach używaj najnowszych i najmocniejszych.
