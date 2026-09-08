import unittest
from browser_agent.planner import parse_task_plan, TaskPlan

class TestProductTaskParserRegressions(unittest.TestCase):
    def assert_plan(self, instruction, expected_query, expected_requested=None, expected_intent=None):
        plan = parse_task_plan(instruction)
        self.assertIsInstance(plan, TaskPlan)
        self.assertEqual(plan.search_query, expected_query)
        if expected_requested is not None:
            for info in expected_requested:
                self.assertIn(info, plan.requested_information)
        if expected_intent is not None:
            self.assertEqual(plan.intent, expected_intent)

    def test_average_price_basketball_shoes(self):
        self.assert_plan(
            "what is the average price of basketball shoes in india",
            "basketball shoes in india",
            expected_requested=["price"],
            expected_intent="product_search"
        )

    def test_average_price_laptops(self):
        self.assert_plan(
            "what is the average price of laptops in india",
            "laptops in india",
            expected_requested=["price"],
            expected_intent="product_search"
        )

    def test_find_price_basketball_shoes(self):
        self.assert_plan(
            "find the price of basketball shoes",
            "basketball shoes",
            expected_requested=["price"],
            expected_intent="product_search"
        )

    def test_find_priceof_typo(self):
        self.assert_plan(
            "find the priceof basketball shoes",
            "basketball shoes",
            expected_requested=["price"],
            expected_intent="product_search"
        )

    def test_flipkart_priceof_typo(self):
        plan = parse_task_plan("go to flipkart and find the priceof basketball shoes")
        self.assertEqual(plan.destination, "flipkart")
        self.assertEqual(plan.search_query, "basketball shoes")
        self.assertIn("price", plan.requested_information)
        self.assertEqual(plan.intent, "product_search")

    def test_find_cheap_running_shoes(self):
        plan = parse_task_plan("find cheap running shoes")
        self.assertEqual(plan.search_query, "cheap running shoes")
        self.assertEqual(plan.ranking_field, "price")
        self.assertEqual(plan.ranking_order, "asc")

    def test_find_headphones_under_5000(self):
        plan = parse_task_plan("find headphones under 5000")
        self.assertEqual(plan.search_query, "headphones")
        self.assertTrue(any(c.get('field') == 'price' for c in plan.constraints))

if __name__ == '__main__':
    unittest.main()
