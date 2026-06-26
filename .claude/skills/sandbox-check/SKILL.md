---
name: sandbox-check
description: Uruchom lokalnie własny silnik testów projektu (self-test zasianego buga RED→GREEN + walidacja sample) tak jak pipeline GitHub Actions. Użyj do walidacji zmian w src/sandbox.py, src/agent.py lub sample/ przed pushem.
allowed-tools: Bash
---

Odtwórz lokalnie kroki CI z [.github/workflows/sandbox-pr.yml](../../../.github/workflows/sandbox-pr.yml)
(pomijając budowę obrazu Dockera).

## Kroki

1. **Self-test silnika** (zasiewa regresję, sprawdza RED → GREEN):
   ```bash
   PYTHONUTF8=1 .venv/Scripts/python.exe scripts/ci_sandbox_check.py
   ```
2. **Bramka walidacji sample** (generuje `ci_report.md`):
   ```bash
   PYTHONUTF8=1 .venv/Scripts/python.exe scripts/ci_validate_sample.py
   ```

Podsumuj wynik (pass/fail) i wskaż ewentualne nieprzechodzące testy.

## Uwagi

- `PYTHONUTF8=1` jest wymagane na Windows (konsola cp1250 wywala się na znakach Unicode w raportach).
- Jeśli brak `.venv`, najpierw wykonaj kroki z `/run-demo` (utworzenie venv + instalacja zależności).
