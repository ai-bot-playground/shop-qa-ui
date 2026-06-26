import os
import requests
import json

ENDPOINT = "https://ai-remik.services.ai.azure.com/anthropic/v1/messages"
API_KEY = os.environ["AZURE_ANTHROPIC_API_KEY"]  # ustaw w env

headers = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

payload = {
    "model": "claude-opus-4-8",  # nazwa modelu jak skonfigurowana w deploymencie
    "max_tokens": 256,
    "system": "Udzielaj odpowiedzi wyłącznie po angielsku.",
    "messages": [
        {"role": "user", "content": "Powiedz 'działa' po polsku."}
    ],
}

resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=30)
resp.raise_for_status()

data = resp.json()
print(json.dumps(data, indent=2, ensure_ascii=False))
print("\n--- odpowiedź ---")
print(data["content"][0]["text"])