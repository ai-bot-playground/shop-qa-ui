import unittest

from src import agent


class AgentFlowTests(unittest.TestCase):
    def test_repair_prompt_contains_failure_and_related_change(self):
        captured = []
        original_call = agent._call

        def fake_call(system, user_content, max_tokens=1024, light=False):
            captured.append(user_content)
            return "class PaymentService { /* fixed */ }"

        agent._call = fake_call
        try:
            repaired = agent.repair_file_change(
                "dodaj opłatę",
                [],
                "shop-payment",
                "src/PaymentService.java",
                "class PaymentService {}",
                "error: cannot find symbol FeePolicy",
                [{
                    "repo": "shop-payment",
                    "file_path": "src/FeePolicy.java",
                    "new_content": "class FeePolicy { /* RELATED_MARKER */ }",
                }],
            )
        finally:
            agent._call = original_call

        self.assertIn("fixed", repaired)
        self.assertIn("cannot find symbol FeePolicy", captured[0])
        self.assertIn("RELATED_MARKER", captured[0])
        self.assertIn("shop-payment/src/PaymentService.java", captured[0])

    def test_repair_no_change_sentinel_is_empty(self):
        original_call = agent._call
        agent._call = lambda *args, **kwargs: "BRAK_ZMIAN"
        try:
            repaired = agent.repair_file_change(
                "zmiana", [], "shop-order", "OrderService.java", "class OrderService {}", "failure"
            )
        finally:
            agent._call = original_call

        self.assertEqual("", repaired)

    def test_failed_completeness_review_is_not_reported_as_complete(self):
        def broken_call(*args, **kwargs):
            raise TimeoutError("read timed out")

        original_call = agent._call
        agent._call = broken_call
        try:
            verdict = agent.verify_completeness("zmiana", [], "repo-map", [])
        finally:
            agent._call = original_call

        self.assertFalse(verdict["complete"])
        self.assertIn("read timed out", verdict["error"])

    def test_file_generation_sees_its_plan_role_and_sibling_files(self):
        # Przebieg z prawdziwym modelem (05.10): PurchaseSteps.java generowany w izolacji
        # nie wiedział o nowym initial-stock.feature i wracał jako BRAK_ZMIAN.
        captured = []
        original_call = agent._call
        agent._call = lambda system, user, **kw: captured.append(user) or "class PurchaseSteps {}"
        change_set = [
            {"repo": "shop-acceptance-tests", "file_path": "src/test/java/PurchaseSteps.java",
             "action": "modify", "reason": "Kroki dla seedowanych produktów", "new_content": None},
            {"repo": "shop-acceptance-tests", "file_path": "src/test/resources/features/initial-stock.feature",
             "action": "create", "reason": "Scenariusz zakupu seedowanego produktu",
             "new_content": "Scenario: buy seeded\n  Given the seeded product \"1\""},
        ]
        try:
            agent.generate_file_change(
                "seed", [], "src/test/java/PurchaseSteps.java", "class PurchaseSteps {}",
                repo="shop-acceptance-tests", reason="Kroki dla seedowanych produktów",
                change_set=change_set,
            )
        finally:
            agent._call = original_call

        prompt = captured[0]
        self.assertIn("ZADANIE TEGO PLIKU W PLANIE: Kroki dla seedowanych produktów", prompt)
        self.assertIn('Given the seeded product "1"', prompt)
        self.assertNotIn("- shop-acceptance-tests/src/test/java/PurchaseSteps.java", prompt,
                         "plik docelowy nie powinien być listowany jako „pozostały”")
        # Atrapa i model skryptowy czytają pierwszy blok ``` po „PLIK:" — musi to być plik docelowy.
        first_block = prompt.split("```\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual("class PurchaseSteps {}", first_block)

    def test_light_call_falls_back_when_reasoning_is_mandatory(self):
        # openai/gpt-6.1-sol: `reasoning.enabled=false` → 400 „Reasoning is mandatory…".
        from unittest import mock

        rejected = mock.Mock(status_code=400, text='{"error":{"message":"Reasoning is mandatory '
                             'for this endpoint and cannot be disabled."}}')
        ok = mock.Mock(status_code=200)
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"choices": [{"message": {"content": "Warszawa"}}], "usage": {}}
        sent = []

        def fake_post(url, headers=None, json=None, timeout=None):
            sent.append(dict(json["reasoning"]))
            return rejected if len(sent) == 1 else ok

        with mock.patch("src.agent.requests.post", side_effect=fake_post), \
                mock.patch.dict("os.environ", {"QA_FAKE_LLM": ""}):
            reply = agent._call("system", "user", max_tokens=32, light=True)

        self.assertEqual("Warszawa", reply)
        self.assertEqual([{"enabled": False}, {"effort": "low"}], sent)


if __name__ == "__main__":
    unittest.main()