"""Podstawiony „model" zwracający treść scenariusza zamiast wywołania OpenRoutera.

Wpina się w jeden punkt — `agent._call` — czyli dokładnie tam, gdzie kończy się
aplikacja, a zaczyna model. Dzięki temu test przechodzi PRAWDZIWĄ ścieżką
aplikacji (`plan_change` → `generate_*` → `validate_file_changes` → `repair_*`),
tylko z deterministyczną, kompilowalną treścią zamiast losowej odpowiedzi LLM.

Różnica wobec `src/fake_llm.py`: atrapa offline dopisuje komentarz do dowolnego
pliku (sprawdza mechanikę), a ten moduł oddaje konkretny, sensowny kod
scenariusza (sprawdza, że bramka faktycznie kompiluje realną zmianę).
"""

import re

from src import agent, fake_llm
from tests.scenarios import Scenario


class ScriptError(AssertionError):
    """Aplikacja poprosiła o coś, czego scenariusz nie przewiduje."""


def _field(user_content: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}:[ \t]*(.+)$", user_content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _fenced_after(user_content: str, label: str) -> str:
    """Treść bloku ``` … ``` stojącego bezpośrednio po znaczniku `label:`.

    `fake_llm._fenced` bierze PIERWSZY blok w prompcie — w prompcie naprawczym
    pierwszy bywa logiem walidacji, więc tu kotwiczymy się na etykiecie.
    """
    idx = user_content.find(label)
    if idx < 0:
        return ""
    match = re.search(r"```\n(.*?)\n```", user_content[idx:], re.DOTALL)
    return match.group(1) if match else ""


class ScriptedLLM:
    """Callable zgodny z sygnaturą `agent._call`.

    Zlicza wywołania per rodzaj i zapamiętuje prompty — testy sprawdzają dzięki
    temu nie tylko wynik, ale i to, CO aplikacja wysłała do modelu (np. czy
    prompt naprawczy zawiera prawdziwy log kompilatora).
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.calls: list[tuple[str, str]] = []          # (kind, user_content)
        self.repaired: set[tuple[str, str]] = set()     # (repo, path)

    # ── routing ──────────────────────────────────────────────────────────────
    def __call__(self, system: str, user_content: str,
                 max_tokens: int = 1024, light: bool = False) -> str:
        kind = agent._FAKE_KINDS.get(system, "")
        if not kind and system == agent._REPAIR_FILE_SYSTEM:
            kind = "repair"
        self.calls.append((kind, user_content))

        handler = {
            "plan": self._plan,
            "filechange": self._filechange,
            "newfile": self._newfile,
            "repair": self._repair,
        }.get(kind)
        if handler:
            return handler(user_content)
        # Analiza/ekspansja/recenzja nie niosą kodu — wystarczy atrapa offline.
        return fake_llm.respond(kind, user_content)

    def kinds(self) -> list[str]:
        return [k for k, _ in self.calls]

    def prompts(self, kind: str) -> list[str]:
        return [c for k, c in self.calls if k == kind]

    # ── poszczególne rodzaje ────────────────────────────────────────────────
    def _plan(self, _user_content: str) -> str:
        import json
        return json.dumps(self.scenario.plan_json(), ensure_ascii=False)

    def _find(self, path: str, repo: str = ""):
        matches = [
            f for f in self.scenario.files
            if f.path == path and (not repo or f.repo == repo)
        ]
        if not matches:
            raise ScriptError(f"scenariusz {self.scenario.id} nie zna pliku {repo}/{path}")
        if len(matches) > 1:
            raise ScriptError(f"niejednoznaczny plik {path} w scenariuszu {self.scenario.id}")
        return matches[0]

    def _filechange(self, user_content: str) -> str:
        path = _field(user_content, "PLIK")
        original = _fenced_after(user_content, "PLIK:")
        if not original.strip():
            raise ScriptError(f"prompt dla {path} nie zawiera treści oryginału")
        return self._find(path).build(original)

    def _newfile(self, user_content: str) -> str:
        target = _field(user_content, "NOWY PLIK DO UTWORZENIA")
        repo, _, path = target.partition("/")
        return self._find(path, repo).build("")

    def _repair(self, user_content: str) -> str:
        target = _field(user_content, "PLIK DO OCENY I EWENTUALNEJ NAPRAWY")
        repo, _, path = target.partition("/")
        current = _fenced_after(user_content, "PLIK DO OCENY I EWENTUALNEJ NAPRAWY:")
        fixer = self.scenario.repair.get(path)
        if fixer is None:
            return "BRAK_ZMIAN"       # ten plik nie jest przyczyną błędu
        repaired = fixer(current)
        if repaired == current:
            return "BRAK_ZMIAN"
        self.repaired.add((repo, path))
        return repaired
