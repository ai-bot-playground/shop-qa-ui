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


if __name__ == "__main__":
    unittest.main()