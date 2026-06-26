import re

JIRA_PLANS: dict[str, dict] = {
    "cancel_order": {
        "title": "Naprawa logiki anulowania zamówień",
        "summary": "Funkcja cancel_order cicho zwraca False gdy zamówienie jest wysłane, zamiast rzucić wyjątek lub zwrócić czytelny komunikat błędu.",
        "steps": [
            "Zapoznaj się z obecnym zachowaniem `cancel_order` (`legacy_billing/billing.py:11`)",
            "Ustal z biznesem oczekiwane zachowanie: wyjątek, kod błędu, czy log?",
            "Wprowadź zmianę w zakładce Piaskownica i uruchom testy automatyczne",
            "Zaakceptuj lub odrzuć wyniki testów (human-in-the-loop)",
            "Zatwierdź zmiany przez commit z opisem",
            "Przekaż do code review i QA",
        ],
        "estimation": {"dev": "1–2 dni", "test": "0,5 dnia", "total": "2–3 dni"},
        "affected_files": [
            {"path": "legacy_billing/billing.py", "line": 11, "symbol": "cancel_order"},
        ],
        "commit_suggestion": "fix: rzuć wyjątek przy próbie anulowania wysłanego zamówienia",
        "risk": "Średni",
        "priority": "High",
    },
    "calc_lf": {
        "title": "Weryfikacja i aktualizacja stawek opłat za opóźnienie",
        "summary": "Stawki 1,5% i 2,5% mogą być nieaktualne. Funkcja calc_lf nie waliduje danych wejściowych (ujemne kwoty, brak limitu maksymalnego).",
        "steps": [
            "Sprawdź aktualne stawki z działem finansowym",
            "Zapoznaj się z logiką `calc_lf` (`legacy_billing/billing.py:3`)",
            "Zaktualizuj stawki lub dodaj brakującą walidację w Piaskownicy",
            "Uruchom testy i upewnij się że wyniki zgadzają się z działem finansowym",
            "Zacommituj zmiany z referencją do dokumentu zatwierdzającego stawki",
        ],
        "estimation": {"dev": "0,5 dnia", "test": "1 dzień", "total": "1–2 dni"},
        "affected_files": [
            {"path": "legacy_billing/billing.py", "line": 3, "symbol": "calc_lf"},
        ],
        "commit_suggestion": "fix: zaktualizuj stawki opłat za opóźnienie wg nowego cennika",
        "risk": "Wysoki",
        "priority": "Critical",
    },
}

_KEYWORDS: dict[str, list[str]] = {
    "cancel_order": [
        "anulowanie", "anulowani", "zamowien", "zamówien", "cancel", "order",
        "cicho", "silent", "wyslan", "wysłan", "shipped", "wyjątek",
    ],
    "calc_lf": [
        "oplat", "opłat", "opoznien", "opóźnien", "stawka", "fee", "late",
        "obliczan", "oblicz", "faktur", "procent", "odsetk", "billing",
    ],
}

_GENERIC_PLAN = {
    "title": "Analiza wymagań — brak dopasowania w kodzie",
    "summary": "Nie znaleziono funkcji bezpośrednio powiązanej z opisem zadania. Wymagana ręczna analiza.",
    "steps": [
        "Zaindeksuj repozytorium w zakładce Q&A",
        "Zadaj pytanie w języku naturalnym aby znaleźć powiązany kod",
        "Wróć do Jira Task i sprecyzuj opis zadania",
    ],
    "estimation": {"dev": "?", "test": "?", "total": "Do ustalenia"},
    "affected_files": [],
    "commit_suggestion": "",
    "risk": "Nieznane",
    "priority": "Medium",
}


def generate_plan(task_text: str) -> dict:
    text = task_text.lower()
    for symbol, keywords in _KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return {"symbol": symbol, **JIRA_PLANS[symbol]}
    return {"symbol": None, **_GENERIC_PLAN}
