# shop-qa-ui

Aplikacja Streamlit — część systemu **ai-bot-playground**. Product Owner opisuje zmianę w języku naturalnym → agent analizuje kod serwisów sklepu, planuje i generuje zmianę → lokalnie kompiluje ją i poprawia na podstawie błędów → **wdraża ją na środowisko testowe na Kubernetes i daje PO link** → dopiero gdy PO potwierdzi, że działa, wystawia **Pull Request do repozytorium serwisu** (bramka `preprod-gate` wykonuje pełną walidację na preprod) → merge z UI.

Link z gotową prośbą: `http://localhost:8502/?q=<treść zmiany>` wypełnia pole pytania w kroku Analyze.

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
| `OPENROUTER_REASONING_EFFORT` | `high` | Thinking (`high`/`medium`/`low`/`off`). Tanie wywołania pomocnicze (ekspansja zapytania) wyłączają thinking; modele z obowiązkowym rozumowaniem (np. `openai/gpt-6.1-sol`) odrzucają to błędem 400 — wtedy idą na `low` |
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
| **3 — Piaskownica** | Planner dostaje trafne fragmenty realnego kodu; LLM generuje pliki — każdy z rolą z planu, listą pozostałych plików zmiany i treścią już wygenerowanych (np. klasa kroków widzi nowy `.feature`); obowiązkowa walidacja w izolowanym worktree; błąd wraca do LLM do poprawy |
| **4 — Test PO** | Po zielonej walidacji „🧪 Wdróż na środowisko testowe": obrazy zmienionych serwisów budowane z worktree ze zmianą, `kind load`, pełny stos z chartu `shop-infra/helm` na **osobnym namespace** `test-<id>` klastra `kind-preprod` (bez Prometheusa/Grafany; reszta serwisów z obrazów bazowych `main`). PO dostaje linki (`http://localhost:<port>` — port-forward do UI i gatewaya, prowadzony przez aplikację) oraz instrukcję „co kliknąć i czego się spodziewać" od modelu. „✅ Działa" → PR z adnotacją o sprawdzeniu; „❌ Nie działa" + opis → uwagi wracają do Piaskownicy („🛠 Popraw zmianę według uwag PO"), potem walidacja i wdrożenie od nowa. Jedno środowisko na raz; znika po merge'u lub przyciskiem 🗑. Moduł: [`src/testenv.py`](src/testenv.py) |
| **5 — PR** | PR powstaje dopiero po akceptacji PO (wyjątek: zmiana bez wdrażanego serwisu, np. same testy — wtedy PR od razu); następnie live status bramki `preprod-gate` co 15 s, podgląd na preprod i **merge z UI** (per repo, za potwierdzeniem człowieka). Anulowany check to porażka. Repo bez żadnej bramki (`main` nie wymaga checków, a po 90 s nic nie wystartowało — np. `shop-acceptance-tests`) dostaje stan „bez bramki": ostrzeżenie i merge za potwierdzeniem. Przy czerwonej bramce UI pokazuje fragment logu kończący się na pierwszym `##[error]` (także dla reusable workflow, gdzie `gh run view --log-failed` milczy). Gdy wszystkie PR-y osiągną stan końcowy, auto-odświeżanie się wyłącza |

### Lokalna bramka przed PR

- Gradle: `classes testClasses --offline --no-daemon` — kompiluje kod i testy, ale nie uruchamia Testcontainers ani usług.
- Suite'y Cucumber bez Springa i Testcontainers (`shop-acceptance-tests`) dostają dodatkowo **dry-run** (`test` z init-scriptem ustawiającym `cucumber.execution.dry-run`): kroki są dopasowywane do glue bez wykonywania, więc `.feature` z niezaimplementowanym krokiem nie przejdzie. To repo nie ma własnej bramki na PR, a po merge'u taki plik wywracałby akceptację w bramce każdego serwisu.
- React/Vite: `npm ci --offline`, następnie `npm run build`.
- Pozostałe repozytoria: walidacja składni JSON/YAML/Python i `git diff --check`.
- Błędy kompilacji trafiają do kroku naprawczego LLM. Braki JDK, Node lub pakietów w cache są oznaczane jako problemy środowiska i nie są wysyłane do LLM jako błędy kodu.
- Walidacja idzie na worktree z lokalnego `HEAD`, a gałąź PR-a wychodzi z `origin/main`. Ponieważ PR niesie **pełną treść pliku**, `open_pr_for_files` porównuje `base_content` (treść, na której powstała zmiana) z tym, co stoi w `origin/main`, i przy rozjeździe **odmawia** — inaczej cicho cofnąłby zmianę, która trafiła do `main` w międzyczasie (typowo po merge'u poprzedniego PR-a z tego samego UI). Lekarstwo: `git pull` w klonie, ponowne zaindeksowanie i wygenerowanie zmiany na aktualnym kodzie.

Pełny workflow uruchamiaj lokalnie z JDK 25, Node/npm i lokalnymi klonami `shop-*`. Przed pierwszą walidacją `shop-ui` wykonaj w nim `npm ci`, aby zapełnić cache używany później w trybie offline.

### Ograniczenia wariantu kontenerowego / k8s

`Containerfile` nie zawiera JDK, Node, `gh`, podmana/kind/helm ani repozytoriów siostrzanych, a ConfigMap nie ustawia `SHOP_REPOS_DIR` — pod na `:8501` obsługuje więc **wyłącznie indeksowanie i analizę**. Lokalna walidacja, środowisko testowe dla PO i wystawianie PR-ów działają tylko w wariancie natywnym (`run-local.ps1`, port `8502`) — na tej samej maszynie co klaster `kind-preprod`.

### Gradle: „Unable to establish loopback connection"

Komunikat myli — **nie chodzi o TCP loopback**. `Selector.open()` (którego Gradle potrzebuje do komunikacji z daemonem) tworzy pipe budzący na **gniazdie AF_UNIX** w `java.io.tmpdir`, a na zablokowanych korporacyjnie Windowsach `connect` na takim gnieździe w `%LOCALAPPDATA%\Temp` zwraca `SocketException: Invalid argument`. Zwykły zapis pliku i `bind` w tym katalogu działają — pada dopiero `connect`, i tylko w tym drzewie katalogów. To ta sama klasa problemu, którą obchodzi już [`_clone_base()`](src/sandbox.py) dla worktree gita.

Obejście — jedna zmienna środowiskowa użytkownika, obejmuje każdy proces Javy (launcher Gradle'a, daemon, Testcontainers, Netty):

```bash
setx JDK_JAVA_OPTIONS "-Djdk.net.unixdomain.tmpdir=C:\Windows\Temp"
```

Sam `org.gradle.jvmargs` nie wystarcza — naprawia daemona, ale launcher ginie wtedy z `The first result from the daemon was empty`.

Szybkie sprawdzenie, czy obejście działa — **uruchom `gradlew`, nie `jshell`**:

```bash
cd ../shop-catalog && ./gradlew.bat --offline --no-daemon classes testClasses
```

`jshell` **nie czyta** `JDK_JAVA_OPTIONS` (robi to wyłącznie launcher `java`), więc test
przez `jshell` pokazuje `FAIL` nawet wtedy, gdy obejście jest aktywne i Gradle buduje się
poprawnie. Jeśli chcesz sprawdzić sam `Selector.open()`, uruchom to launcherem `java`
(tryb jednoplikowy — on JDK_JAVA_OPTIONS czyta):

```bash
printf 'void main() { try (var s = java.nio.channels.Selector.open()) { System.out.println("OK"); } catch (Exception e) { System.out.println("FAIL: " + e); } }' > Sel.java && java Sel.java
```

Niezależnie od obejścia aplikacja klasyfikuje taki log jako awarię **środowiska**, nie kodu, i nie wysyła go do LLM.

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
tests/
  scenarios.py      — katalog scenariuszy zmian S1–S5 (realny, kompilowalny kod)
  scripted_llm.py   — „model" podstawiany pod agent._call na czas scenariusza
  test_change_scenarios.py — scenariusze end-to-end przez app.py i prawdziwe buildy
  (pozostałe)       — planowanie, naprawa, lokalna bramka, PR, tryb offline, UI (AppTest)
manifest.yaml       — lista serwisów shop-* do indeksowania
deploy/k8s/         — manifesty Kubernetes (namespace `shop`)
```

---

## Testy

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Testy UI korzystają ze `streamlit.testing.v1.AppTest` — uruchamiają prawdziwe `app.py`, bez przeglądarki, klucza i sieci. Trzy warstwy:

| Warstwa | Pliki | Co sprawdza |
|---|---|---|
| Jednostkowa | `test_agent_flow.py`, `test_local_validation.py`, `test_pull_request.py` | prompty naprawcze, klasyfikacja awarii bramki, ochrona przed nadpisaniem `origin/main` |
| Przepływ UI | `test_app_flow.py`, `test_fake_llm_flow.py`, `test_user_journey.py` | krok 3 zawsze daje wyjście, gating merge'a, pełna droga: indeksowanie → pytanie → akceptacja → Piaskownica |
| Scenariusze zmian | `test_change_scenarios.py` (+ `scenarios.py`, `scripted_llm.py`) | **prawdziwe buildy** zmienionych serwisów |

### Scenariusze zmian (`-m scenario`)

Podstawiony jest wyłącznie `agent._call` — reszta to produkcyjna ścieżka aplikacji: plan → generacja → diff → worktree → `gradlew`/`npm` → gating PR-a. Zamiast atrapy dopisującej komentarz, „model" oddaje **realny, kompilowalny kod**, więc bramka faktycznie coś weryfikuje.

| ID | Zasięg | Co wnosi |
|---|---|---|
| S1 | `shop-catalog`, 1 plik | najkrótsza ścieżka; PR zablokowany do czasu zielonej bramki |
| S2 | `shop-catalog`, 3 pliki | nowy plik (migracja Flyway `V2`), spójność pola w encji i DTO, jeden PR na repo |
| S3 | `shop-catalog` + `shop-ui` | dwa języki: Gradle **i** npm muszą być zielone; czerwony frontend blokuje PR obu repo |
| S4 | `shop-order`, `shop-notification`, `shop-ui`, `shop-acceptance-tests` — 10 plików | zmiana przez wszystkie warstwy (dane → saga → zdarzenie → UI → testy akceptacyjne), jeden PR na repo |
| S5 | `shop-catalog`, kod niekompilowalny | bramka odrzuca, błąd klasyfikowany jako `code`, pętla naprawcza dostaje prawdziwy log `javac` i doprowadza do zielonego |

Scenariusze **realnie budują** serwisy, więc trwają kilka minut i wymagają lokalnych klonów `shop-*`, JDK 25 i Node. Bez nich (np. na runnerze GitHuba) po prostu się pomijają. PR-y nigdy nie lecą naprawdę — `open_pr_for_files` jest podmieniony i sprawdzane jest tylko, **z czym** aplikacja by go wystawiła.

Sam szybki zestaw (bez buildów, ~15 s):

```bash
python -m pytest -m "not scenario"
```

Przed pierwszym uruchomieniem scenariuszy zapełnij cache offline — inaczej bramka zgłosi problem **środowiska**, nie kodu:

```bash
for r in shop-catalog shop-gateway shop-inventory shop-order shop-payment shop-notification shop-acceptance-tests; do (cd ../$r && ./gradlew.bat --no-daemon classes testClasses); done
```

---

## CI

[`pr-check.yml`](.github/workflows/pr-check.yml): `pytest` (na atrapie offline) + build obrazu + smoke test Streamlit (GitHub-hosted runner).
