# Legacy Code Documenter & Tribal-Knowledge Q&A (T09)

Aplikacja Streamlit, która **indeksuje starszy kod Pythona**, odpowiada na pytania o
niego w języku naturalnym (z cytowaniami `plik:linia`), a następnie pozwala
**wygenerować, przetestować w piaskownicy i zacommitować poprawkę** — z człowiekiem
w pętli (human-in-the-loop) i automatycznym pipeline'em CI tworzącym Pull Request.

Model LLM: **Claude** (Anthropic) przez endpoint Azure AI Foundry. Bez klucza API
aplikacja działa w **trybie demonstracyjnym** (mockowane odpowiedzi) — patrz
[§ Integracja z LLM](#integracja-z-llm).

> 👤 **Nie jesteś programistą i chcesz tylko korzystać z aplikacji?**
> Zacznij od [Przewodnika użytkownika](docs/PRZEWODNIK_UZYTKOWNIKA.md) — prowadzi krok po
> kroku, zwykłym językiem. Ten README jest dokumentacją techniczną.

---

## Spis treści

1. [Szybki start](#szybki-start)
2. [Architektura](#architektura)
3. [Stack technologiczny](#stack-technologiczny)
4. [Struktura repozytorium](#struktura-repozytorium)
5. [Workflow aplikacji (4 kroki)](#workflow-aplikacji-4-kroki)
6. [Moduły i API wewnętrzne](#moduły-i-api-wewnętrzne)
7. [Integracja z LLM](#integracja-z-llm)
8. [Konfiguracja (zmienne środowiskowe)](#konfiguracja-zmienne-środowiskowe)
9. [Piaskownica i testy statyczne](#piaskownica-i-testy-statyczne)
10. [Dataset i model danych](#dataset-i-model-danych)
11. [Konteneryzacja](#konteneryzacja)
12. [CI/CD — pipeline AI Sandbox](#cicd--pipeline-ai-sandbox)
13. [Deployment (Kubernetes)](#deployment-kubernetes)
14. [Skrypty pomocnicze](#skrypty-pomocnicze)
15. [Ewaluacja](#ewaluacja)
16. [Bezpieczeństwo i ograniczenia](#bezpieczeństwo-i-ograniczenia)

---

## Szybki start

### Kontener (zalecane)

```bash
cp .env.docker.example .env.docker     # uzupełnij klucz Azure Anthropic (lub zostaw pusty → tryb demo)
podman compose up --build              # lub: docker compose up --build
# UI → http://localhost:8501
```

### Lokalnie

```bash
python -m venv .venv && .venv/Scripts/activate    # Windows; na Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # uzupełnij klucz lub zostaw pusty (tryb demo)
./run.sh                                           # = streamlit run app.py
```

### Ewaluacja (golden set)

```bash
python eval.py --repo sample --model claude-opus-4-8
```

---

## Architektura

Monolit Streamlit (jeden proces, port `8501`) realizujący lekki **RAG bez embeddingów**
(retrieval = wyszukiwanie po słowach kluczowych) + **agentową piaskownicę** zmian kodu.

```text
                          ┌─────────────────────────────────────────────┐
                          │            app.py  (Streamlit UI)            │
                          │   stepper: Ready → Analyze → Sandbox → PR    │
                          └───────┬───────────────┬──────────────┬───────┘
                                  │               │              │
              ingest_repo()       │  run_qa()     │  generate_   │  commit_and_
              keyword_search()     │               │  code_fix()  │  push_change()
                                  ▼               ▼              ▼
   ┌────────────────┐   ┌────────────────┐  ┌────────────┐  ┌─────────────────┐
   │  src/ingest.py │   │  src/agent.py  │  │ src/sandbox│  │  git push →     │
   │  AST → chunks  │──▶│  retrieve+LLM  │  │ exec testy │  │  ai-sandbox/<ts>│
   │ src/retriever  │   │  (Azure Claude │  │ static     │  │      ▼          │
   └────────────────┘   │   lub MOCK)    │  └────────────┘  │  GitHub Actions │
                        └────────────────┘                  │  → PR do develop│
                                                            └─────────────────┘
```

**Przepływ danych:** użytkownik wskazuje katalog z kodem → [ingest_repo](src/ingest.py)
parsuje pliki `.py` (AST) na `CodeChunk` → [keyword_search](src/retriever.py) wybiera
top-K fragmentów dla pytania → [run_qa](src/agent.py) buduje kontekst i woła LLM
(odpowiedź techniczna + analiza biznesowa + propozycje) → po akceptacji propozycji
[generate_code_fix](src/agent.py) tworzy poprawioną funkcję → [run_static_tests](src/sandbox.py)
wykonuje ją w izolowanym namespace → po przejściu testów [commit_and_push_change](src/sandbox.py)
commituje i wypycha branch `ai-sandbox/<timestamp>`, co uruchamia [pipeline CI](.github/workflows/sandbox-pr.yml).

---

## Stack technologiczny

| Warstwa | Technologia |
| --- | --- |
| UI | Streamlit ≥ 1.30 |
| Język | Python 3.12 (obraz) / 3.13+ (lokalnie) |
| LLM | Claude (`claude-opus-4-8`) via Azure AI Foundry (Anthropic Messages API) |
| HTTP | `requests` (bezpośrednie wywołania REST do endpointu) |
| Dane | `pandas` (tabele symboli, CSV golden set) |
| Konfiguracja | `python-dotenv` (`.env`) |
| Parsing kodu | `ast` (biblioteka standardowa) |
| Konteneryzacja | OCI / Docker / Podman ([Containerfile](Containerfile), [compose.yaml](compose.yaml)) |
| CI/CD | GitHub Actions ([sandbox-pr.yml](.github/workflows/sandbox-pr.yml)) |
| Deployment | Kubernetes (szkielet, [deploy/k8s/](deploy/k8s/)) |

> Uwaga: retrieval **nie używa embeddingów ani bazy wektorowej** — jest to celowo proste
> dopasowanie po tokenach (patrz [retriever.py](src/retriever.py)). Aspiracyjny opis z
> [docs/PLAN.md](docs/PLAN.md) (Qdrant, SQLite) **nie odzwierciedla** stanu kodu.

---

## Struktura repozytorium

```text
.
├── app.py                # Streamlit UI — punkt wejścia, workflow 4-krokowy
├── eval.py               # CLI evaluator (golden Q&A set)
├── run.sh                # lokalne uruchomienie (streamlit run app.py)
├── requirements.txt      # zależności Pythona
├── Containerfile         # obraz OCI (podman/docker build)
├── compose.yaml          # środowisko dev/demo (port 8501)
├── .env.example          # szablon konfiguracji lokalnej (placeholder klucza API)
├── .env.docker.example   # szablon konfiguracji dla compose
├── src/                  # logika rdzenia
│   ├── ingest.py         # AST → CodeChunk
│   ├── retriever.py      # wyszukiwanie po słowach kluczowych
│   ├── agent.py          # orkiestracja LLM + tryb demo (mock)
│   ├── sandbox.py        # testy statyczne, edycja pliku, commit/push
│   └── answer_types.py   # szablony odpowiedzi (biznesowy/techniczny)
├── scripts/              # skrypty CI / walidacji / health-check
├── docker/               # entrypoint kontenera + placeholder app
├── sample/               # domyślny dataset analizowany (używany przez app i CI)
├── deploy/k8s/           # manifesty Kubernetes
├── docs/                 # dokumentacja projektowa
└── test-endpoint/        # samodzielny test łączności z endpointem
```

---

## Workflow aplikacji (4 kroki)

UI ([app.py](app.py)) prowadzi przez stepper o czterech krokach. Stan trzymany jest w
`st.session_state` (sesje/wątki, zaindeksowane chunki, wyniki piaskownicy). Kroki
odblokowują się sekwencyjnie (`_completed_steps`).

| Krok | Nazwa | Co robi | Kluczowe wywołania |
| --- | --- | --- | --- |
| 1 | **System Ready** | Indeksowanie repozytorium (ścieżka z `REPO_PATH`, domyślnie `sample/`) | [ingest_repo](src/ingest.py) |
| 2 | **Analyze** | Pytanie w NL → odpowiedź techniczna z cytowaniami + widok biznesowy + 3 propozycje. Wybór szablonu odpowiedzi (biznesowy/techniczny). Akceptacja propozycji (human-in-the-loop). | [run_qa](src/agent.py) |
| 3 | **Piaskownica** | Agent generuje poprawioną funkcję; edytowalny diff; uruchomienie testów statycznych; pętla „napraw i uruchom ponownie"; zatwierdzenie i commit+push. | [generate_code_fix](src/agent.py), [fix_code_with_tests](src/agent.py), [run_static_tests](src/sandbox.py), [replace_function_in_file](src/sandbox.py), [commit_and_push_change](src/sandbox.py) |
| 4 | **PR** | Podsumowanie: branch źródłowy `ai-sandbox/<ts>` → `develop`, status push, link do Actions/PR, checklist. | — |

Krok 3 zawiera **świadomy false-positive** w testach (patrz [§ Piaskownica](#piaskownica-i-testy-statyczne)),
demonstrujący, że człowiek może zaakceptować znany błędny test, zamiast „naprawiać" poprawny kod.

---

## Moduły i API wewnętrzne

### [src/ingest.py](src/ingest.py) — parsowanie kodu

```python
@dataclass
class CodeChunk:
    file_path: str   # ścieżka względem korzenia repo
    symbol: str      # nazwa funkcji/klasy
    start_line: int
    end_line: int
    source: str      # surowy kod fragmentu

parse_python_file(filepath: Path, repo_root: Path) -> list[CodeChunk]
ingest_repo(repo_path: str) -> list[CodeChunk]
```

- `ingest_repo` rekurencyjnie (`rglob("*.py")`) parsuje wszystkie pliki Pythona.
- `ast.walk` zbiera **każdy** `FunctionDef`, `AsyncFunctionDef`, `ClassDef` — więc metody
  klasy oraz sama klasa stają się osobnymi (nakładającymi się) chunkami.
- Pliki z błędem składni / odczytu są pomijane (zwracają pustą listę).

### [src/retriever.py](src/retriever.py) — retrieval

```python
keyword_search(chunks: list[CodeChunk], query: str, top_k: int = 5) -> list[CodeChunk]
```

- Tokenizacja: `re.findall(r"\w+", text.lower())` → zbiór tokenów.
- Wynik = liczność przecięcia tokenów pytania z tokenami `symbol + source`.
- Zwraca top-K wg wyniku. **Fallback:** gdy żaden chunk nie ma wspólnych tokenów,
  zwraca **wszystkie** chunki (dzięki czemu LLM zawsze dostaje kontekst).

### [src/agent.py](src/agent.py) — orkiestracja LLM

```python
run_qa(question: str, repo_path: str, **_) -> dict
generate_code_fix(original_source: str, proposal: dict, question: str) -> str
fix_code_with_tests(source_code: str, failing_tests: list[dict]) -> str
llm_available() -> bool        # True gdy ustawiono klucz API
is_demo_mode() -> bool         # True gdy brak klucza → mock
```

`run_qa` wykonuje **dwa** wywołania LLM i zwraca słownik:

```python
{
  "answer": str,                  # odpowiedź techniczna z cytowaniami [source: plik:linia]
  "retrieved_chunks": [CodeChunk],
  "business_context": {           # lub None
      "impact", "area", "time_dev", "time_test", "time_total",
      "dependencies": [str], "risk", "summary"
  },
  "proposals": [                  # lista (zwykle 3)
      {"title", "description", "effort", "risk", "commit_hint"}
  ],
}
```

- Wywołanie 1 (`_TECH_SYSTEM`): zwięzła odpowiedź techniczna; system prompt wymusza
  cytowania i odmowę („Nie znaleziono w kodzie.") przy braku podstaw w kodzie.
- Wywołanie 2 (`_BIZ_SYSTEM`): **czysty JSON** parsowany przez `_extract_json` → kontekst
  biznesowy + propozycje. Błąd tego wywołania nie blokuje odpowiedzi technicznej.

### [src/sandbox.py](src/sandbox.py) — piaskownica i git

```python
run_static_tests(source_code: str) -> list[dict]
replace_function_in_file(chunk, new_source: str, repo_path: str) -> str   # zwraca abs_path
git_commit_file(file_path: str, message: str, repo_path: str) -> dict
commit_and_push_change(abs_path, message, repo_path, branch_prefix="ai-sandbox") -> dict
run_qa_eval(symbol: str, repo_path: str) -> list[dict]
STATIC_TESTS: list[dict]   # {name, fn, args, expected}
```

- `run_static_tests` kompiluje i wykonuje (`exec`) podany kod w izolowanym `namespace`
  wstępnie zasilonym `TAX_RATE` i `STOCK`; uruchamia tylko te testy, których nazwa funkcji
  występuje w kodzie. Wynik testu: `{name, passed, expected, got, error}`.
- `commit_and_push_change` commituje na bieżącym branchu, a następnie wypycha `HEAD` na
  **nowy** zdalny branch `ai-sandbox/<timestamp>` (`HEAD:refs/heads/...`, bez przełączania
  brancha lokalnego). Push uruchamia [pipeline CI](.github/workflows/sandbox-pr.yml).
  Autoryzacja: `GH_TOKEN`/`GITHUB_TOKEN` (w kontenerze) lub ambient credentials (`gh` na hoście).

### [src/answer_types.py](src/answer_types.py) — szablony odpowiedzi

```python
ANSWER_TYPES = {"business": {...}, "technical": {...}}
get_default_templates() -> dict   # głęboka kopia konfiguracji pól
```

Definiuje konfigurowalne pola dla widoku **biznesowego** (summary, czas, impact, ryzyko,
zależności) i **technicznego** (treść, ścieżka/linia, kod źródłowy). UI pozwala
włączać/wyłączać poszczególne pola.

> **Moduły eksperymentalne / niewpięte:** [src/doc_generator.py](src/doc_generator.py) i
> [src/jira_planner.py](src/jira_planner.py) nie są importowane przez `app.py` i odwołują
> się do nieistniejących symboli (`src.contracts`, `llm_complete`). Traktować jako szkice.

---

## Integracja z LLM

Rdzeniem jest funkcja `_call(system, user_content, max_tokens=1024)` w
[src/agent.py](src/agent.py):

```python
POST {AZURE_ANTHROPIC_ENDPOINT}
headers: x-api-key: <klucz>, anthropic-version: 2023-06-01, content-type: application/json
body:    { model: "claude-opus-4-8", max_tokens, system, messages: [{role:user, content}] }
timeout: 60 s
→ odpowiedź: json["content"][0]["text"]
```

Klucz pobierany jest przez `_api_key()`: `AZURE_ANTHROPIC_API_KEY` → fallback
`ANTHROPIC_API_KEY`. Endpoint domyślny: `https://ai-remik.services.ai.azure.com/anthropic/v1/messages`.

### Tryb demonstracyjny (mock)

Gdy **brak klucza API** (`_api_key()` puste), `_call` przekierowuje do `_mock_call` i
zwraca **przykładowe odpowiedzi** w tym samym formacie, jakiego oczekuje frontend:

- `_TECH_SYSTEM` → odpowiedź techniczna z atrapą cytowania, oznaczona jako demo,
- `_BIZ_SYSTEM` → poprawny JSON z kontekstem biznesowym i 3 propozycjami,
- `_FIX_SYSTEM`/`_FIX_TESTS_SYSTEM` → oryginalna funkcja z adnotacją demo (kod pozostaje
  uruchamialny, więc piaskownica i testy działają).

Dzięki temu cały workflow (Analyze → Piaskownica → PR) da się przeklikać bez modelu.
Po ustawieniu klucza kod **automatycznie** wraca do realnych wywołań — nic nie trzeba
przełączać. UI sygnalizuje stan banerem oraz statusem w panelu bocznym
(`🟡 Tryb demo` / `🟢 LLM Available`).

---

## Konfiguracja (zmienne środowiskowe)

Szablony: [.env.example](.env.example) (lokalnie, ładowane przez `load_dotenv()`),
[.env.docker.example](.env.docker.example) (dla compose).

| Zmienna | Domyślnie | Czytana przez | Opis |
| --- | --- | --- | --- |
| `AZURE_ANTHROPIC_API_KEY` | — | [agent.py](src/agent.py) `_api_key()` | Klucz API. **Pusty = tryb demo.** |
| `ANTHROPIC_API_KEY` | — | [agent.py](src/agent.py) `_api_key()` | Fallback klucza (bezpośrednie Anthropic API). |
| `AZURE_ANTHROPIC_ENDPOINT` | endpoint Azure | [agent.py](src/agent.py) | URL Messages API. |
| `REPO_PATH` | `sample` | [app.py](app.py) (domyślna ścieżka indeksowania) | Katalog analizowanego kodu. |
| `STREAMLIT_PORT` | `8501` | [docker/entrypoint.sh](docker/entrypoint.sh) | Port serwera. |
| `APP_ENTRYPOINT` | `app.py` | [docker/entrypoint.sh](docker/entrypoint.sh) | Plik startowy (fallback: placeholder). |
| `GH_TOKEN` / `GITHUB_TOKEN` | — | [sandbox.py](src/sandbox.py) | Token do push brancha `ai-sandbox/*`. |
| `LLM_PROVIDER`, `AZURE_AI_*` | — | (deklarowane w szablonach, **nieczytane** przez obecny kod) | Placeholdery na przyszłość. |

---

## Piaskownica i testy statyczne

[STATIC_TESTS](src/sandbox.py) to lista przypadków `{name, fn, args, expected}` dla funkcji
z `sample/` (`apply_discount`, `calculate_total`, `check_stock`). `run_static_tests`:

1. kompiluje i wykonuje (`exec`) podany kod w słowniku-namespace zasilonym `TAX_RATE=0.23`
   i mapą `STOCK`;
2. dla każdego testu, którego nazwa funkcji występuje w kodzie, wywołuje funkcję z `args`
   i porównuje `got == expected`;
3. zwraca listę wyników; błąd kompilacji/wykonania → `passed=False` z opisem.

**Świadomy false-positive:** test oznaczony `⚠️` zakłada, że `apply_discount(100, "PROMO10")`
zwróci `90.0` (cena po rabacie), podczas gdy funkcja zwraca `10.0` (kwotę rabatu). To celowo
błędny *test*, nie kod — UI automatycznie traktuje wyniki `⚠️` jako zaakceptowane, ilustrując
osąd człowieka w pętli.

---

## Dataset i model danych

[sample/](sample/) to celowo „zaniedbany" starszy kod (komentarze o nieobecnym autorze,
stan w pamięci, magiczne kody):

| Plik | Zawartość |
| --- | --- |
| [sample/billing.py](sample/billing.py) | `TAX_RATE`, `calculate_total(subtotal, discount_code=None)`, `apply_discount(total, code)` |
| [sample/inventory.py](sample/inventory.py) | `STOCK` (in-memory), `check_stock`, `reserve_item`, `release_item` |
| [sample/orders.py](sample/orders.py) | `STATUS_MAP`, `process_order(...)`, `cancel_order(...)` |
| [sample/questions.csv](sample/questions.csv) | golden set 10 pytań do ewaluacji |

Format `questions.csv`:

```text
id, question, expected_answer_location, expected_keywords, answer_type
```

- `answer_type`: `factual` (oczekiwana odpowiedź zawiera wszystkie `expected_keywords`)
  lub `refusal` (Q10 — system powinien odmówić, bo informacji nie ma w kodzie).
- `run_qa_eval(symbol, repo_path)` filtruje pytania powiązane z danym symbolem i punktuje
  odpowiedzi po trafieniu słów kluczowych.

---

## Konteneryzacja

[Containerfile](Containerfile) (zgodny z OCI — `podman build` i `docker build`):

- baza `python:3.12-slim`; instaluje `git` (sandbox/commit + pytest) i `ca-certificates` (TLS do Azure),
- warstwa zależności (`COPY requirements.txt` → `pip install`) cache'owana osobno od kodu,
- ustawia tożsamość git (`Legacy Documenter Bot`) dla commitów wykonywanych w kontenerze,
- `EXPOSE 8501` + `HEALTHCHECK` na `/_stcore/health`,
- `ENTRYPOINT ["docker/entrypoint.sh"]`.

[docker/entrypoint.sh](docker/entrypoint.sh): uruchamia `streamlit run $APP_ENTRYPOINT`
(domyślnie `app.py`); jeśli plik nie istnieje — startuje
[docker/placeholder_app.py](docker/placeholder_app.py) (strona statusu integracji T1–T5),
dzięki czemu obraz jest uruchamialny zanim kod aplikacji się pojawi.

[compose.yaml](compose.yaml) (dev/demo): bind-mount całego repo (`./:/app`, z `.git` —
sandbox commituje na realnym repo), wolumen `index-cache`, health-check na poziomie compose,
zmienne z `.env.docker`.

---

## CI/CD — pipeline AI Sandbox

[.github/workflows/sandbox-pr.yml](.github/workflows/sandbox-pr.yml) — wyzwalany przez
`push` na branch `ai-sandbox/**` (czyli przez krok „Piaskownica" w GUI) lub ręcznie
(`workflow_dispatch`).

Kroki (wszystkie w kontenerze zbudowanym z wypchniętego kodu):

1. **Build** obrazu `legacy-documenter:ci` z [Containerfile](Containerfile).
2. **Engine self-test** — [scripts/ci_sandbox_check.py](scripts/ci_sandbox_check.py): zasiewa
   regresję w `sample/billing.py`, sprawdza że test pada (RED), po czym że poprawka przechodzi (GREEN).
3. **PR gate** — [scripts/ci_validate_sample.py](scripts/ci_validate_sample.py): waliduje
   zacommitowany sample, generuje `ci_report.md` (artefakt).
4. **Smoke test** — [scripts/smoke_health.sh](scripts/smoke_health.sh): potwierdza, że GUI
   (Streamlit) startuje i odpowiada na health endpoint.
5. **Auto-PR** — przy sukcesie `gh pr create` otwiera Pull Request do `develop` (lub, gdy
   Actions nie mają uprawnień, drukuje gotowy link compare).

---

## Deployment (Kubernetes)

[deploy/k8s/](deploy/k8s/) zawiera minimalny, cloud-agnostyczny szkielet (namespace,
configmap, secret.example, deployment z probe'ami, service ClusterIP, ingress, kustomization).
Szczegóły i ostrzeżenia: [deploy/k8s/README.md](deploy/k8s/README.md) oraz
[docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md). Traktować jako punkt wyjścia, nie konfigurację produkcyjną.

---

## Skrypty pomocnicze

| Skrypt | Rola |
| --- | --- |
| [scripts/ci_sandbox_check.py](scripts/ci_sandbox_check.py) | Self-test silnika (seeded bug RED→GREEN) — używany w CI. |
| [scripts/ci_validate_sample.py](scripts/ci_validate_sample.py) | Bramka PR — walidacja zacommitowanego sample, raport `ci_report.md`. |
| [scripts/smoke_health.sh](scripts/smoke_health.sh) | Health-check: czy GUI bootuje w kontenerze. |
| [scripts/check_endpoints.py](scripts/check_endpoints.py) | Diagnostyka łączności z endpointem LLM (ręczna). |

---

## Ewaluacja

[eval.py](eval.py) — CLI uruchamiający „golden set" pytań przeciwko `run_qa` i punktujący
odpowiedzi (oczekiwany symbol / odmowa). Wymaga ustawionego `ANTHROPIC_API_KEY`.

```bash
python eval.py --repo sample --model claude-opus-4-8
```

---

## Bezpieczeństwo i ograniczenia

- **`run_static_tests` wykonuje `exec` na kodzie** generowanym/edytowanym przez użytkownika
  i LLM. Akceptowalne dla zaufanego sample'a w piaskownicy; **nie** uruchamiać na niezaufanym
  kodzie bez izolacji (kontener/sandbox systemowy).
- **`commit_and_push_change` wykonuje realne operacje git** (commit + push). W trybie demo
  można przeklikać workflow, ale przycisk „Zatwierdź i zacommituj" tworzy faktyczny commit.
- Sekrety (`.env`, `.env.docker`) są ignorowane przez git i `.dockerignore`; do obrazu **nie**
  trafiają — są wstrzykiwane runtime'owo. Nie commitować realnych kluczy.
- Retrieval jest leksykalny (bez embeddingów) — działa dobrze na małych repo/sample;
  dla dużych baz kodu wymagałby indeksu semantycznego.
- `LLM_PROVIDER` i `AZURE_AI_*` w szablonach env są placeholderami — obecny kod ich nie czyta.

---

## Dokumentacja projektowa

- 👤 **Dla użytkowników (nietechniczny):** [Przewodnik użytkownika](docs/PRZEWODNIK_UZYTKOWNIKA.md)

Pełne materiały (specyfikacja, plan, scenariusz demo, infrastruktura) w katalogu [docs/](docs/):
[SPEC.md](docs/SPEC.md) · [PLAN.md](docs/PLAN.md) · [HACKATHON.md](docs/HACKATHON.md) ·
[SCENARIO.md](docs/SCENARIO.md) · [REPO.md](docs/REPO.md) ·
[INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) ·
[TASK_AND_RULES_AND_REQUIREMENTS.md](docs/TASK_AND_RULES_AND_REQUIREMENTS.md)
