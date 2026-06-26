import copy

ANSWER_TYPES = {
    "business": {
        "label": "💼 Biznesowy",
        "default_fields": [
            {"key": "summary",      "label": "Podsumowanie",    "visible": True},
            {"key": "feasibility",  "label": "Wykonalność",      "visible": True},
            {"key": "test_plan",    "label": "Plan testów",      "visible": True},
            {"key": "time_metrics", "label": "Czas realizacji",  "visible": True},
            {"key": "impact",       "label": "Impact",           "visible": True},
            {"key": "risk",         "label": "Ryzyko",           "visible": True},
            {"key": "dependencies", "label": "Zależności",       "visible": True},
        ],
    },
    "technical": {
        "label": "🔧 Techniczny",
        "default_fields": [
            {"key": "answer_text",  "label": "Treść odpowiedzi", "visible": True},
            {"key": "file_path",    "label": "Ścieżka i linia",  "visible": True},
            {"key": "source_code",  "label": "Kod źródłowy",     "visible": True},
        ],
    },
}


def get_default_templates() -> dict:
    return {
        atype: copy.deepcopy(cfg["default_fields"])
        for atype, cfg in ANSWER_TYPES.items()
    }
