import os
import requests
import json

ENDPOINT = os.environ.get("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
MODEL = os.environ.get("OPENROUTER_MODEL", "z-ai/glm-5.2")
API_KEY = os.environ["OPENROUTER_API_KEY"]  # ustaw w env

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "content-type": "application/json",
}

payload = {
    "model": MODEL,
    "max_tokens": 256,
    "messages": [
        {"role": "user", "content": "Powiedz 'działa' po polsku."}
    ],
}

resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=30)
resp.raise_for_status()

data = resp.json()
print(json.dumps(data, indent=2, ensure_ascii=False))
print("\n--- odpowiedź ---")
print(data["choices"][0]["message"]["content"])
