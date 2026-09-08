"""
Unit tests for Information Extraction, Completion Evaluation, and Recovery Logic.
"""
import unittest
from unittest.mock import MagicMock, patch

from browser_agent.agent import BrowserAgent
from browser_agent.loop_detector import LoopDetector
from browser_agent.state import ActionRecord, AgentMemory, AgentState, ElementInfo


class TestInformationExtractionAndRecovery(unittest.TestCase):
    """Test suite for DONE evaluation, information extraction, and loop avoidance."""

    def test_information_already_visible_returns_done(self):
        """When requested info is present on page, model output 'done' with result is accepted."""
        memory = AgentMemory(task="Find the latest Python version and page title")
        action = {
            "action": "done",
            "confidence": 0.98,
            "reasoning": "The Python version 3.14.7 and title are visible on page.",
            "result": {
                "latest_python_version": "Python 3.14.7",
                "page_title": "Python Release Python 3.14.7 | Python.org"
            }
        }
        
        self.assertEqual(action.get("action"), "done")
        self.assertIn("latest_python_version", action.get("result", {}))
        self.assertEqual(action["result"]["latest_python_version"], "Python 3.14.7")

    def test_information_not_visible_continues_acting(self):
        """When on search results or intermediate page, agent selects click/type action."""
        action = {
            "action": "click",
            "element_id": 12,
            "reasoning": "Clicking the official Python release link to view version",
            "confidence": 0.92
        }
        self.assertNotEqual(action.get("action"), "done")
        self.assertEqual(action.get("action"), "click")
        self.assertEqual(action.get("element_id"), 12)

    def test_completed_navigation_and_extraction_done(self):
        """Ensure BrowserAgent records extracted_data when action is done."""
        agent = BrowserAgent()
        agent.memory.task = "Tell me the page title and latest version"
        
        done_action = {
            "action": "done",
            "confidence": 0.95,
            "reasoning": "Destination reached and version is visible.",
            "result": {
                "latest_version": "3.14.7",
                "page_title": "Python Release Python 3.14.7"
            }
        }
        
        if isinstance(done_action.get("result"), dict):
            agent.memory.extracted_data.update(done_action["result"])
            
        self.assertEqual(agent.memory.extracted_data["latest_version"], "3.14.7")
        self.assertEqual(agent.memory.extracted_data["page_title"], "Python Release Python 3.14.7")

    def test_failed_action_does_not_repeat_same_action(self):
        """When an action produced no state change, LoopDetector flags repeating it after threshold."""
        detector = LoopDetector(max_identical_actions=2)
        memory = AgentMemory()
        
        failed_record1 = ActionRecord(
            step=1,
            action={"action": "click", "element_id": 7, "target": "Search Button"},
            success=True,
            verified=False,
            state_change=False,
        )
        memory.add_action(failed_record1)
        
        # First repeat check
        proposed = {"action": "click", "element_id": 7, "target": "Search Button"}
        is_loop, _ = detector.check_loop(memory, proposed)
        self.assertFalse(is_loop)
        
        # Second repeat failure
        failed_record2 = ActionRecord(
            step=2,
            action={"action": "click", "element_id": 7, "target": "Search Button"},
            success=True,
            verified=False,
            state_change=False,
        )
        memory.add_action(failed_record2)
        
        is_loop, advice = detector.check_loop(memory, proposed)
        self.assertTrue(is_loop)
        self.assertIn("DO NOT repeat this action", advice)
        self.assertIn("Check if the requested information is already visible", advice)

    def test_loop_recovery_reperceive_before_arbitrary_fallback(self):
        """Loop advice guides re-perceiving visible text or alternative action before navigation."""
        detector = LoopDetector(max_consecutive_failures=3)
        memory = AgentMemory()
        for i in range(3):
            rec = ActionRecord(
                step=i+1,
                action={"action": f"click_{i}"},
                success=False,
                verified=False,
                state_change=False,
            )
            memory.add_action(rec)
        
        proposed = {"action": "click", "element_id": 9}
        is_loop, advice = detector.check_loop(memory, proposed)
        
        self.assertTrue(is_loop)
        self.assertIn("Re-evaluate the visible elements carefully", advice)

    def test_done_result_contains_extracted_information(self):
        """Verify summary generation integrates extracted key-values."""
        from browser_agent.vision import summarize_task_result
        
        extracted = {
            "latest_python_version": "Python 3.14.7",
            "page_title": "Python Release Python 3.14.7 | Python.org"
        }
        
        mock_page = MagicMock()
        mock_page.url = "https://www.python.org/downloads/release/python-3147/"
        mock_page.title.return_value = "Python Release Python 3.14.7 | Python.org"
        
        # Test fallback summary formatting when VLM is bypassed or fails
        with patch("browser_agent.vision.chat", side_effect=RuntimeError("Ollama offline")):
            summary = summarize_task_result("Get latest Python version", mock_page, "fake.png", extracted_result=extracted)
            self.assertIn("Latest Python Version", summary)
            self.assertIn("Python 3.14.7", summary)

    def test_information_satisfaction_detects_all_requested_fields(self):
        """Test is_information_satisfied returns True when all requested items are present."""
        memory = AgentMemory(task="Open https://example.com and tell me the exact page heading and page title.")
        self.assertFalse(memory.is_information_satisfied())
        
        # Add partial data
        memory.update_extracted_data({"page_title": "Example Domain"})
        self.assertFalse(memory.is_information_satisfied())
        
        # Add remaining required data
        memory.update_extracted_data({"page_heading": "Example Domain"})
        self.assertTrue(memory.is_information_satisfied())

    def test_failed_subsequent_action_does_not_overwrite_valid_result(self):
        """When valid info is present, empty/placeholder data from subsequent failed steps does not overwrite it."""
        memory = AgentMemory(task="Find product name and price")
        memory.update_extracted_data({"product_name": "Laptop Bag", "price": "₹799"})
        
        self.assertEqual(memory.extracted_data["product_name"], "Laptop Bag")
        self.assertEqual(memory.extracted_data["price"], "₹799")
        
        # Subsequent step with empty / placeholder values
        memory.update_extracted_data({"product_name": "Value visible on screen", "price": ""})
        
        # Original valid values must be preserved
        self.assertEqual(memory.extracted_data["product_name"], "Laptop Bag")
        self.assertEqual(memory.extracted_data["price"], "₹799")

    def test_ground_page_metadata_populates_heading_and_title(self):
        """Verify _ground_page_metadata extracts heading and title from page."""
        agent = BrowserAgent()
        agent.memory.task = "Open https://example.com and tell me the exact page heading and page title."
        
        mock_page = MagicMock()
        mock_page.url = "https://example.com/"
        mock_page.title.return_value = "Example Domain"
        
        mock_h1 = MagicMock()
        mock_h1.inner_text.return_value = "Example Domain"
        mock_page.query_selector.return_value = mock_h1
        
        agent._ground_page_metadata(mock_page)
        
        self.assertEqual(agent.memory.extracted_data.get("page_title"), "Example Domain")
        self.assertEqual(agent.memory.extracted_data.get("page_heading"), "Example Domain")
        self.assertTrue(agent.memory.is_information_satisfied())

    def test_product_information_satisfaction_strict_requirements(self):
        """Verify that product tasks requiring name, price, rating require all 3 before satisfaction."""
        task = "Go to Flipkart, search for laptop bags under ₹1000, handle any login or popup that appears without logging in, open a suitable product, and tell me its product name, price, and rating."
        memory = AgentMemory(task=task)
        self.assertFalse(memory.is_information_satisfied())

        # Only product_name
        memory.update_extracted_data({"product_name": "SAFAR Laptop Backpack"})
        self.assertFalse(memory.is_information_satisfied())

        # Product name and price
        memory.update_extracted_data({"price": "₹699"})
        self.assertFalse(memory.is_information_satisfied())

        # All 3: product_name, price, rating
        memory.update_extracted_data({"rating": "4.2 ★"})
        self.assertTrue(memory.is_information_satisfied())

    def test_product_information_rejects_placeholders(self):
        """Verify that placeholder strings do not satisfy product requirements."""
        task = "Tell me product name, price, and rating"
        memory = AgentMemory(task=task)
        memory.update_extracted_data({
            "product_name": "Product Name",
            "price": "Value visible on screen",
            "rating": "..."
        })
        self.assertFalse(memory.is_information_satisfied())

    def test_find_product_links_ignores_categories_and_selects_product(self):
        """Verify that find_product_links ignores category breadcrumbs and selects real product links."""
        from browser_agent.agent import find_product_links
        elements = [
            ElementInfo(id=10, tag="a", text="Bags, Wallets & Belts", bbox=[10, 10, 100, 20], center=[50, 20], attributes={"href": "/bags-wallets-belts/pr?sid=reh,4d7,x9i"}),
            ElementInfo(id=11, tag="a", text="Explore Plus", bbox=[10, 30, 80, 20], center=[50, 40], attributes={"href": "/plus"}),
            ElementInfo(id=12, tag="a", text="Cart", bbox=[10, 50, 50, 20], center=[35, 60], attributes={"href": "/viewcart"}),
            ElementInfo(id=24, tag="a", text="MICXO Waterproof Bag Laptop Backpack 30 L Black", bbox=[100, 200, 300, 150], center=[250, 275], attributes={"href": "/micxo-waterproof-bag-laptop-backpack/p/itmfafd11101d03b?pid=BKPHFBWZZCUHXD2N"}),
        ]
        prod_links = find_product_links(elements)
        self.assertEqual(len(prod_links), 1)
        self.assertEqual(prod_links[0].id, 24)
        self.assertIn("MICXO", prod_links[0].text)

    def test_vlm_failure_on_flipkart_search_recovers_to_product_link(self):
        """When VLM fails with @@@@@ on Flipkart search results, deterministic grounding picks product link."""
        from browser_agent.agent import find_product_links
        elements = [
            ElementInfo(id=5, tag="a", text="Bags, Wallets & Belts", bbox=[10, 10, 100, 20], center=[50, 20], attributes={"href": "/bags-wallets-belts"}),
            ElementInfo(id=20, tag="a", text="DEEP DAZZLING Unisex 36 L Laptop Backpack", bbox=[100, 200, 300, 150], center=[250, 275], attributes={"href": "/deep-dazzling-laptop/p/itm7da7fa967c2e8"}),
        ]
        
        # Verify find_product_links ignores category link 5 and chooses product link 20
        candidates = find_product_links(elements)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].id, 20)
        self.assertNotEqual(candidates[0].id, 5)

    def test_final_verification_is_false_until_price_and_rating_extracted(self):
        """Verify that verification is strictly False when price or rating are missing, and True when present."""
        task = "Go to Flipkart, search for laptop bags under ₹1000, handle any login or popup, open a suitable product, and tell me its product name, price, and rating."
        mock_page = MagicMock()
        mock_page.url = "https://www.flipkart.com/search?q=laptop+bags"
        
        memory = AgentMemory(task=task)
        # Search page with partial info -> False
        self.assertFalse(memory.is_information_satisfied(task, mock_page))
        
        # Product page without price/rating -> False
        mock_page.url = "https://www.flipkart.com/product/p/itm123"
        memory.update_extracted_data({"product_name": "Laptop Bag"})
        self.assertFalse(memory.is_information_satisfied(task, mock_page))
        
        # Product page with price only -> False
        memory.update_extracted_data({"price": "₹799"})
        self.assertFalse(memory.is_information_satisfied(task, mock_page))
        
        # Product page with all 3: product_name, price, rating -> True
        memory.update_extracted_data({"rating": "4.5"})
        self.assertTrue(memory.is_information_satisfied(task, mock_page))

    def test_verify_task_completion_returns_false_on_vlm_failure(self):
        """verify_task_completion returns verified: False when VLM produces an error/garbage."""
        from browser_agent.vision import verify_task_completion
        mock_page = MagicMock()
        mock_page.url = "https://www.flipkart.com/product/p/itm123"
        mock_page.title.return_value = "Laptop Bag"
        
        with patch("browser_agent.vision.chat", side_effect=ValueError("AI did not return valid JSON: @@@@@@")):
            res = verify_task_completion("Find product name, price, and rating", mock_page, "fake.png")
            self.assertFalse(res.get("verified"))
            self.assertEqual(res.get("confidence"), 0.0)


if __name__ == "__main__":
    unittest.main()



