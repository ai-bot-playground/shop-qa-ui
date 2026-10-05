"""Pełna droga użytkownika: indeksowanie → pytanie → akceptacja → Piaskownica.

Pozostałe testy wchodzą do kroku 3 z ręcznie ustawionym `session_state`.
Tutaj nic nie jest ustawiane na skróty: test klika te same przyciski co człowiek,
więc pilnuje PRZEKAZANIA stanu między krokami — miejsca, w którym najłatwiej
o cichą regresję (krok 3 dostaje puste pytanie, brak chunków albo stary plan,
i kończy się ekranem „nie ma czego modyfikować").

Workspace jest tymczasowy i minimalny, a model to atrapa offline
(`QA_FAKE_LLM=1`), więc test jest szybki i nie dotyka prawdziwych repo ani sieci.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")

JAVA = """\
package com.shop.catalog.api;

class ProductController {
    long count() {
        return 0;
    }
}
"""


def _workspace(tmp: str) -> str:
    """Dwa repozytoria z `manifest.yaml`, żeby selektor aplikacji je zobaczył."""
    for repo, pkg in (("shop-catalog", "catalog"), ("shop-notification", "notification")):
        src = Path(tmp, repo, "src", "main", "java", "com", "shop", pkg, "api")
        src.mkdir(parents=True)
        (src / "ProductController.java").write_text(
            JAVA.replace("com.shop.catalog.api", f"com.shop.{pkg}.api"), encoding="utf-8"
        )
        subprocess.run(["git", "init", str(Path(tmp, repo))], check=True, capture_output=True)
    return tmp


class UserJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = _workspace(self._tmp.name)
        env = mock.patch.dict(
            os.environ, {"QA_FAKE_LLM": "1", "SHOP_REPOS_DIR": self.workspace}
        )
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def _state(app, key: str, default=None):
        return app.session_state[key] if key in app.session_state else default

    @staticmethod
    def _circle_of(stepper_html: str, label: str) -> str:
        """Zawartość kółka kroku o danej etykiecie („✓" albo numer)."""
        import re
        match = re.search(
            r">([^<>]{1,3})</div>\s*<div style='[^']*'>" + re.escape(label) + "<",
            stepper_html,
        )
        return match.group(1) if match else ""

    def _click(self, app, needle: str):
        button = next((b for b in app.button if needle in b.label), None)
        self.assertIsNotNone(
            button, f"brak przycisku „{needle}”; są: {[b.label for b in app.button]}"
        )
        return button.click().run()

    def test_indexing_then_question_then_accept_lands_in_sandbox(self):
        app = AppTest.from_file(APP, default_timeout=180).run()
        self.assertEqual("ready", app.session_state["active_tab"])

        # ── Krok 1: indeksowanie z panelu bocznego ──
        app = self._click(app, "Indeksuj aplikację")
        self.assertFalse(app.exception, app.exception)
        chunks = self._state(app, "chunks") or []
        self.assertTrue(chunks, "indeksowanie nie zwróciło żadnych symboli")
        self.assertEqual({"shop-catalog", "shop-notification"}, {c.repo for c in chunks})
        self.assertEqual("analyze", app.session_state["active_tab"],
                         "po zaindeksowaniu aplikacja powinna przejść do kroku 2")

        # ── Krok 2: pytanie ──
        question = "Dodaj endpoint zwracający liczbę produktów w katalogu."
        app.text_area[0].set_value(question)
        app = self._click(app, "Zapytaj")
        self.assertFalse(app.exception, app.exception)

        messages = app.session_state["sessions"][0]["messages"]
        self.assertEqual(1, len(messages), "pytanie nie trafiło do historii wątku")
        self.assertEqual(question, messages[0]["question"])
        self.assertTrue(messages[0]["proposals"], "analiza nie zwróciła propozycji")
        self.assertIsNotNone(messages[0]["recommended_index"],
                             "to agent wybiera rekomendację, nie użytkownik")

        # ── Krok 2 → 3: akceptacja rekomendacji ──
        app = self._click(app, "Akceptuj rekomendację")
        self.assertFalse(app.exception, app.exception)
        self.assertEqual("sandbox", app.session_state["active_tab"])
        self.assertEqual(question, app.session_state["sandbox_question"],
                         "krok 3 dostał inne pytanie niż zaakceptowane")
        self.assertTrue(self._state(app, "sandbox_accepted_proposals"),
                        "krok 3 nie dostał zaakceptowanej propozycji")
        self.assertTrue(self._state(app, "sandbox_preload_chunks"),
                        "krok 3 nie dostał trafionych fragmentów kodu")

        # ── Krok 3 wygenerował zmiany i zapalił swój znacznik w stepperze ──
        changes = self._state(app, "sandbox_multi_changes") or []
        self.assertTrue(changes, "krok 3 nie zaplanował ani jednego pliku")
        self.assertTrue(
            any((c.get("new_content") or "").strip() for c in changes),
            "atrapa nie wygenerowała treści dla żadnego pliku",
        )

    def test_sandbox_counts_as_completed_once_changes_exist(self):
        """Stepper ma odzwierciedlać stan, a nie czekać na PR.

        Wcześniej `_completed_steps()` patrzyło na `sandbox_results` — klucz,
        którego nikt nie ustawia — więc krok 3 zapalał się dopiero po PR-ze.
        """
        app = AppTest.from_file(APP, default_timeout=180).run()
        app = self._click(app, "Indeksuj aplikację")
        app.text_area[0].set_value("Dodaj endpoint licznika produktów.")
        app = self._click(app, "Zapytaj")
        app = self._click(app, "Akceptuj rekomendację")

        self.assertTrue(self._state(app, "sandbox_multi_changes"))
        self.assertNotIn("sandbox_results", app.session_state,
                         "wrócił martwy klucz stanu")

        # Stepper rysuje „✓" w kółku kroku ukończonego, a jego numer — gdy nie jest.
        stepper = next(m.value for m in app.markdown if "Workflow" in m.value)
        for label, expected in (("System Ready", "✓"), ("Analyze", "✓"),
                                ("Piaskownica", "✓"), ("PR", "4")):
            self.assertEqual(
                expected, self._circle_of(stepper, label),
                f"krok „{label}” ma zły znacznik w stepperze",
            )


if __name__ == "__main__":
    unittest.main()
