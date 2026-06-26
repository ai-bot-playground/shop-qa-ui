# AI Hackathon — Minimal Preparation Guide

## 1. Kontekst

### 1.1 Co wiemy

- Hackathon jest wewnętrzny.
- Zespół liczy 5 osób.
- Czas pracy: 8 godzin.
- Problem biznesowy poznamy dopiero na starcie.
- Rozwiązanie ma wykorzystywać LLM.
- Prawdopodobnie trzeba będzie pokazać działający prototyp.
- Prezentacja końcowa potrwa około 20 minut.
- Będziemy raczej pracować na danych fikcyjnych lub testowych.
- Zespół ma kompetencje frontend, backend, administracja i DevOps.

### 1.2 Czego nie wiemy

```text
Nie wiemy, jaki będzie problem biznesowy.
Nie wiemy, jakie narzędzia będą wymagane.
Nie wiemy, jakie będą kryteria oceny.
Ale wiemy, że musimy użyć LLM i pokazać wartościowe rozwiązanie w 8 godzin.
```

Nie próbujemy przed hackathonem przewidywać problemu, integracji ani finalnej architektury.

### 1.3 Główna strategia

```text
Problem → analiza → scope → minimalna architektura → prototyp ↔ testy → demo → prezentacja
```

## 2. Przygotowanie przed hackathonem

| Status | Sprawdzenie | Kryterium |
|---|---|---|
| [ ] | Role zespołu | Każda osoba ma główną rolę i rolę zastępczą |
| [ ] | Repo startowe | Repo można sklonować i uruchomić |
| [ ] | `AGENTS.md` | Zawiera zasady pracy agentów i guardrails |
| [ ] | Mini-spec template | Dostępny jest krótki szablon specyfikacji |
| [ ] | Start Prompt | Jest gotowy do użycia po otrzymaniu zadania |
| [ ] | Test uruchomienia | Potwierdzono, że projekt startuje lokalnie |
| [ ] | Szablon prezentacji | Zawiera branding i podstawową strukturę |
| [ ] | Dostępy i środowiska | Konta, uprawnienia i narzędzia są sprawdzone |
| [ ] | Git i rollback | Zespół zna zasady commitów, checkpointów i cofania zmian |
| [ ] | Przygotowanie fake data | Znamy sposób szybkiego utworzenia danych po poznaniu problemu i schematu |

Nie przygotowujemy wcześniej:

- finalnej architektury,
- integracji domenowych,
- agentów domenowych,
- rozbudowanego frameworka agentowego,
- kodu zależnego od nieznanego problemu,
- generatora danych zależnego od nieznanej domeny.

Po zatwierdzeniu MVP przygotowujemy prosty, powtarzalny skrypt generujący fake data zgodne z potrzebnym schematem. Skrypt powinien wspierać seed, liczbę rekordów oraz podstawowe przypadki błędne.

## 3. Plan pracy na 8 godzin

| Czas | Cel |
|---|---|
| 0:00–0:30 | zrozumienie problemu, użytkownika i braków |
| 0:30–1:00 | wybór kierunku, scope i MVP |
| 1:00–1:30 | minimalna architektura, podział pracy i mini-specy |
| 1:30–3:15 | budowa i testowanie prototypu małymi iteracjami |
| 3:15–3:25 | obowiązkowy Sync & Merge Check |
| 3:25–5:00 | integracja, poprawki i dalsza budowa MVP |
| 5:00–6:00 | stabilizacja, testy end-to-end i fallback |
| 6:00–7:15 | prezentacja, demo script i przygotowanie danych |
| 7:15–8:00 | próba generalna i użycie wersji `demo-safe` |

Twarda zasada:

```text
Po 60 minutach musimy wiedzieć, co budujemy i czego nie budujemy.
```


### 3.1 Sync & Merge Check

O 3:15 zespół zatrzymuje pracę na 10 minut.

| Status | Sprawdzenie | Kryterium |
|---|---|---|
| [ ] | Działający rezultat | Każdy pokazuje działający fragment albo konkretny blocker |
| [ ] | Integracja | Sprawdzamy, czy frontend, backend i LLM korzystają ze zgodnych kontraktów |
| [ ] | End-to-end | Uruchamiamy pierwszy możliwy przepływ przez całe rozwiązanie |
| [ ] | Blockery | Krytyczne problemy trafiają do mocnego agenta lub ownera |
| [ ] | Scope | Odcinamy funkcje zagrażające realizacji MVP |
| [ ] | Merge | Ustalamy kolejność integracji i wspólny checkpoint w Git |

```text
No progress reports.
Show working output or identify the blocker.
```

## 4. Zasady użycia AI

```text
LLM analizuje i proponuje.
Kod waliduje i wykonuje.
Człowiek zatwierdza.
```

| LLM | Kod deterministyczny |
|---|---|
| rozumienie niejasnych danych | walidacja |
| klasyfikacja | reguły biznesowe |
| podsumowanie | transformacje danych |
| rekomendacje | integracje i wykonywanie akcji |
| wykrywanie braków | obsługa błędów i fallback |

Human approval jest wymagany dla:

- rozszerzenia scope,
- działań destrukcyjnych,
- nowych zależności,
- nowych agentów lub subagentów,
- istotnych decyzji architektonicznych,
- ryzykownych lub nieodwracalnych działań.

## 5. Model pracy agentów

Ta sekcja jest źródłem prawdy dla `AGENTS.md`, promptów i agentów.

Obowiązkowy flow:

```text
plan → scope approval → change → tests → docs/changelog → diff → review → commit
```

Najważniejsze zasady:

```text
Scope can only become smaller, never larger, without explicit human approval.

Do not solve unspecified problems.
Do not fill specification gaps silently.
Stop and report missing information.
```

### 5.1 Kontrakt zadania

Każde zadanie agenta musi określać:

| Status | Element | Wymaganie |
|---|---|---|
| [ ] | Goal | Jeden konkretny cel |
| [ ] | Input | Dane wejściowe i zależności |
| [ ] | Expected output | Oczekiwany artefakt lub rezultat |
| [ ] | Approved scope | Co agent może zrobić |
| [ ] | Out of scope | Czego agent nie może robić |
| [ ] | Allowed files | Pliki, które może odczytać lub zmienić |
| [ ] | Tests | Sposób weryfikacji |
| [ ] | Definition of Done | Warunki zakończenia |
| [ ] | Stop conditions | Kiedy agent ma się zatrzymać |

### 5.2 Guardrails i delegacja

| Status | Reguła | Oczekiwane zachowanie |
|---|---|---|
| [ ] | Plan | Agent pokazuje plan i listę plików przed zmianą |
| [ ] | Scope | Pracuje wyłącznie w zatwierdzonym zakresie |
| [ ] | Małe zmiany | Zmiana jest lokalna i możliwa do przejrzenia |
| [ ] | Dziedziczenie scope | Subagent nie może otrzymać szerszego scope niż rodzic |
| [ ] | Delegacja | Nowy agent, subagent lub prompt wymaga zgody |
| [ ] | Zależności | Nowa biblioteka wymaga uzasadnienia i zgody |
| [ ] | Ochrona kodu | Agent nie usuwa działającego kodu bez zgody |
| [ ] | Braki w specyfikacji | Agent nie zgaduje; zgłasza brakujące informacje |
| [ ] | Testy | Po zmianie uruchamia właściwe testy |
| [ ] | Dokumentacja | Aktualizuje docs i changelog tylko, gdy zmiana tego wymaga |
| [ ] | Weryfikacja | Pokazuje diff i wynik testów |
| [ ] | Zakończenie | Kończy pracę po spełnieniu Definition of Done |
| [ ] | Wyjście poza scope | Zatrzymuje się i prosi o decyzję |

Domyślne limity:

```text
1 agent = 1 zadanie
maksymalnie 3 zmieniane pliki
maksymalnie 1 nowa zależność po akceptacji
maksymalnie 1 poziom subagentów
brak autonomicznego tworzenia kolejnych promptów i agentów
```

Są to limity domyślne, nie absolutne zakazy. Każdy wyjątek wymaga jawnej zgody człowieka.

### 5.3 Dobór klasy agenta

Stosujemy model mieszany:

```text
Mocny Lead Agent
→ mocni agenci dla krytycznych workstreamów
→ mniejsi agenci dla zamkniętych zadań
→ mocny niezależny reviewer
```

| Typ agenta | Użycie | Ograniczenia |
|---|---|---|
| Mocny Lead Agent | analiza problemu, wybór MVP, podział pracy, kontrola scope | nie rozpoczyna implementacji bez zatwierdzenia MVP |
| Mocny agent | architektura, integracje, debugowanie, ryzyko, zadania krytyczne | nie uzupełnia po cichu braków i nie rozszerza scope |
| Mniejszy agent | boilerplate, formatowanie, proste testy, docs, changelog, małe zmiany | nie podejmuje decyzji architektonicznych |
| Mocny reviewer | zgodność ze specyfikacją, scope, testami i Definition of Done | nie rozszerza rozwiązania podczas review |
| Spec Canary | sprawdzenie kompletności mini-specyfikacji | nie modyfikuje kodu i nie zgaduje |

### 5.4 Spec Canary

Prompt:

```text
Przeanalizuj zadanie wyłącznie na podstawie mini-specyfikacji.
Nie zgaduj i nie uzupełniaj brakujących informacji.
Nie modyfikuj kodu.

Jeśli specyfikacja jest niepełna, zwróć:
- brakujące informacje,
- niejednoznaczności,
- decyzje wymagające zatwierdzenia.
```

Wynik Spec Canary jest sygnałem ostrzegawczym, a nie ostatecznym dowodem. Braki potwierdza mocny agent lub człowiek.

## 6. Lightweight Spec-Driven Development

Pracujemy według flow:

```text
Mini-spec → implementacja → test → review → commit
```

Mini-spec zawiera:

| Status | Element | Co musi być określone |
|---|---|---|
| [ ] | Goal | Co funkcja ma osiągnąć |
| [ ] | Input | Jakie dane przyjmuje |
| [ ] | Expected output | Jaki wynik ma zwrócić |
| [ ] | Edge cases | Jakie przypadki brzegowe obsługuje |
| [ ] | Definition of Done | Kiedy zadanie jest zakończone |

TDD stosujemy tylko tam, gdzie chroni kluczową logikę:

- walidacja structured output,
- logika biznesowa,
- transformacje danych,
- integracje,
- główny demo flow.

## 7. Repo, dokumentacja i quality gates

### 7.1 Minimalna struktura repo

```text
/
  AGENTS.md
  CHANGELOG.md
  README.md
  docs/
    decision-log.md
    mini-spec-template.md
    demo-notes.md
  prompts/
    start-prompt.md
  src/
  tests/
  demo/
  .env.example
```

Znaczenie plików:

| Plik | Cel |
|---|---|
| `AGENTS.md` | zasady z sekcji 5 |
| `CHANGELOG.md` | co istotnego zmieniono |
| `docs/decision-log.md` | dlaczego podjęto kluczowe decyzje |
| `docs/mini-spec-template.md` | wspólny format zadań |
| `docs/demo-notes.md` | demo flow, dane i fallback |
| `prompts/start-prompt.md` | analiza zadania po rozpoczęciu hackathonu |

### 7.2 Hooki i quality gates

Nie wszystkie muszą być fizycznymi Git hookami. Mogą być obowiązkowymi krokami wykonywanymi przez agentów lub CI.

| Hook / gate | Działanie |
|---|---|
| `pre-change` | pokaż cel, scope, plan i pliki |
| `scope-check` | blokuj zmianę wykraczającą poza zatwierdzony scope |
| `delegation-check` | blokuj niezatwierdzone tworzenie promptów i subagentów |
| `agent-routing-check` | sprawdź, czy klasa agenta pasuje do ryzyka zadania |
| `spec-canary-check` | dla ważnego zadania sprawdź kompletność mini-specyfikacji |
| `dependency-check` | wymagaj zgody na nową zależność |
| `destructive-change` | wymagaj zgody na usuwanie, reset lub duży refactor |
| `test-check` | uruchom testy związane ze zmianą |
| `docs-check` | sprawdź potrzebę aktualizacji README lub docs |
| `changelog-check` | dodaj wpis tylko dla istotnej zmiany |
| `post-change` | pokaż diff i wyniki testów |
| `pre-commit` | lint, testy, secret scan i walidacja formatu |
| `commit-message` | użyj prefiksu: `feat`, `fix`, `docs`, `test`, `chore` |

## 8. Prompt przedhackathonowy — przygotowanie repo

```text
Prepare a minimal, technology-neutral repository for a 5-person, 8-hour AI hackathon.

Do not assume the future business problem, domain integrations or final architecture.

Create only:
- AGENTS.md,
- README.md,
- CHANGELOG.md,
- docs/decision-log.md,
- docs/mini-spec-template.md,
- docs/demo-notes.md,
- prompts/start-prompt.md,
- src/,
- tests/,
- demo/,
- .env.example.

Use the following operating rules:
- plan before editing,
- work only within explicit approved scope,
- keep changes small,
- do not add dependencies without approval,
- do not delete working code without approval,
- run tests after every meaningful change,
- check whether docs and changelog require updates,
- show diff before commit,
- stop and report missing information instead of guessing,
- scope may only become smaller without approval,
- subagents inherit the parent scope,
- do not create prompts or subagents autonomously,
- allow at most one delegation level,
- every task must define goal, input, expected output, allowed files,
  tests, Definition of Done and stop conditions,
- use strong agents for critical reasoning, architecture, integrations,
  debugging and review,
- use smaller agents only for closed, low-risk and mechanical tasks,
- provide a spec-canary workflow for validating important mini-specs.

Keep everything minimal.
Do not implement domain-specific features.
```

## 9. Start Prompt

Uruchamiamy go po otrzymaniu zadania.

```text
You are the lead facilitator for a 5-person team in an 8-hour internal AI hackathon.

Analyze the business problem below and prepare the team to choose an MVP.
Do not start implementation.

Rules:
- Do not assume tools, integrations or architecture.
- Separate facts from assumptions.
- If one missing answer can materially change the solution, return only one clarification question.
- Otherwise propose no more than 3 solution directions.
- Recommend the smallest valuable MVP.
- Define what should be done by LLM and what should be deterministic code.
- Define the minimum artifacts required.
- Split the approved direction into small tasks.
- Create mini-specs only for important tasks.
- Generate only the types of specialist prompts that may be needed.
- Do not generate full specialist prompts until the MVP is explicitly approved.
- Scope may only become smaller, never larger, without explicit human approval.
- Do not create subagents unless explicitly approved.
- Allow at most one level of delegation.
- Assign strong agents to critical reasoning, architecture, integrations,
  debugging and review.
- Assign smaller agents only to closed, low-risk and mechanical tasks.
- A weaker agent is never the only control against scope expansion.
- For important tasks, optionally recommend a Spec Canary.
- No agent may silently fill specification gaps.
- Include risks, tests and fallback.
- Be concise.

Business problem:
{{BUSINESS_PROBLEM}}

Team skills:
{{TEAM_SKILLS}}

Known constraints:
{{KNOWN_CONSTRAINTS}}

If clarification is required, return:

{
  "status": "needs_clarification",
  "question": "...",
  "why_it_matters": "..."
}

Otherwise return:

{
  "status": "ready_for_mvp_decision",
  "problem_summary": "...",
  "known_facts": [],
  "assumptions": [],
  "solution_options": [],
  "recommended_mvp": {
    "goal": "...",
    "demo_flow": [],
    "must_have": [],
    "out_of_scope": [],
    "fallback": "..."
  },
  "llm_role": [],
  "deterministic_code_role": [],
  "artifacts_to_create": [],
  "tasks": [],
  "agent_routing": [
    {
      "task": "...",
      "agent_class": "strong | small | reviewer | spec-canary",
      "reason": "...",
      "risk": "low | medium | high"
    }
  ],
  "scope_control": {
    "approved_scope": [],
    "out_of_scope": [],
    "allowed_files": [],
    "delegation_allowed": false,
    "maximum_delegation_level": 1,
    "stop_conditions": []
  },
  "required_specialist_prompt_types": [],
  "main_risks": [],
  "testing_plan": [],
  "first_actions": []
}
```

Po zatwierdzeniu MVP Lead Agent może wygenerować wyłącznie prompty potrzebne do zatwierdzonych zadań. Każdy prompt musi zawierać:

```text
goal
inherited scope
out of scope
allowed files
expected output
tests
Definition of Done
stop conditions
```

## 10. Checklista przed startem implementacji

| Status | Sprawdzenie | Kryterium |
|---|---|---|
| [ ] | Problem | Jest jasno opisany |
| [ ] | Użytkownik | Wiemy, dla kogo budujemy rozwiązanie |
| [ ] | Ból biznesowy | Wiemy, jaki problem rozwiązujemy |
| [ ] | Cel MVP | Jest zapisany w jednym zdaniu |
| [ ] | Demo flow | Jest prosty i możliwy do pokazania |
| [ ] | Must-have | Lista niezbędnych funkcji jest zamknięta |
| [ ] | Out of scope | Wiemy, czego nie budujemy |
| [ ] | Architektura | Jest minimalna i wspiera tylko MVP |
| [ ] | Podział pracy | Każde zadanie ma ownera i kontrakt |
| [ ] | Dobór agentów | Klasa agenta odpowiada ryzyku zadania |
| [ ] | Testy | Jest plan testów dla głównego flow |
| [ ] | Fallback | Wiemy, co pokażemy, jeśli integracja lub LLM zawiedzie |

## 11. Finalna checklista gotowości

| Status | Obszar | Co sprawdzamy |
|---|---|---|
| [ ] | Zespół | Role i odpowiedzialności są jasne |
| [ ] | Repo | Projekt uruchamia się lokalnie |
| [ ] | Agenci | Guardrails są zapisane w `AGENTS.md` |
| [ ] | Spec | Mini-specy istnieją dla kluczowych zadań |
| [ ] | Scope | Nie ma niezatwierdzonych rozszerzeń |
| [ ] | Testy | Główny flow i przypadki błędne są sprawdzone |
| [ ] | Git | Istnieje działający checkpoint lub tag `demo-safe` |
| [ ] | Docs | README, decision log i CHANGELOG są aktualne |
| [ ] | Demo | Demo działa end-to-end |
| [ ] | Fallback | Jest gotowy plan awaryjny |
| [ ] | Prezentacja | Jest demo script i podział mówców |

## 12. Definicja sukcesu

Rozwiązanie ma być:

```text
proste,
działające,
zrozumiałe,
wartościowe biznesowo,
odpowiedzialnie wykorzystujące AI.
```

Nie wygrywa najbardziej rozbudowany system.

Wygrywa rozwiązanie, które jasno rozwiązuje problem i można je wiarygodnie pokazać.
