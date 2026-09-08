"""
Tests for action execution, safety checks, and grounding.
"""
import unittest
from playwright.sync_api import sync_playwright
from browser_agent.actions import check_action_safety, execute_action
from browser_agent.state import ElementInfo


class TestActions(unittest.TestCase):

    def test_safety_check_blocks_sensitive_keywords(self):
        unsafe_action = {"action": "type", "text": "my credit card is 1234"}
        is_safe, msg = check_action_safety(unsafe_action, "https://example.com")
        self.assertFalse(is_safe)
        self.assertIn("credit card", msg)

        safe_action = {"action": "type", "text": "Python tutorial"}
        is_safe, msg = check_action_safety(safe_action, "https://example.com")
        self.assertTrue(is_safe)

    def test_browser_action_execution_on_local_page(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Action Test Page</h1>
                <input id="myInput" type="text" placeholder="Type here" />
                <button id="myBtn" onclick="document.getElementById('result').innerText='Clicked!';">Click Me</button>
                <div id="result">Initial</div>
            </body>
            </html>
            """)

            from browser_agent.perception import PerceptionEngine
            perception = PerceptionEngine()
            elements = perception.extract_interactive_elements(page)

            # Test TYPE by element ID
            input_elem = next(e for e in elements if e.tag == "input")
            type_success = execute_action(page, {"action": "type", "element_id": input_elem.id, "text": "Hello World"}, elements)
            self.assertTrue(type_success)
            self.assertEqual(page.locator("#myInput").input_value(), "Hello World")

            # Test CLICK by element ID
            btn_elem = next(e for e in elements if e.tag == "button")
            click_success = execute_action(page, {"action": "click", "element_id": btn_elem.id}, elements)
            self.assertTrue(click_success)
            self.assertEqual(page.locator("#result").inner_text(), "Clicked!")

            # Test SCROLL
            scroll_success = execute_action(page, {"action": "scroll", "direction": "down", "amount": 200})
            self.assertTrue(scroll_success)

            browser.close()


if __name__ == "__main__":
    unittest.main()
