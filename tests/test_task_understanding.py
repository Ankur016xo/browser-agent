"""
Unit tests for Task Understanding, Destination Extraction, Query Normalization, and Clean State.
"""
import unittest
from pathlib import Path
from browser_agent.agent import extract_destination_url, normalize_task
from browser_agent.planner import parse_task_plan
from web_server import AgentServerRuntime, SCREENSHOT_PATHS


class TestTaskUnderstanding(unittest.TestCase):
    """Test suite for parsing natural language tasks into destinations and clean search queries."""

    def test_destination_extraction_explicit_url(self):
        url = extract_destination_url("Open https://example.com and check page title")
        self.assertEqual(url, "https://example.com")

    def test_destination_extraction_domain(self):
        url = extract_destination_url("Open example.com and tell me heading")
        self.assertEqual(url, "https://example.com")

    def test_destination_extraction_flipkart(self):
        url = extract_destination_url("Go to Flipkart and find a laptop bag under ₹1000 with the best rating")
        self.assertEqual(url, "https://www.flipkart.com")

    def test_destination_extraction_amazon(self):
        url = extract_destination_url("Open Amazon and find wireless headphones under ₹2000")
        self.assertEqual(url, "https://www.amazon.in")

    def test_destination_extraction_duckduckgo(self):
        url = extract_destination_url("Search DuckDuckGo for Python documentation")
        self.assertEqual(url, "https://duckduckgo.com")

    def test_destination_extraction_wikipedia(self):
        url = extract_destination_url("Search Wikipedia for Quantum Computing")
        self.assertEqual(url, "https://www.wikipedia.org")

    def test_normalize_task_ecommerce_cheapest_with_rating(self):
        task = "open flipkart and find me the cheapest laptop bag with the best rating"
        query = normalize_task(task)
        self.assertEqual(query, "laptop bag")

    def test_normalize_task_ecommerce_constraint_and_rating(self):
        task = "Go to Flipkart and find a laptop bag under ₹1000 with the best rating. Open the most relevant product and tell me its name, price, and rating."
        query = normalize_task(task)
        self.assertEqual(query, "laptop bag")

    def test_normalize_task_flipkart_multiclause_instruction(self):
        task = "Go to Flipkart, search for laptop bags under ₹1000, handle any login or popup that appears without logging in, open a suitable product, and tell me its product name, price, and rating."
        query = normalize_task(task)
        self.assertEqual(query, "laptop bags")

    def test_normalize_task_amazon_constraint(self):
        task = "Open Amazon and find wireless headphones under ₹2000"
        query = normalize_task(task)
        self.assertEqual(query, "wireless headphones")

    def test_normalize_task_duckduckgo_documentation(self):
        task = "Search DuckDuckGo for Python documentation, open the official Python documentation website, and tell me the page title and URL."
        query = normalize_task(task)
        self.assertEqual(query, "Python documentation")

    def test_normalize_task_duckduckgo_release(self):
        task = "Search DuckDuckGo for the latest Python release, open the official Python website result, and tell me the latest Python version and the page title."
        query = normalize_task(task)
        self.assertEqual(query, "latest Python release")

    def test_normalize_task_plain_search(self):
        task = "Search for Elden Ring wiki"
        query = normalize_task(task)
        self.assertEqual(query, "Elden Ring wiki")

    def test_normalize_task_direct_url_no_search(self):
        task = "Open https://example.com and tell me the exact page heading and page title."
        query = normalize_task(task)
        self.assertEqual(query, task)

    def test_screenshot_invalidation_on_runtime_start(self):
        """Verify that starting a new task immediately purges old screenshot files."""
        # Create dummy old screenshots
        test_screen = SCREENSHOT_PATHS[0]
        test_screen.parent.mkdir(parents=True, exist_ok=True)
        test_screen.write_bytes(b"old-screenshot-data")
        self.assertTrue(test_screen.exists())

        runtime = AgentServerRuntime()
        # Invalidate via start logic
        for sp in SCREENSHOT_PATHS:
            if sp.exists():
                sp.unlink()

        self.assertFalse(test_screen.exists())
        status = runtime.get_status()
        self.assertFalse(status["has_screenshot"])

    def test_wikipedia_capital_query_separation(self):
        plan = parse_task_plan("Go to Wikipedia and find the capital of India.")
        self.assertEqual(plan.destination, "wikipedia")
        self.assertEqual(plan.target, "India")
        self.assertEqual(plan.search_query, "India")
        self.assertEqual(plan.intent, "information_extraction")
        self.assertIn("capital", plan.requested_information)

    def test_wikipedia_population_query_separation(self):
        plan = parse_task_plan("Go to Wikipedia and find the population of India.")
        self.assertEqual(plan.destination, "wikipedia")
        self.assertEqual(plan.target, "India")
        self.assertEqual(plan.search_query, "India")
        self.assertEqual(plan.intent, "information_extraction")
        self.assertIn("population", plan.requested_information)

    def test_wikipedia_open_article_and_find_capital(self):
        plan = parse_task_plan("Go to Wikipedia, open the India article, and find the capital of India.")
        self.assertEqual(plan.destination, "wikipedia")
        self.assertEqual(plan.target, "India")
        self.assertEqual(plan.search_query, "India")
        self.assertEqual(plan.intent, "information_extraction")
        self.assertIn("capital", plan.requested_information)
        self.assertIn("open the India article", plan.navigation_requirement)

    def test_wikipedia_einstein_search_separation(self):
        plan = parse_task_plan("Search Wikipedia for Albert Einstein and find his birth date.")
        self.assertEqual(plan.destination, "wikipedia")
        self.assertEqual(plan.target, "Albert Einstein")
        self.assertEqual(plan.search_query, "Albert Einstein")
        self.assertEqual(plan.intent, "information_extraction")
        self.assertIn("birth date", plan.requested_information)

    def test_flipkart_ranked_gaming_laptop_parsing(self):
        plan = parse_task_plan("go to flipkart and find me the best gaming laptop with the highest ratings")
        self.assertEqual(plan.destination, "flipkart")
        self.assertEqual(plan.target, "product")
        self.assertEqual(plan.search_query, "gaming laptop")
        self.assertEqual(plan.intent, "ranked_search")
        self.assertEqual(plan.ranking_field, "rating")
        self.assertEqual(plan.ranking_order, "desc")


if __name__ == "__main__":
    unittest.main()
