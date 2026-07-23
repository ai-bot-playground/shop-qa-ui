#!/usr/bin/env python3
"""check_endpoints.py — diagnostyka łączności z modelem LLM (OpenRouter).

Sprawdza DOKŁADNIE tę samą ścieżkę LLM, której używa aplikacja (src/agent.py):
  OpenRouter chat/completions, model = OPENROUTER_MODEL,
  auth: Bearer OPENROUTER_API_KEY.

Uruchom lokalnie (host) lub w kontenerze — czyta te same zmienne env co aplikacja:
  python scripts/check_endpoints.py

Exit code: 0 = OK, 1 = błąd.
"""
import json
import os
import sys
import urllib.error
import urllib.request

try:
    from dotenv import load_dotenv

    # .env leży w katalogu shop-qa-ui (rodzic katalogu scripts/).
    _here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_here, "..", ".env"))
except Exception:
    pass  # dotenv opcjonalny — env może już być ustawiony w powłoce/kontenerze

ENDPOINT = os.environ.get(
    "OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions"
)
MODEL = os.environ.get("OPENROUTER_MODEL", "z-ai/glm-5.2")
KEY = os.environ.get("OPENROUTER_API_KEY", "")
PING = "Odpowiedz jednym słowem: pong"
TIMEOUT = 60


def _mask(key: str) -> str:
    return f"...{key[-4:]} (len {len(key)})" if key else "(BRAK)"


def check_openrouter() -> bool:
    print(f"\n[OpenRouter] {MODEL}  →  {ENDPOINT}")
    print(f"      klucz OPENROUTER_API_KEY: {_mask(KEY)}")
    if not KEY:
        print("      ⛔ POMINIĘTO — brak OPENROUTER_API_KEY")
        return False

    payload = {
        "model": MODEL,
        "max_tokens": 64,
        # Ping bez rozumowania — inaczej przy effort=high cały krótki budżet
        # zjadają tokeny reasoningu i `content` wraca pusty (HTTP 200, ale bez treści).
        "reasoning": {"enabled": False},
        "messages": [{"role": "user", "content": PING}],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, body = r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"      ⛔ {type(e).__name__}: {e}")
        return False

    print(f"      HTTP {status}")
    if status == 200:
        try:
            data = json.loads(body)
            txt = (data["choices"][0]["message"].get("content") or "").strip()
            print(f"      ✅ odpowiedź: {txt!r}")
            if data.get("usage"):
                print(f"      usage: {data['usage']}")
            return True
        except (KeyError, IndexError, ValueError):
            print(f"      ⚠️  200, nieoczekiwany kształt: {body[:300]}")
            return False
    print(f"      ⛔ treść: {body[:400]}")
    return False


def main() -> int:
    print("=== Diagnostyka endpointu LLM (OpenRouter) ===")
    ok = check_openrouter()
    print("\n=== Wynik ===")
    print(f"  OpenRouter: {'✅ OK' if ok else '⛔ FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
