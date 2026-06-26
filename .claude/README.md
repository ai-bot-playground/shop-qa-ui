# Konfiguracja Claude Code (`.claude/`)

Ten katalog opisuje repozytorium **dla modelu Anthropic (Claude Code)** i konfiguruje jego
zachowanie w projekcie. Pliki są wersjonowane (poza osobistym `settings.local.json`).

## Zawartość

| Ścieżka | Rola |
| --- | --- |
| [CLAUDE.md](CLAUDE.md) | **Główny opis projektu dla Claude** — auto-ładowany do kontekstu na starcie. Mapa kodu, sposób uruchomienia, zasady. |
| [skills/](skills/) | **Skille** (Agent Skills) — instrukcje uruchamiane na żądanie (lub auto, gdy pasują). Każdy w `skills/<nazwa>/SKILL.md`. |
| [agents/](agents/) | **Subagenci** wyspecjalizowani w podsystemach repo. Każdy w `agents/<nazwa>.md`. |
| [hooks/check_py.py](hooks/check_py.py) | Skrypt wywoływany przez hook `PostToolUse` — kontrola składni `.py` po edycji. |
| [settings.json](settings.json) | Ustawienia **współdzielone**: uprawnienia (`permissions`) + hooki (`hooks`). |
| `settings.local.json` | Ustawienia **osobiste** (nie commitować — w `.gitignore`). |

## CLAUDE.md — opis dla modelu

Claude Code auto-ładuje `CLAUDE.md` zarówno z korzenia repo (`./CLAUDE.md`), jak i z
`./.claude/CLAUDE.md` (oba działają równoważnie). Trzymamy go tutaj, w `.claude/`.
Zasady dobrego CLAUDE.md: zwięźle (≈ < 200 linii), konkretnie (mapa kodu, komendy, zasady,
pułapki). Duże treści można dołączać przez `@ścieżka` (import) — my zamiast tego linkujemy do
[README.md](../README.md), żeby nie rozdmuchiwać kontekstu.

## Skille

Wbudowane w tym repo:

- **`/run-demo`** — uruchamia aplikację lokalnie w trybie demo (mock) na `:8501`.
- **`/sandbox-check`** — odtwarza testy silnika CI lokalnie (`scripts/ci_*.py`).

Każdy skill to `skills/<nazwa>/SKILL.md` z frontmatterem YAML (`name`, `description`,
opcjonalnie `allowed-tools`, `model`, `arguments`, `paths`, …). Treść po `---` to instrukcje
dla Claude. Można dołączać dynamiczny kontekst przez `` !`komenda` `` oraz pliki pomocnicze
w `skills/<nazwa>/scripts/`.

> Slash-commands w `.claude/commands/<nazwa>.md` działają tak samo — skille to nowsze, zalecane podejście.

## Hooki

Hooki uruchamiają polecenia na zdarzenia cyklu życia. **Zalecany hook (do dodania ręcznie do
[settings.json](settings.json)** — agent nie może modyfikować tego pliku z powodu zabezpieczenia):

- **`PostToolUse` / `Edit|Write` → `python .claude/hooks/check_py.py`**
  Po każdej edycji pliku sprawdza składnię Pythona (pliki nie-`.py` są pomijane). Błąd składni
  trafia jako informacja do Claude (nie blokuje — edycja już się wykonała). Wymaga `python` na PATH.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python .claude/hooks/check_py.py" }
        ]
      }
    ]
  }
}
```

Przykład rozszerzenia (ostrzeżenie przed `git push`), do dodania w `settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "if": "Bash(git push:*)",
        "hooks": [
          { "type": "command", "command": "echo '[hook] Push uruchomi pipeline CI (ai-sandbox/**).' 1>&2" }
        ]
      }
    ]
  }
}
```

Inne zdarzenia: `SessionStart`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, …
Kody wyjścia: `0` = ok, `2` = blokada (stderr → powód). Edycję `settings.json` najwygodniej
robić skillem `/update-config`.

## Subagenci

Wyspecjalizowani subagenci w [agents/](agents/) — każdy zna konwencje i pułapki swojego
podsystemu, ma zawężony zestaw narzędzi i jest auto-delegowany na podstawie pola `description`:

| Agent | Specjalizacja | Narzędzia |
| --- | --- | --- |
| [legacy-code-explainer](agents/legacy-code-explainer.md) | Wyjaśnianie i trasowanie kodu (`src/*`, `sample/*`) — tylko odczyt | Read, Grep, Glob |
| [llm-integration-expert](agents/llm-integration-expert.md) | Integracja LLM w `src/agent.py`, prompty, tryb demo | Read, Grep, Glob, Edit, Bash |
| [sandbox-engineer](agents/sandbox-engineer.md) | Piaskownica/testy (`src/sandbox.py`), silnik CI (`scripts/ci_*.py`) | Read, Grep, Glob, Edit, Bash |
| [streamlit-ui-dev](agents/streamlit-ui-dev.md) | UI Streamlit (`app.py`), workflow, szablony odpowiedzi | Read, Grep, Glob, Edit, Bash |
| [infra-ci-engineer](agents/infra-ci-engineer.md) | Containerfile, compose, GitHub Actions, k8s | Read, Grep, Glob, Edit, Bash |

Format: `.claude/agents/<nazwa>.md` z frontmatterem (`name`, `description`, `tools`, `model`,
opcjonalnie `disallowedTools`, `permissionMode`, …). Wbudowane agenty (`Explore`, `Plan`,
`general-purpose`) pozostają dostępne.

## Uprawnienia (`permissions`)

Opcjonalnie możesz dodać do [settings.json](settings.json) allowlistę bezpiecznych, częstych
poleceń (read-only git, `py_compile`, skrypty CI), aby ograniczyć liczbę pytań o zgodę. Składnia:
`"Bash(git status:*)"`, `"Read(src/**)"`, `"Bash(git push:*)"` w `deny`/`ask` itd.
Pierwszeństwo: `deny` → `ask` → `allow`. (Tych reguł celowo **nie** dodano automatycznie.)

## Źródła

- CLAUDE.md / pamięć: <https://code.claude.com/docs/en/memory>
- Skille: <https://code.claude.com/docs/en/skills>
- Hooki: <https://code.claude.com/docs/en/hooks>
- Subagenci: <https://code.claude.com/docs/en/sub-agents>
- Uprawnienia: <https://code.claude.com/docs/en/permissions>
