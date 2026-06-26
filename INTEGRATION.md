# Integracja `shop-qa-ui` ← (acc-ai-hackathon) z platformą `ai-bot-playground`

> Żywy dokument — aktualizowany na bieżąco wraz z postępem prac.
> Tablica zadań: org `ai-bot-playground` → Projects → **AI** (karty z prefiksem `[QA*]`).
> Plan referencyjny: `~/.claude/plans/cryptic-enchanting-swan.md`.

## Cel
Przekuć narzędzie „Legacy Code Documenter" (Streamlit + Azure Anthropic `claude-opus-4-8`)
w **dev-frontend nad naszym sklepem**: użytkownik opisuje czego chce → LLM świadomy naszego
kodu ocenia wykonalność i uzgadnia testy → po akceptacji powstaje **PR do serwisu sklepu** →
**nasza bramka preprod** (component → build → deploy kind-preprod → acceptance) waliduje i
wdraża kandydata na preprod, gdzie użytkownik sprawdza efekt. Repo trafi do org jako
`ai-bot-playground/shop-qa-ui` (po potwierdzeniu).

## Kluczowa decyzja architektoniczna
**Walidacją jest nasza bramka preprod, nie pythonowy sandbox.** Pythonowy `run_static_tests`
(`exec()` funkcji) nie pasuje do Javy/Spring. Tool: rozumie kod → proponuje diff → wystawia
PR → pokazuje status bramki + podgląd preprod. Edycja startowo skupiona (1 serwis), z
człowiekiem akceptującym diff (human-in-the-loop).

## Decyzje przyjęte
- Parser Javy: **lekki regex** (bez nowych zależności) — zgodnie z zasadą „nie instaluj".
- Pierwszy serwis PoC: **shop-notification** (najmniejsze ryzyko pierwszej realnej zmiany).
- PR celuje w **`main`** serwisu (tam jest wymagana bramka `preprod-gate / gate`).

## Postęp etapów
| Etap | Zakres | Status |
|---|---|---|
| 0 | Hygiena repo + rebrand (acc-ai-hackathon → shop-qa-ui) | 🟡 w toku (rebrand; rename+push w Etapie 6) |
| 1 | Indeksacja Javy w `ingest.py` + wybór serwisu w `app.py` | ✅ **DONE — zweryfikowane realnie** (GLM-5.2: odpowiedź z trafnymi `plik:linia` nad shop-notification) |
| 2 | LLM świadomy systemu: werdykt wykonalności + plan testów | ✅ **DONE — zweryfikowane realnie** (GLM-5.2: feasibility „Tak" + plan testów wskazał NASZE scenariusze Cucumber) |
| 3 | Zmiana jako diff + PR do `ai-bot-playground/<serwis>` (main) | ✅ code-complete (agent `generate_change_diff`; sandbox `open_pr_for_change` na klonie; UI diff-review) — realny PR przy uruchomieniu z kluczem API |
| 4 | Status bramki preprod-gate + podgląd kandydata na preprod | ✅ code-complete (`pr_checks` + render statusu + instrukcja port-forward) |
| 5 | Merge human-in-the-loop po zielonej bramce | ✅ code-complete (`merge_pr` + przycisk za checkboxem potwierdzenia) |
| 6 | Pakowanie/rebrand + push `shop-qa-ui` do org (po potwierdzeniu) | 🟡 w toku (rebrand kodu; rename+push po potwierdzeniu) |

## Zmiany w kodzie (dziennik)
- `src/ingest.py` — dodano `parse_java_file` (regex + dopasowanie klamr po głębokości; pomija
  wywołania na depth ≥ 2), dispatcher `.py`/`.java`, pomijanie `build/.git/target/...`.
  Zweryfikowane na `shop-notification` (klasy, metody, konstruktor, interfejs repo).
- `app.py` — sidebar: selectbox serwisu sklepu (z `SHOP_REPOS_DIR`, domyślnie shop-notification)
  + text-override; podświetlanie źródeł jako `java`; przechowywanie i render `feasibility` +
  `test_plan` w sekcji biznesowej.
- `src/agent.py` — `_SHOP_FACTS` (fakty o systemie) wstrzykiwane do kontekstu LLM; `_BIZ_SYSTEM`
  rozszerzony o `feasibility` (werdykt + powód + dotknięte serwisy/pliki) i `test_plan`
  (istniejące/nowe scenariusze); `run_qa` zwraca te pola; mock je wypełnia.
- `src/answer_types.py` — dodane pola szablonu biznesowego: `Wykonalność`, `Plan testów`.
- Smoke: `run_qa` (demo) nad `shop-notification` zwraca feasibility+test_plan+3 propozycje.
- Indeksacja **wszystkich serwisów** (walidacja parsera Javy, 0 luk): gateway 1/1, catalog 12/12,
  inventory 21/21, order 22/22, payment 13/13, notification 9/9 — **323 chunki, 100% plików .java**.
  Saga `OrderService` sparsowana w całości (createOrder, handleInventoryEvent, handlePaymentEvent,
  cancelTimedOutSagas, cancelAndCompensate, …).
- `src/agent.py` — `_DIFF_SYSTEM` + `generate_change_diff(question, proposals, chunks)`: zmiana jako
  unified diff (świadoma systemu), mock zwraca pusty diff (demo). `_strip_fences`.
- `src/sandbox.py` — `check_diff_applies` (git apply --check), `open_pr_for_change` (klon temp →
  branch → apply → push → `gh pr create --base main`), `pr_checks` (status bramki), `merge_pr`
  (gh pr merge --squash). Smoke: difflib-diff przechodzi `git apply --check` na shop-notification.
- `app.py` — krok „Piaskownica": dla plików `.java` ścieżka diff→PR (review diff, apply-check,
  „Wystaw PR do serwisu"); krok „PR": status `preprod-gate / gate`, instrukcja port-forward na
  preprod, merge za checkboxem potwierdzenia. Ścieżka Python (sample) zachowana.
- `src/agent.py` — dyspozytor providera: **OpenRouter** (OpenAI-compatible, `Bearer`,
  `/chat/completions`, `choices[0].message.content`) → Azure Anthropic → mock; model z
  `OPENROUTER_MODEL`. `.env`: `OPENROUTER_API_KEY` + `OPENROUTER_MODEL=z-ai/glm-5.2` (gitignored).
- **Weryfikacja realna (GLM-5.2 przez OpenRouter):** `run_qa` nad shop-notification → odpowiedź
  z cytowaniami `NotificationService.java:38-44/:39`, `SentNotification.java:11-13`; feasibility
  „Tak"; plan testów wskazał istniejące scenariusze Cucumber. Etap 1+2 potwierdzone E2E.
- **Odkrycie + pivot (Etap 3):** LLM-owy unified diff bywa „corrupt patch" (błędne liczniki `@@`,
  brak spacji w pustej linii kontekstu) — `git apply` odrzucił poprawną semantycznie zmianę.
  Zmiana podejścia na **pełny plik**: `agent.generate_file_change` zwraca całą treść pliku,
  `sandbox.open_pr_for_file_change` nadpisuje plik w klonie i **git liczy diff/commit** (zero
  ryzyka uszkodzenia patcha). `sandbox.compute_diff` (difflib) służy tylko do podglądu w UI.
  Funkcje diff-owe zostają jako fallback. **Zweryfikowane realnie:** GLM-5.2 zwrócił pełny,
  poprawny `NotificationService.java`, podgląd diffa = dokładnie zmieniona linia.
- `src/agent.py` — **tryb thinking**: payload OpenRoutera dostał `reasoning` (domyślnie
  `effort=high`) + duży `max_tokens` (`_OPENROUTER_MAX_TOKENS`); `_strip_think` czyści `<think>`.
  **Zweryfikowane:** wywołanie GLM-5.2 zwróciło `usage.reasoning_tokens=102` (model realnie
  rozumuje) przy czystym `content`.
- `src/agent.py` — **telemetria tokenów**: do payloadu OpenRoutera dodany `usage:{include:true}`
  (zwraca koszt). Po każdym wywołaniu `_emit_token_metrics` POST-uje `usage` (prompt/completion/
  reasoning/total + cost) na `TOKEN_METRICS_URL/api/usage` do serwisu **shop-token-metrics**
  (best-effort, timeout 2 s, błędy połykane — nigdy nie psuje wywołania LLM). `.env`:
  `TOKEN_METRICS_URL` (puste = wyłączone) + `TOKEN_METRICS_SOURCE` (domyślnie `shop-qa-ui`).
  **Zweryfikowane realnie E2E:** realne wywołanie GLM-5.2 → liczniki na `/actuator/prometheus`
  serwisu: `llm_tokens_total{type=completion}=443`, `{type=prompt}=38`, `{type=reasoning}=436`,
  `llm_requests_total=1`, `llm_cost_usd_total=0.0020024` (tagi model/source/application).
- `src/ingest.py` — **parser front-endu** JS/TS/JSX/TSX/MJS (segmentacja po deklaracjach
  top-level + fallback całego pliku). Zweryfikowane na shop-ui: komponent `App` [15-98]
  obejmuje `<button>`. Umożliwia indeksację i zmiany w shop-ui.
- `app.py` — wszystkie pliki spoza `.py` (Java *i* front-end) idą ścieżką pełny plik → PR;
  podświetlanie składni wg rozszerzenia (`_lang_for`); komunikat przy pustej odpowiedzi
  rozróżnia tryb demo / błąd wywołania / niepasujący plik (już NIE myli „brak klucza").
- `src/agent.py` — `generate_file_change` nie maskuje już realnych błędów (np. TLS) jako
  pustki — propaguje je, by UI pokazał prawdziwą przyczynę.
- `src/sandbox.py` — **PR bez klonu z sieci**: `open_pr_for_file_change` używa lokalnego
  repo + `git worktree` (czysta gałąź z `origin/<base>`, izolacja — kopia robocza i bieżąca
  gałąź nietknięte; gałąź zawiera wyłącznie tę jedną zmianę). `_resolve_local_repo`
  (local_repo / `SHOP_REPOS_DIR`), baza worktree poza `%TEMP%` w `~/.shopqa-tmp`
  (override `SHOPQA_TMP`) — `%TEMP%` był blokowany przez EDR dla git.exe. **Zweryfikowane:**
  gałąź = `src/App.jsx | 1 +` wzgl. `origin/main`, brak wiszących worktree, kopia robocza nietknięta.

## Obserwowalność zużycia tokenów (Prometheus + Grafana)
Nowy serwis **`ai-bot-playground/shop-token-metrics`** (Spring Boot 4 + Micrometer) zbiera
zużycie tokenów LLM i wystawia je na `/actuator/prometheus`. `shop-qa-ui` po każdym wywołaniu
LLM POST-uje `usage` na `TOKEN_METRICS_URL/api/usage`. W klastrze (kind) Prometheus scrapuje
serwis, a Grafana rysuje dashboard **„LLM Token Usage"** (provisioning automatyczny).

- **Przepływ:** `shop-qa-ui` → `POST /api/usage` → Micrometer (`llm_tokens_total`,
  `llm_requests_total`, `llm_cost_usd_total`, tagi `type`/`model`/`source`) → `/actuator/prometheus`
  → Prometheus → Grafana.
- **Helm:** serwis w `shop-infra/helm/values.yaml` (`services.shop-token-metrics`); Prometheus+Grafana
  w `templates/infra-prometheus.yaml` + `infra-grafana.yaml`, włącznik `observability.enabled`.
- **Podgląd wykresu (lokalnie):**
  ```powershell
  kubectl --context kind-preprod -n shop port-forward svc/grafana 3000:3000
  # http://localhost:3000  -> dashboard "LLM Token Usage" (anonimowy dostęp, bez logowania)
  ```
- **Włączenie telemetrii w toolu:** w `.env` ustaw `TOKEN_METRICS_URL`, np. po
  `kubectl ... port-forward svc/shop-token-metrics 8088:8080` → `TOKEN_METRICS_URL=http://localhost:8088`.

## Jak uruchomić (stan bieżący)
```powershell
# z katalogu narzędzia (acc-ai-hackathon → docelowo shop-qa-ui)
.\.venv\Scripts\Activate.ps1            # lub użyj .venv bezpośrednio
streamlit run app.py
# w sidebarze: wskaż serwis sklepu (np. ../ai-bot-playground/shop-notification) i Indeksuj
```
**Provider LLM** (`src/agent.py`, kolejność): **OpenRouter** (OpenAI-compatible) gdy ustawiony
`OPENROUTER_API_KEY` → Azure Anthropic (`AZURE_ANTHROPIC_API_KEY`) → tryb demo/mock.
Model na OpenRouter ustawiasz w `.env`: `OPENROUTER_MODEL` (obecnie **`z-ai/glm-5.2`**).

**Thinking / kontekst (najlepsze wyniki):** `z-ai/glm-5.2` ma kontekst **1M** tokenów (prompty
są małe — nie limitujemy). Rozumowanie sterowane unified-paramem OpenRoutera `reasoning`:
`OPENROUTER_REASONING_EFFORT=high` (max thinking; opcje high|medium|low|off lub jawny
`OPENROUTER_REASONING_MAX_TOKENS`) oraz budżet wyjścia `OPENROUTER_MAX_TOKENS=32000`
(cap providera 32768). Treść `<think>` jest czyszczona z odpowiedzi (`_strip_think`).

## Warunki działania bramki (przy Etapach 3–5)
Patrz `ai-bot-playground/shop-infra/LOCAL-START.md` — podman → kind → self-hosted runner
muszą żyć, by PR do `main` przeszedł przez `preprod-gate / gate`.
