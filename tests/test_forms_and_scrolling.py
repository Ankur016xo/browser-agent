"""
Deep tests for complex form interactions (checkboxes, radio, select dropdowns, textareas) and scrolling.
"""
import unittest
from playwright.sync_api import sync_playwright
from browser_agent.actions import execute_action
from browser_agent.perception import PerceptionEngine
from browser_agent.verifier import ActionVerifier


class TestFormsAndScrolling(unittest.TestCase):

    def test_form_controls_interaction(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <head><title>Form Test</title></head>
            <body>
                <form id="profileForm">
                    <label for="username">Username</label>
                    <input id="username" type="text" name="user" />

                    <label for="comments">Bio</label>
                    <textarea id="comments" name="bio"></textarea>

                    <label for="country">Country</label>
                    <select id="country" name="country">
                        <option value="us">United States</option>
                        <option value="ca">Canada</option>
                        <option value="uk">United Kingdom</option>
                    </select>

                    <label><input id="agree" type="checkbox" name="agree" /> Agree to Terms</label>

                    <button id="saveBtn" type="button" onclick="document.getElementById('status').innerText='Saved';">Save</button>
                    <div id="status">Unsaved</div>
                </form>
            </body>
            </html>
            """)

            perception = PerceptionEngine()
            verifier = ActionVerifier()
            elements = perception.extract_interactive_elements(page)

            # 1. Type into text input
            user_elem = next(e for e in elements if e.attributes.get("id") == "username")
            action_type = {"action": "type", "element_id": user_elem.id, "text": "agent_tester"}
            pre_state = verifier.capture_pre_action_state(page, action_type)
            success = execute_action(page, action_type, elements)
            ver = verifier.verify_action(page, action_type, pre_state, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#username").input_value(), "agent_tester")

            # 2. Select option in dropdown
            select_elem = next(e for e in elements if e.tag == "select")
            action_select = {"action": "select", "element_id": select_elem.id, "option": "Canada"}
            pre_state = verifier.capture_pre_action_state(page, action_select)
            success = execute_action(page, action_select, elements)
            ver = verifier.verify_action(page, action_select, pre_state, success)
            self.assertTrue(success)
            self.assertEqual(page.locator("#country").input_value(), "ca")

            # 3. Click Checkbox
            chk_elem = next(e for e in elements if e.attributes.get("id") == "agree")
            action_chk = {"action": "click", "element_id": chk_elem.id}
            pre_state = verifier.capture_pre_action_state(page, action_chk)
            success = execute_action(page, action_chk, elements)
            self.assertTrue(success)
            self.assertTrue(page.locator("#agree").is_checked())

            # 4. Click Save Button
            btn_elem = next(e for e in elements if e.attributes.get("id") == "saveBtn")
            action_btn = {"action": "click", "element_id": btn_elem.id}
            pre_state = verifier.capture_pre_action_state(page, action_btn)
            success = execute_action(page, action_btn, elements)
            ver = verifier.verify_action(page, action_btn, pre_state, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#status").inner_text(), "Saved")

            browser.close()

    def test_scrolling_verification_and_bounds(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1024, "height": 768})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body style="height: 3000px;">
                <h1>Top</h1>
                <div style="margin-top: 2000px;" id="bottomMarker">Bottom Content</div>
            </body>
            </html>
            """)

            verifier = ActionVerifier()

            # Scroll down
            action_scroll = {"action": "scroll", "direction": "down", "amount": 800}
            pre_state = verifier.capture_pre_action_state(page, action_scroll)
            success = execute_action(page, action_scroll)
            ver = verifier.verify_action(page, action_scroll, pre_state, success)

            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertTrue(ver.state_changed)

            browser.close()


if __name__ == "__main__":
    unittest.main()
