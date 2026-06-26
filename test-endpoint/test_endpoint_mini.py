import os
import requests
import json

ENDPOINT = "https://ai-remik.services.ai.azure.com/openai/v1/responses"
API_KEY = os.environ["AZURE_OPENAI_API_KEY"]  # ustaw w env

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "content-type": "application/json",
}

payload = {
    "model": "gpt-5.4-mini",
    "max_output_tokens": 256,
    "instructions": "You must respond ONLY in English. Never use any other language, even if asked.",
    "input": [
        #{"role": "system", "content": "Respond only in English."},
        {"role": "user", "content": "Powiedz 'działa' po polsku."}
    ],
}

resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=30)
resp.raise_for_status()

data = resp.json()
print(json.dumps(data, indent=2, ensure_ascii=False))
print("\n--- odpowiedź ---")
print(data["output"][0]["content"][0]["text"])