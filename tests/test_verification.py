"""
Tests for the ActionVerifier and pre/post action state diffing.
"""
import unittest
from playwright.sync_api import sync_playwright
from browser_agent.verifier import ActionVerifier


class TestVerification(unittest.TestCase):

    def setUp(self):
        self.verifier = ActionVerifier()

    def test_verify_typing_action(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("""
            <html>
            <body>
                <input id="q" type="text" />
            </body>
            </html>
            """)

            action = {"action": "type", "text": "Testing Verification"}
            pre_state = self.verifier.capture_pre_action_state(page, action)

            # Perform typing
            page.locator("#q").fill("Testing Verification")

            ver_result = self.verifier.verify_action(page, action, pre_state, execution_success=True)
            self.assertTrue(ver_result.verified)
            self.assertTrue(ver_result.state_changed)

            browser.close()

    def test_verify_failed_click_no_change(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><p>Static text</p></body></html>")

            action = {"action": "click", "target": "NonExistent"}
            pre_state = self.verifier.capture_pre_action_state(page, action)

            ver_result = self.verifier.verify_action(page, action, pre_state, execution_success=False)
            self.assertFalse(ver_result.verified)
            self.assertFalse(ver_result.state_changed)

            browser.close()


if __name__ == "__main__":
    unittest.main()
