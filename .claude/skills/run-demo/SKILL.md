---
name: run-demo
description: Uruchom aplikację Streamlit lokalnie w trybie demo (mock, bez klucza API) na porcie 8501 do ręcznego przeklikania. Użyj, gdy ktoś prosi o uruchomienie, podgląd lub przetestowanie aplikacji.
allowed-tools: Bash
---

Uruchom aplikację lokalnie w **trybie demonstracyjnym** (mockowane odpowiedzi LLM — nie wymaga klucza API).

## Kroki

1. Jeśli brak katalogu `.venv`, utwórz środowisko i zainstaluj zależności:
   - `python -m venv .venv`
   - `.venv/Scripts/python.exe -m pip install -r requirements.txt`
2. Uruchom serwer w tle, **wymuszając tryb demo** (puste zmienne są obecne w środowisku, więc
   `load_dotenv(override=False)` nie nadpisze ich kluczem z `.env`):
   ```bash
   AZURE_ANTHROPIC_API_KEY= ANTHROPIC_API_KEY= .venv/Scripts/python.exe -m streamlit run app.py \
     --server.headless true --server.port 8501 --browser.gatherUsageStats false > streamlit.log 2>&1
   ```
3. Poczekaj aż `http://127.0.0.1:8501/_stcore/health` zwróci `200`, po czym podaj użytkownikowi
   adres **http://localhost:8501**.
4. Aby uruchomić z **realnym modelem**, pomiń puste zmienne — klucz zostanie wczytany z `.env`.

## Uwagi

- Windows: interpreter venv to `.venv/Scripts/python.exe` (na Linux/Mac: `.venv/bin/python`).
- Serwer działa w tle (`streamlit.log`) — zatrzymaj go, gdy nie jest już potrzebny.
- ⚠️ Przycisk „Zatwierdź i zacommituj" w kroku Piaskownica wykonuje **realny** `git commit` —
  ostrzeż użytkownika przed klikaniem do końca, jeśli nie chce trwałych zmian.
