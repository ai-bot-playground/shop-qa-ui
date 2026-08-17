"""Testy trybu offline (`QA_FAKE_LLM=1`) i normalizacji ścieżek.

Sens: przepływ Piaskownicy (plan → generacja → recenzja) da się przejść bez
wywołania modelu, a atrapa musi zwracać dane, które przechodzą przez PRAWDZIWE
parsery `agent.py` — inaczej test nie dowodziłby niczego o aplikacji.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import agent, fake_llm
from src.ingest import ingest_repo


def _repo_map_fixture() -> str:
    """Format dokładnie jak z `agent.build_repo_map`."""
    return (
        "## shop-payment\n"
        "- build.gradle  [dependencies]\n"
        "- src/main/java/com/shop/payment/PaymentService.java  [PaymentService, charge]\n"
        "- src/main/resources/db/migration/V1__init.sql  [V1__init.sql]\n"
        "- src/main/resources/application.yml  [application.yml]\n"
        "## shop-ui\n"
        "- package.json  [package.json]\n"
        "- src/App.jsx  [App]\n"
    )


def _plan_prompt(repo_map: str, question: str = "dodaj opłatę serwisową") -> str:
    """Prompt plannera z sekcjami w tej samej kolejności co w `agent.plan_change`."""
    return (
        "KONTEKST SYSTEMU:\n- Stack: Spring Boot\n- Serwisy: shop-payment\n\n"
        f"MAPA REPOZYTORIÓW (istniejące pliki i symbole):\n{repo_map}\n\n"
        "TRAFNE FRAGMENTY RZECZYWISTEGO KODU (główne źródło decyzji):\n(brak)\n\n"
        f"ŻĄDANA ZMIANA: {question}\n"
        "Zaakceptowane propozycje:\n"
        "- Propozycja A: opis pierwszej propozycji\n"
        "- Propozycja B: opis drugiej propozycji\n\n"
        "Zwróć plan zmian jako JSON:"
    )


class FakeLlmRepoMapTests(unittest.TestCase):
    def test_repo_map_parsing_ignores_proposal_list(self):
        parsed = fake_llm._repo_map(_plan_prompt(_repo_map_fixture()))

        self.assertEqual({"shop-payment", "shop-ui"}, set(parsed))
        self.assertIn("src/App.jsx", parsed["shop-ui"])
        # Lista propozycji też zaczyna się od "- ", ale nie jest ścieżką.
        self.assertNotIn(
            "Propozycja A", " ".join(p for paths in parsed.values() for p in paths)
        )

    def test_plan_picks_modifiable_files_across_repos_plus_one_new_file(self):
        plan = agent.plan_change.__wrapped__ if hasattr(agent.plan_change, "__wrapped__") else None
        del plan  # plan_change nie jest dekorowane — poniżej idziemy przez publiczne API

        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            result = agent.plan_change("dodaj opłatę serwisową", _repo_map_fixture(), [])

        actions = {(f["repo"], f["path"]): f["action"] for f in result}
        self.assertEqual(
            {
                ("shop-payment", "src/main/java/com/shop/payment/PaymentService.java"): "modify",
                ("shop-ui", "src/App.jsx"): "modify",
                ("shop-payment", "docs/ai-change-note.md"): "create",
            },
            actions,
        )

    def test_plan_never_touches_migrations_or_json(self):
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            result = agent.plan_change("zmiana", _repo_map_fixture(), [])

        touched = [f["path"] for f in result]
        self.assertFalse([p for p in touched if p.endswith((".sql", ".json"))], touched)


class FakeLlmGenerationTests(unittest.TestCase):
    def test_modify_appends_comment_for_language_and_keeps_original(self):
        original = "class PaymentService {\n    void charge() {}\n}"

        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            updated = agent.generate_file_change(
                "dodaj opłatę", [], "src/main/java/PaymentService.java", original
            )

        self.assertTrue(updated.startswith(original))
        self.assertIn("// [QA_FAKE_LLM]", updated)
        # Bez trailing whitespace — `git diff --check` w bramce lokalnej jest czuły.
        self.assertFalse([ln for ln in updated.splitlines() if ln != ln.rstrip()])

    def test_modify_refuses_file_without_comment_syntax(self):
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            updated = agent.generate_file_change("zmiana", [], "package.json", '{"a": 1}')

        self.assertEqual("", updated)  # BRAK_ZMIAN → "" po stronie agenta

    def test_new_markdown_file_has_content(self):
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            created = agent.generate_new_file("zmiana", [], "shop-payment", "docs/ai-change-note.md")

        self.assertIn("QA_FAKE_LLM", created)
        self.assertIn("Notatka zmiany", created)
        # `_strip_fences` obcina skrajne newline'y — to walidacja dopisuje końcowy \n.
        self.assertFalse(created.startswith("\n"))


class FakeLlmAnalysisTests(unittest.TestCase):
    def _qa_prompt(self) -> str:
        return (
            "KONTEKST SYSTEMU:\n- Serwisy: shop-payment\n\n"
            "KOD:\n# REPO/PLIK: shop-payment/src/main/java/PaymentService.java "
            "| FUNKCJA: charge | LINIE: 12–30\nclass PaymentService {}\n\n"
            "PYTANIE: jak działa płatność"
        )

    def test_business_json_parses_and_recommends_one_proposal(self):
        data = agent._extract_json(fake_llm.respond("biz", self._qa_prompt()))

        self.assertEqual(3, len(data["proposals"]))
        self.assertEqual(0, data["recommended_index"])
        self.assertEqual("Tak", data["feasibility"]["verdict"])
        self.assertEqual(["shop-payment"], data["feasibility"]["impacted_services"])

    def test_technical_answer_carries_citation(self):
        answer = fake_llm.respond("tech", self._qa_prompt())

        self.assertIn("[source: shop-payment/src/main/java/PaymentService.java:12]", answer)

    def test_completeness_review_is_green(self):
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            verdict = agent.verify_completeness("zmiana", [], _repo_map_fixture(), [])

        self.assertTrue(verdict["complete"])
        self.assertEqual([], verdict["missing"])

    def test_repair_returns_no_change(self):
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            repaired = agent.repair_file_change(
                "zmiana", [], "shop-payment", "A.java", "class A {}", "error: boom"
            )

        self.assertEqual("", repaired)


class FakeLlmIsolationTests(unittest.TestCase):
    def test_fake_mode_never_reaches_the_network(self):
        def explode(*args, **kwargs):
            raise AssertionError("tryb offline nie może wołać OpenRoutera")

        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}), \
                mock.patch.object(agent, "_call_openrouter", explode):
            self.assertTrue(agent.plan_change("zmiana", _repo_map_fixture(), []))

    def test_flag_is_read_per_call_not_at_import(self):
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "0"}):
            self.assertFalse(agent._fake_llm_enabled())
        with mock.patch.dict(os.environ, {"QA_FAKE_LLM": "1"}):
            self.assertTrue(agent._fake_llm_enabled())


class IngestPathTests(unittest.TestCase):
    def test_indexed_paths_are_posix(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "src", "main", "java", "com", "shop")
            target.mkdir(parents=True)
            (target / "PaymentService.java").write_text(
                "package com.shop;\n\nclass PaymentService {\n    void charge() {}\n}\n",
                encoding="utf-8",
            )

            chunks = ingest_repo(tmp)

        self.assertTrue(chunks, "indeks nie zwrócił żadnego symbolu")
        for chunk in chunks:
            self.assertNotIn("\\", chunk.file_path)
        self.assertTrue(
            any(c.file_path == "src/main/java/com/shop/PaymentService.java" for c in chunks),
            [c.file_path for c in chunks],
        )


if __name__ == "__main__":
    unittest.main()
