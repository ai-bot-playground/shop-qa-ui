#!/usr/bin/env python3
"""check_endpoints.py — diagnostyka łączności z modelem przez Azure AI Foundry.

Sprawdza endpoint używany przez aplikację, czytając te same zmienne env co
diagnostyczna sekcja .env.docker.example:

  - MOCNY (AKTYWNY): {AZURE_AI_ENDPOINT}/v1/messages
        model = AZURE_AI_DEPLOYMENT (np. claude-opus-4-8), auth: Bearer AZURE_AI_API_KEY

Aktywna ścieżka LLM w aplikacji to OpenRouter (OPENROUTER_API_KEY).
Ten skrypt służy do weryfikacji łączności z Azure AI Foundry jako alternatywą.

Uruchom WEWNĄTRZ kontenera (te same klucze/sieć co aplikacja):
  podman exec --env PYTHONUTF8=1 <kontener> python scripts/check_endpoints.py

Exit code: 0 = OK, 1 = błąd.
"""
import json
import os
import sys
import urllib.request

PING = "Odpowiedz jednym słowem: pong"
TIMEOUT = 60


def _mask(key: str) -> str:
    return f"...{key[-4:]} (len {len(key)})" if key else "(BRAK)"


def _post(url: str, headers: dict, payload: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def check_opus() -> bool:
    endpoint = os.environ.get("AZURE_AI_ENDPOINT", "")
    key = os.environ.get("AZURE_AI_API_KEY", "")
    deployment = os.environ.get("AZURE_AI_DEPLOYMENT", "claude-opus-4-8")
    print(f"\n[Azure AI Foundry] {deployment}  →  {endpoint}/v1/messages")
    print(f"      klucz AZURE_AI_API_KEY: {_mask(key)}")
    if not endpoint or not key:
        print("      ⛔ POMINIĘTO — brak AZURE_AI_ENDPOINT lub AZURE_AI_API_KEY")
        return False
    status, body = _post(
        endpoint.rstrip("/") + "/v1/messages",
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
         "anthropic-version": "2023-06-01"},
        {"model": deployment, "max_tokens": 16,
         "messages": [{"role": "user", "content": PING}]},
    )
    print(f"      HTTP {status}")
    if status == 200:
        try:
            print(f"      ✅ odpowiedź: {json.loads(body)['content'][0]['text'].strip()!r}")
            return True
        except (KeyError, IndexError, ValueError):
            print(f"      ⚠️  200, nieoczekiwany kształt: {body[:300]}")
            return False
    print(f"      ⛔ treść: {body[:400]}")
    return False


def main() -> int:
    print("=== Diagnostyka endpointów LLM (Azure AI Foundry) ===")
    ok = check_opus()
    print("\n=== Wynik ===")
    print(f"  Azure AI Foundry: {'✅ OK' if ok else '⛔ FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
