"""Scenariusze zmian end-to-end — przez PRAWDZIWE `app.py` i PRAWDZIWĄ bramkę.

Te testy nie podmieniają ani kroku planowania, ani walidacji: podstawiony jest
wyłącznie `agent._call` (patrz [`tests/scripted_llm.py`](scripted_llm.py)), czyli
sam model. Wszystko poniżej to produkcyjna ścieżka aplikacji:

    plan → generacja plików → diff → worktree → `gradlew` / `npm` → gating PR-a

Dlatego wymagają lokalnych klonów `shop-*` oraz JDK i Node — bez nich test się
POMIJA (na runnerze GitHuba nie ma repozytoriów siostrzanych). PR-y nigdy nie
lecą naprawdę: `open_pr_for_files` jest podmieniony, a test sprawdza tylko, Z CZYM
aplikacja by go wystawiła.

Skala rośnie od S1 (jeden plik) do S4 (cztery repozytoria, dwa języki); S5
sprawdza, że bramka potrafi powiedzieć „nie” i że pętla naprawcza to odkręca.
Opis scenariuszy: [`tests/scenarios.py`](scenarios.py).
"""

import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import pytest
from streamlit.testing.v1 import AppTest

from src.ingest import ingest_app
from tests import scenarios
from tests.scripted_llm import ScriptedLLM

APP = str(Path(__file__).resolve().parents[1] / "app.py")

# Te testy naprawdę budują serwisy (Gradle/npm) — kilka minut. `pytest -m
# "not scenario"` zostawia sam szybki zestaw jednostkowy i UI.
pytestmark = pytest.mark.scenario

# Kolejność jak w manifest.yaml — mapa repozytoriów podawana plannerowi
# ma odpowiadać temu, co widzi użytkownik w UI.
INDEXED_REPOS = [
    "shop-gateway", "shop-catalog", "shop-inventory", "shop-order",
    "shop-payment", "shop-notification", "shop-ui", "shop-acceptance-tests",
]


def _workspace() -> str:
    return os.environ.get("SHOP_REPOS_DIR") or str(Path(__file__).resolve().parents[2])


def _available_repos() -> dict[str, str]:
    root = _workspace()
    return {
        name: os.path.join(root, name)
        for name in INDEXED_REPOS
        if os.path.isdir(os.path.join(root, name, ".git"))
    }


_REPOS = _available_repos()
_CHUNKS: list | None = None


def _chunks() -> list:
    """Indeks całego workspace'u, policzony raz na cały moduł (~6 s)."""
    global _CHUNKS
    if _CHUNKS is None:
        _CHUNKS = ingest_app([{"name": n, "path": p} for n, p in _REPOS.items()])
    return _CHUNKS


def _toolchain_missing(repos: list[str]) -> str:
    """Czego brakuje, by bramka mogła realnie zbudować te repozytoria."""
    for repo in repos:
        path = _REPOS.get(repo)
        if path is None:
            return f"brak lokalnego klonu {repo}"
        if os.path.isfile(os.path.join(path, "gradlew.bat")) and not shutil.which("java"):
            return "brak JDK w PATH"
        if os.path.isfile(os.path.join(path, "package.json")) and not shutil.which("npm"):
            return "brak npm w PATH"
    return ""


class ScenarioHarness(unittest.TestCase):
    """Uruchamia scenariusz przez krok 3 aplikacji i udostępnia jej stan."""

    maxDiff = None

    def setUp(self) -> None:
        # Bramka lokalna nie zależy od trybu offline, ale gdyby QA_FAKE_LLM
        # wyciekło ze środowiska, przykryłoby podstawiony model atrapą.
        self._env = mock.patch.dict(
            os.environ, {"SHOP_REPOS_DIR": _workspace(), "QA_FAKE_LLM": ""}
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def _start(self, scenario: scenarios.Scenario, timeout: int = 900):
        missing = _toolchain_missing(scenario.repos)
        if missing:
            self.skipTest(f"{scenario.id}: {missing}")

        llm = ScriptedLLM(scenario)
        patcher = mock.patch("src.agent._call", llm)
        patcher.start()
        self.addCleanup(patcher.stop)

        app = AppTest.from_file(APP, default_timeout=timeout)
        app.session_state["active_tab"] = "sandbox"
        app.session_state["chunks"] = _chunks()
        app.session_state["repo_paths"] = dict(_REPOS)
        app.session_state["sandbox_question"] = scenario.question
        app.session_state["sandbox_accepted_proposals"] = scenario.proposals
        # Krok 2 przekazuje trafione fragmenty; bierzemy te z repozytoriów objętych
        # scenariuszem, żeby wejście plannera przypominało realny przebieg.
        app.session_state["sandbox_preload_chunks"] = [
            c for c in _chunks() if c.repo in scenario.repos
        ][:8]
        return llm, app.run()

    # ── odczyt stanu aplikacji ───────────────────────────────────────────────
    @staticmethod
    def _state(app, key: str, default=None):
        """`AppTest.session_state` to SafeSessionState — nie ma `.get()`."""
        return app.session_state[key] if key in app.session_state else default

    def _changes(self, app) -> list[dict]:
        return self._state(app, "sandbox_multi_changes") or []

    @staticmethod
    def _button(app, needle: str):
        for b in app.button:
            if needle in b.label:
                return b
        return None

    def _require_button(self, app, needle: str):
        button = self._button(app, needle)
        self.assertIsNotNone(
            button, f"brak przycisku „{needle}”; są: {[b.label for b in app.button]}"
        )
        return button

    def _assert_plan_matches(self, scenario: scenarios.Scenario, app) -> None:
        planned = {(f.repo, f.path) for f in scenario.files}
        produced = {(c["repo"], c["file_path"]) for c in self._changes(app)}
        self.assertEqual(planned, produced, "krok 3 zgubił lub dołożył pliki z planu")

    def _assert_content(self, scenario: scenarios.Scenario, app) -> None:
        by_path = {c["file_path"]: c for c in self._changes(app)}
        for path, needles in scenario.expect_content.items():
            change = by_path[path]
            self.assertTrue(
                (change.get("diff") or "").strip(),
                f"{path}: aplikacja nie zbudowała diffa",
            )
            for needle in needles:
                self.assertIn(needle, change["new_content"], f"{path}: brak „{needle}”")

    def _validate(self, app):
        """Klika lokalną bramkę i zwraca wyniki per repo."""
        self._require_button(app, "Uruchom walidację").click()
        app = app.run()
        self.assertFalse(app.exception, app.exception)
        return app, self._state(app, "sandbox_validation_results") or {}

    def _assert_green(self, scenario: scenarios.Scenario, results: dict) -> None:
        self.assertEqual(set(scenario.repos), set(results), "zwalidowano inne repo niż zmienione")
        for repo, result in results.items():
            self.assertTrue(
                result.get("success"),
                f"{repo}: bramka na czerwono\n{result.get('error')}\n{(result.get('output') or '')[-3000:]}",
            )
            self.assertTrue(
                result.get("project_check"),
                f"{repo}: uruchomiono tylko kontrolę statyczną, nie build projektu",
            )


class SingleServiceScenarioTests(ScenarioHarness):
    """S1 — najkrótsza droga: jeden serwis, jeden plik."""

    def test_s1_single_file_change_passes_the_local_gate(self):
        scenario = scenarios.S1_SINGLE_FILE
        llm, app = self._start(scenario)

        self.assertFalse(app.exception, app.exception)
        self._assert_plan_matches(scenario, app)
        self._assert_content(scenario, app)

        app, results = self._validate(app)
        self._assert_green(scenario, results)
        self.assertIn(
            "gradlew", " ".join(results["shop-catalog"]["commands"]).lower(),
            "katalog to projekt Gradle — bramka musiała go zbudować",
        )

    def test_s1_pull_request_is_blocked_until_the_gate_is_green(self):
        scenario = scenarios.S1_SINGLE_FILE
        _llm, app = self._start(scenario)

        pr_button = self._require_button(app, "Wystaw PR")
        self.assertTrue(pr_button.disabled, "PR dostępny przed walidacją")
        self.assertTrue(
            any("zablokowany do czasu zielonej" in w.value for w in app.warning),
            "brak informacji, dlaczego PR jest zablokowany",
        )

        app, _results = self._validate(app)
        self.assertFalse(self._require_button(app, "Wystaw PR").disabled,
                         "PR nadal zablokowany mimo zielonej bramki")


class MultiFileScenarioTests(ScenarioHarness):
    """S2 — jeden serwis, kilka warstw, w tym NOWY plik (migracja Flyway)."""

    def test_s2_new_file_and_modified_files_land_in_one_repo(self):
        scenario = scenarios.S2_SINGLE_REPO_MULTIFILE
        _llm, app = self._start(scenario)

        self.assertFalse(app.exception, app.exception)
        self._assert_plan_matches(scenario, app)
        self._assert_content(scenario, app)

        created = [c for c in self._changes(app) if c["action"] == "create"]
        self.assertEqual(
            ["src/main/resources/db/migration/V2__product_sku.sql"],
            [c["file_path"] for c in created],
            "migracja Flyway musi iść jako nowy plik, nie edycja V1",
        )

        app, results = self._validate(app)
        self._assert_green(scenario, results)

    def test_s2_opens_exactly_one_pull_request_with_all_files(self):
        scenario = scenarios.S2_SINGLE_REPO_MULTIFILE
        _llm, app = self._start(scenario)
        app, _results = self._validate(app)

        opened: list[dict] = []

        def fake_open_pr(file_changes, title, body, repo_slug, **kwargs):
            opened.append({"files": file_changes, "title": title, "slug": repo_slug,
                           "local_repo": kwargs.get("local_repo")})
            return {"success": True, "branch": "ai-change/test", "pr_url": "https://example/pr/1"}

        with mock.patch("src.sandbox.open_pr_for_files", side_effect=fake_open_pr):
            self._require_button(app, "Wystaw PR").click()
            app = app.run()

        self.assertFalse(app.exception, app.exception)
        self.assertEqual(1, len(opened), "jeden serwis = dokładnie jeden PR")
        self.assertEqual("ai-bot-playground/shop-catalog", opened[0]["slug"])
        self.assertEqual(
            {f.path for f in scenario.files},
            {f["path"] for f in opened[0]["files"]},
            "PR musi zebrać wszystkie pliki zmiany w jednym commicie",
        )
        migration = next(f for f in opened[0]["files"] if f["path"].endswith(".sql"))
        self.assertTrue(migration["allow_create"], "nowy plik bez allow_create zostanie odrzucony")
        self.assertEqual("pr", app.session_state["active_tab"], "po PR aplikacja nie przeszła do kroku 4")


class CrossLanguageScenarioTests(ScenarioHarness):
    """S3 — dwa repozytoria, dwa narzędzia budowania; oba muszą być zielone."""

    def test_s3_gradle_and_npm_gates_both_run(self):
        scenario = scenarios.S3_TWO_REPOS_TWO_LANGUAGES
        _llm, app = self._start(scenario)

        self.assertFalse(app.exception, app.exception)
        self._assert_plan_matches(scenario, app)
        self._assert_content(scenario, app)

        app, results = self._validate(app)
        self._assert_green(scenario, results)

        java_cmds = " ".join(results["shop-catalog"]["commands"]).lower()
        node_cmds = " ".join(results["shop-ui"]["commands"]).lower()
        self.assertIn("gradlew", java_cmds)
        self.assertIn("npm", node_cmds)
        self.assertIn("run build", node_cmds)

    def test_s3_red_frontend_blocks_the_pull_request_for_every_repo(self):
        """Zielona Java nie może przepchnąć PR-a, gdy frontend jest czerwony."""
        scenario = scenarios.S3_TWO_REPOS_TWO_LANGUAGES
        _llm, app = self._start(scenario)

        real_validate = __import__("src.sandbox", fromlist=["x"]).validate_file_changes

        def half_red(file_changes, local_repo, timeout=600):
            if str(local_repo).endswith("shop-ui"):
                return {"success": False, "commands": ["npm run build"],
                        "output": "error during build: Unexpected token", "error":
                        "Walidacja nie przeszła (exit 1).", "project_check": True,
                        "failure_kind": "code"}
            return real_validate(file_changes, local_repo, timeout)

        with mock.patch("src.sandbox.validate_file_changes", side_effect=half_red):
            self._require_button(app, "Uruchom walidację").click()
            app = app.run()

        self.assertFalse(app.exception, app.exception)
        self.assertTrue(self._require_button(app, "Wystaw").disabled,
                        "PR otwarty mimo czerwonego shop-ui")


class CrossServiceScenarioTests(ScenarioHarness):
    """S4 — zmiana przez cały system: dane → logika → zdarzenia → UI."""

    def test_s4_four_repositories_compile_together(self):
        scenario = scenarios.S4_CROSS_SERVICE
        _llm, app = self._start(scenario)

        self.assertFalse(app.exception, app.exception)
        self._assert_plan_matches(scenario, app)
        self._assert_content(scenario, app)
        self.assertEqual(
            {"shop-order", "shop-notification", "shop-ui", "shop-acceptance-tests"},
            {c["repo"] for c in self._changes(app)},
            "zmiana ma sięgnąć od sagi przez konsumenta i UI aż po testy akceptacyjne",
        )

        app, results = self._validate(app)
        self._assert_green(scenario, results)

    def test_s4_opens_one_pull_request_per_repository(self):
        scenario = scenarios.S4_CROSS_SERVICE
        _llm, app = self._start(scenario)
        app, _results = self._validate(app)

        opened: list[tuple[str, set]] = []

        def fake_open_pr(file_changes, title, body, repo_slug, **kwargs):
            opened.append((repo_slug, {f["path"] for f in file_changes}))
            return {"success": True, "branch": "ai-change/test", "pr_url": f"https://example/{repo_slug}"}

        with mock.patch("src.sandbox.open_pr_for_files", side_effect=fake_open_pr):
            self._require_button(app, "Wystaw").click()
            app = app.run()

        self.assertFalse(app.exception, app.exception)
        by_slug = dict(opened)
        self.assertEqual(
            {"ai-bot-playground/shop-order",
             "ai-bot-playground/shop-notification",
             "ai-bot-playground/shop-ui",
             "ai-bot-playground/shop-acceptance-tests"},
            set(by_slug),
            "jeden PR na repozytorium, bez duplikatów",
        )
        self.assertEqual(len(opened), len(by_slug), "to samo repo dostało więcej niż jeden PR")
        self.assertEqual(5, len(by_slug["ai-bot-playground/shop-order"]),
                         "wszystkie pliki shop-order w jednym PR")
        self.assertEqual(3, len(by_slug["ai-bot-playground/shop-acceptance-tests"]),
                         "klient, kroki i .feature idą jednym PR-em")
        # Krok 4 dostaje jeden wpis per repo, nie per plik.
        self.assertEqual(4, len(app.session_state["qa_multi_prs"]))


class BrokenChangeScenarioTests(ScenarioHarness):
    """S5 — bramka ma prawo powiedzieć „nie”, a pętla naprawcza to odkręcić."""

    def test_s5_compiler_error_blocks_pr_and_is_classified_as_code(self):
        scenario = scenarios.S5_BROKEN_THEN_REPAIRED
        _llm, app = self._start(scenario)

        app, results = self._validate(app)
        result = results["shop-catalog"]
        self.assertFalse(result["success"], "niekompilowalny kod przeszedł bramkę")
        self.assertEqual("code", result["failure_kind"],
                         "błąd kompilatora oznaczony jako problem środowiska")
        self.assertIn("totalCount", result["output"], "log nie zawiera prawdziwego błędu javac")
        self.assertTrue(self._require_button(app, "Wystaw").disabled,
                        "PR dostępny mimo czerwonej bramki")

    def test_s5_repair_loop_sends_the_real_log_and_turns_the_gate_green(self):
        scenario = scenarios.S5_BROKEN_THEN_REPAIRED
        llm, app = self._start(scenario)
        app, _results = self._validate(app)

        self._require_button(app, "Popraw pliki według logów").click()
        app = app.run()
        self.assertFalse(app.exception, app.exception)

        repair_prompts = llm.prompts("repair")
        self.assertTrue(repair_prompts, "pętla naprawcza nie odpytała modelu")
        self.assertIn("totalCount", repair_prompts[0],
                      "prompt naprawczy nie niesie prawdziwego logu kompilatora")

        results = self._state(app, "sandbox_validation_results") or {}
        self.assertTrue(results["shop-catalog"]["success"],
                        f"po naprawie bramka nadal czerwona:\n{results['shop-catalog'].get('output', '')[-2000:]}")
        self.assertFalse(self._require_button(app, "Wystaw").disabled,
                         "PR nadal zablokowany po zielonej walidacji")


if __name__ == "__main__":
    unittest.main()
