#!/usr/bin/env python3
"""check_endpoints.py — diagnostyka łączności z modelami Azure AI Foundry.

Sprawdza endpoint(y) używane przez aplikację, czytając te same zmienne env co
kod (src/agent.py:_llm_azure) i kontrakt z .env.docker:

  - MOCNY (AKTYWNY, analiza/Q&A): {AZURE_AI_ENDPOINT}/v1/messages
        model = AZURE_AI_DEPLOYMENT (np. claude-opus-4-8), auth: Bearer AZURE_AI_API_KEY
  - MAŁY (placeholder, kod jeszcze nie używa): {AZURE_OPENAI_ENDPOINT}/v1/responses
        model = AZURE_AI_DEPLOYMENT_FAST (np. gpt-5.4-mini), auth: Bearer AZURE_OPENAI_API_KEY
        — testowany TYLKO gdy AZURE_OPENAI_ENDPOINT jest ustawiony.

Uruchom WEWNĄTRZ kontenera (te same klucze/sieć co aplikacja):
  podman exec --env PYTHONUTF8=1 <kontener> python scripts/check_endpoints.py
albo, gdy repo nie jest zamontowane:
  podman cp scripts/check_endpoints.py <kontener>:/tmp/c.py && podman exec <kontener> python /tmp/c.py

Exit code: 0 = aktywny model OK, 1 = błąd.
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
    print(f"\n[MOCNY/aktywny] {deployment}  →  {endpoint}/v1/messages")
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


def check_gpt() -> bool | None:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.environ.get("AZURE_AI_DEPLOYMENT_FAST", "gpt-5.4-mini")
    if not endpoint:
        print(f"\n[MAŁY/placeholder] {deployment} — POMINIĘTO "
              "(AZURE_OPENAI_ENDPOINT nieustawiony; model jeszcze niewpięty w kod)")
        return None
    key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("AZURE_AI_API_KEY", "")
    print(f"\n[MAŁY/placeholder] {deployment}  →  {endpoint}/v1/responses")
    print(f"      klucz: {_mask(key)}")
    status, body = _post(
        endpoint.rstrip("/") + "/v1/responses",
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        {"model": deployment, "max_output_tokens": 16,
         "input": [{"role": "user", "content": PING}]},
    )
    print(f"      HTTP {status}")
    if status == 200:
        try:
            print(f"      ✅ odpowiedź: {json.loads(body)['output'][0]['content'][0]['text'].strip()!r}")
            return True
        except (KeyError, IndexError, ValueError):
            print(f"      ⚠️  200, nieoczekiwany kształt: {body[:300]}")
            return False
    print(f"      ⛔ treść: {body[:400]}")
    return False


def main() -> int:
    print("=== Diagnostyka endpointów LLM (Azure AI Foundry) ===")
    print(f"LLM_PROVIDER = {os.environ.get('LLM_PROVIDER', '(brak)')}")
    opus_ok = check_opus()
    gpt = check_gpt()
    print("\n=== Wynik ===")
    print(f"  MOCNY (aktywny): {'✅ OK' if opus_ok else '⛔ FAIL'}")
    print(f"  MAŁY (placeholder): {'✅ OK' if gpt else ('— pominięty' if gpt is None else '⛔ FAIL')}")
    return 0 if opus_ok else 1


if __name__ == "__main__":
    sys.exit(main())
