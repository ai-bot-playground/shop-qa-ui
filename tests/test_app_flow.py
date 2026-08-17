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

    def test_step_four_without_prs_explains_itself(self):
        app = AppTest.from_file(APP, default_timeout=60)
        app.session_state["active_tab"] = "pr"
        app = app.run()

        self.assertFalse(app.exception)
        self.assertTrue(any("Brak wystawionych PR" in i.value for i in app.info))


if __name__ == "__main__":
    unittest.main()
