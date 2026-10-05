"""Testy UI przez `streamlit.testing.v1.AppTest` — uruchamiają PRAWDZIWE `app.py`.

Pokrywają trzy miejsca, w których przepływ potrafił się zatrzymać bez żadnego
komunikatu ani przycisku (użytkownik widział pusty ekran i musiał zakładać
nowy wątek):
  * krok 3 dla pliku `.py` (dawny guard bez gałęzi `else`),
  * krok 3 gdy model nie wygenerował żadnej zmiany,
  * krok 4 — sekcja merge była za `qa_repo_slug`, którego nikt nigdy nie ustawiał.

Wszystko na atrapie LLM (`QA_FAKE_LLM=1`) i na tymczasowym workspace, więc test
jest szybki, hermetyczny i nie dotyka prawdziwych repo ani sieci.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")

JAVA_SOURCE = """\
package com.shop.payment;

class PaymentService {
    void charge(long orderId) {
    }
}
"""


def _make_workspace(tmp: str, with_python_file: bool = False) -> str:
    """Workspace z jednym repo `shop-payment` (git + plik Javy)."""
    repo = Path(tmp, "shop-payment")
    (repo / "src" / "main" / "java" / "com" / "shop" / "payment").mkdir(parents=True)
    (repo / "src/main/java/com/shop/payment/PaymentService.java").write_text(
        JAVA_SOURCE, encoding="utf-8"
    )
    if with_python_file:
        # Plik `.py` sortuje się przed `src/...`, więc trafia na czoło retrievalu —
        # dokładnie przypadek, który dawniej dawał pusty ekran w kroku 3.
        (repo / "aaa_tooling.py").write_text(
            "def charge_report():\n    return 'payment charge'\n", encoding="utf-8"
        )
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    return str(repo.parent)


class AppSmokeTests(unittest.TestCase):
    def test_app_starts_on_step_one(self):
        app = AppTest.from_file(APP, default_timeout=60).run()

        self.assertFalse(app.exception)
        self.assertEqual("ready", app.session_state["active_tab"])
        self.assertIn("System Ready", [t.value for t in app.title])


class SandboxFlowTests(unittest.TestCase):
    """Krok 3 zawsze musi dawać użytkownikowi jakieś wyjście."""

    def _run_sandbox(self, workspace: str, chunks_filter=None) -> AppTest:
        from src.ingest import ingest_app

        repos = [{"name": "shop-payment", "path": os.path.join(workspace, "shop-payment")}]
        chunks = ingest_app(repos)
        if chunks_filter:
            chunks = [c for c in chunks if chunks_filter(c)]
        self.assertTrue(chunks, "fixture nie wygenerował żadnych chunków")

        app = AppTest.from_file(APP, default_timeout=120)
        app.session_state["active_tab"] = "sandbox"
        app.session_state["chunks"] = chunks
        app.session_state["repo_paths"] = {
            "shop-payment": os.path.join(workspace, "shop-payment")
        }
        app.session_state["sandbox_question"] = "dodaj opłatę serwisową"
        app.session_state["sandbox_accepted_proposals"] = []
        app.session_state["sandbox_preload_chunks"] = chunks
        return app.run()

    def test_python_chunk_no_longer_produces_a_blank_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp, with_python_file=True)
            with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1", "SHOP_REPOS_DIR": workspace}):
                app = self._run_sandbox(
                    workspace, chunks_filter=lambda c: c.file_path.endswith(".py")
                )

        self.assertFalse(app.exception)
        # Ekran nie może być pusty: albo plan/diff, albo jawny komunikat + wyjście.
        rendered = (
            len(app.button) + len(app.warning) + len(app.error) + len(app.info)
        )
        self.assertGreater(rendered, 0, "krok 3 nie wyrenderował niczego dla pliku .py")

    def test_sandbox_offers_a_way_out_when_nothing_was_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            # Atrapa planuje pliki, ale generacja zwraca pustkę → zero diffów.
            with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1", "SHOP_REPOS_DIR": workspace}), \
                    mock.patch("src.agent.generate_file_change", return_value=""), \
                    mock.patch("src.agent.generate_new_file", return_value=""):
                app = self._run_sandbox(workspace)

        self.assertFalse(app.exception)
        labels = [b.label for b in app.button]
        self.assertTrue(
            any("Wróć do Analyze" in l for l in labels)
            or any("ponownie" in l for l in labels),
            f"brak wyjścia z kroku 3; przyciski: {labels}",
        )


class RepairLoopTests(unittest.TestCase):
    """Naprawa z logu musi sięgać też po pliki z planu, które wróciły puste."""

    def test_repair_fills_a_planned_file_that_came_back_empty(self):
        # Przebieg z prawdziwym modelem (05.10): PurchaseSteps.java wrócił pusty, dry-run
        # Cucumbera zgłosił niezdefiniowane kroki, a naprawa obejmowała tylko pliki z diffem.
        from src.ingest import ingest_app

        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            repo_path = os.path.join(workspace, "shop-payment")
            service = "src/main/java/com/shop/payment/PaymentService.java"
            policy = "src/main/java/com/shop/payment/FeePolicy.java"
            changed = JAVA_SOURCE.replace("void charge", "long fee() { return FeePolicy.FEE; }\n    void charge")
            app = AppTest.from_file(APP, default_timeout=120)
            app.session_state["active_tab"] = "sandbox"
            app.session_state["chunks"] = ingest_app([{"name": "shop-payment", "path": repo_path}])
            app.session_state["repo_paths"] = {"shop-payment": repo_path}
            app.session_state["sandbox_question"] = "dodaj opłatę"
            app.session_state["sandbox_accepted_proposals"] = []
            app.session_state["sandbox_preload_chunks"] = app.session_state["chunks"]
            app.session_state["sandbox_plan"] = [
                {"repo": "shop-payment", "path": service, "action": "modify", "reason": "użyj opłaty"},
                {"repo": "shop-payment", "path": policy, "action": "create", "reason": "polityka opłat"},
            ]
            app.session_state["sandbox_multi_changes"] = [
                {"repo": "shop-payment", "file_path": service, "action": "modify", "reason": "użyj opłaty",
                 "original": JAVA_SOURCE, "repo_path": repo_path, "new_content": changed,
                 "diff": "--- a\n+++ b\n+fee", "error": None, "pr_result": None},
                {"repo": "shop-payment", "file_path": policy, "action": "create", "reason": "polityka opłat",
                 "original": "", "repo_path": repo_path, "new_content": "",
                 "diff": "", "error": None, "pr_result": None},
            ]
            app.session_state["sandbox_validation_results"] = {"shop-payment": {
                "success": False, "failure_kind": "code", "error": "Walidacja nie przeszła (exit 1).",
                "output": "error: cannot find symbol FeePolicy", "commands": [],
            }}
            validated = []

            def fake_validate(changes, local_repo, timeout=600):
                validated.append(sorted(c["file_path"] for c in changes))
                return {"success": True, "project_check": True, "commands": [], "output": "", "error": "",
                        "failure_kind": ""}

            def fake_repair(question, proposals, repo, file_path, current, log, related=None):
                return "class FeePolicy { static final long FEE = 1; }" if file_path == policy else ""

            with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1", "SHOP_REPOS_DIR": workspace}), \
                    mock.patch("src.agent.repair_file_change", side_effect=fake_repair), \
                    mock.patch("src.sandbox.validate_file_changes", side_effect=fake_validate):
                app = app.run()
                repair = next(b for b in app.button if "Popraw pliki" in b.label)
                app = repair.click().run()

        self.assertFalse(app.exception, app.exception)
        filled = next(c for c in app.session_state["sandbox_multi_changes"] if c["file_path"] == policy)
        self.assertIn("FeePolicy", filled["new_content"])
        self.assertTrue(filled["diff"].strip())
        self.assertEqual([[policy, service]], validated, "ponowna walidacja musi objąć dopisany plik")


class PrStepTests(unittest.TestCase):
    """Krok 4 — status bramki i merge dla ścieżki multi-repo."""

    def _app_with_prs(self) -> AppTest:
        app = AppTest.from_file(APP, default_timeout=60)
        app.session_state["active_tab"] = "pr"
        app.session_state["qa_multi_prs"] = [{
            "repo": "shop-payment",
            "repo_slug": "ai-bot-playground/shop-payment",
            "pr_url": "https://github.com/ai-bot-playground/shop-payment/pull/1",
            "branch": "ai-change-abc123",
            "success": True,
            "error": "",
            "warning": "",
        }]
        return app

    def test_green_gate_exposes_merge_button(self):
        green = {"available": True, "checks": [{"name": "preprod-gate", "bucket": "pass"}]}

        with mock.patch("src.sandbox.pr_checks", return_value=green):
            app = self._app_with_prs().run()

        self.assertFalse(app.exception)
        labels = [b.label for b in app.button]
        self.assertTrue(any("Merge PR" in l for l in labels), f"przyciski: {labels}")
        self.assertTrue(
            any("Potwierdzam" in c.label for c in app.checkbox),
            "brak checkboxa potwierdzenia człowieka",
        )

    def test_merge_button_is_disabled_until_human_confirms(self):
        green = {"available": True, "checks": [{"name": "preprod-gate", "bucket": "pass"}]}

        with mock.patch("src.sandbox.pr_checks", return_value=green):
            app = self._app_with_prs().run()
            merge = next(b for b in app.button if "Merge PR" in b.label)
            self.assertTrue(merge.disabled)

            confirm = next(c for c in app.checkbox if "Potwierdzam" in c.label)
            app = confirm.check().run()
            merge = next(b for b in app.button if "Merge PR" in b.label)
            self.assertFalse(merge.disabled)

    def test_pending_gate_does_not_offer_merge(self):
        pending = {"available": True, "checks": [{"name": "preprod-gate", "bucket": "pending"}]}

        with mock.patch("src.sandbox.pr_checks", return_value=pending):
            app = self._app_with_prs().run()

        self.assertFalse(any("Merge PR" in b.label for b in app.button))

    def test_merge_marks_pr_as_merged(self):
        green = {"available": True, "checks": [{"name": "preprod-gate", "bucket": "pass"}]}

        with mock.patch("src.sandbox.pr_checks", return_value=green), \
                mock.patch("src.sandbox.merge_pr", return_value={"success": True}) as merged:
            app = self._app_with_prs().run()
            next(c for c in app.checkbox if "Potwierdzam" in c.label).check().run()
            next(b for b in app.button if "Merge PR" in b.label).click().run()

        merged.assert_called_once_with(
            "ai-bot-playground/shop-payment", "ai-change-abc123"
        )
        self.assertTrue(
            app.session_state["qa_merged"]["ai-bot-playground/shop-payment"]
        )

    def test_cancelled_gate_is_a_failure_not_endless_pending(self):
        # `gh pr checks` zgłasza anulowany check jako bucket "cancel" — dawniej
        # wpadał do „pending" i panel odpytywał GitHuba w nieskończoność.
        cancelled = {"available": True, "checks": [{"name": "preprod-gate / gate", "bucket": "cancel"}]}

        with mock.patch("src.sandbox.pr_checks", return_value=cancelled), \
                mock.patch("src.sandbox.pr_failure_summary", return_value=""):
            app = self._app_with_prs().run()

        self.assertFalse(app.exception)
        self.assertEqual("failure", app.session_state["qa_gate_states"]["ai-bot-playground/shop-payment"])
        self.assertFalse(any("Merge PR" in b.label for b in app.button))

    def _app_with_ungated_pr(self, age_s: float, required: list | None) -> AppTest:
        import time
        no_checks = {"available": True, "checks": [], "message": "no checks reported"}
        app = self._app_with_prs()
        app.session_state["qa_multi_prs"][0]["opened_at"] = time.time() - age_s
        with mock.patch("src.sandbox.pr_checks", return_value=no_checks), \
                mock.patch("src.sandbox.required_checks", return_value=required):
            return app.run()

    def test_repo_without_any_gate_offers_merge_with_warning(self):
        # Np. shop-acceptance-tests: `main` bez ochrony i bez workflow na PR —
        # check nigdy się nie pojawi, więc czekanie w nieskończoność blokowało pętlę.
        app = self._app_with_ungated_pr(age_s=120, required=[])

        self.assertFalse(app.exception)
        self.assertEqual("no_gate", app.session_state["qa_gate_states"]["ai-bot-playground/shop-payment"])
        self.assertTrue(any("nie ma bramki" in w.value for w in app.warning))
        self.assertTrue(any("Merge PR" in b.label for b in app.button))

    def test_fresh_pr_without_checks_still_waits_for_the_gate(self):
        app = self._app_with_ungated_pr(age_s=5, required=[])

        self.assertEqual("pending", app.session_state["qa_gate_states"]["ai-bot-playground/shop-payment"])
        self.assertFalse(any("Merge PR" in b.label for b in app.button))

    def test_protected_repo_without_checks_never_skips_the_gate(self):
        # Wymagany check, który nie wystartował (np. runner offline) — to NIE jest „brak bramki".
        app = self._app_with_ungated_pr(age_s=600, required=["preprod-gate / gate"])

        self.assertEqual("pending", app.session_state["qa_gate_states"]["ai-bot-playground/shop-payment"])
        self.assertFalse(any("Merge PR" in b.label for b in app.button))

    def test_step_four_without_prs_explains_itself(self):
        app = AppTest.from_file(APP, default_timeout=60)
        app.session_state["active_tab"] = "pr"
        app = app.run()

        self.assertFalse(app.exception)
        self.assertTrue(any("Brak wystawionych PR" in i.value for i in app.info))


if __name__ == "__main__":
    unittest.main()
