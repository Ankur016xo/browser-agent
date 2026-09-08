"""
Integration tests proving the CAPTCHA false-success bug is impossible.
Enforces that deterministic ExecutionState blockers strictly override any positive VLM verification.
"""
import unittest
from unittest.mock import patch, MagicMock
from playwright.sync_api import sync_playwright

from browser_agent.agent import BrowserAgent
from browser_agent.state import AgentState


class TestBlockerAndAuthoritativeVerification(unittest.TestCase):

    @patch("browser_agent.agent.take_screenshot")
    @patch("browser_agent.agent.verify_task_completion")
    @patch("browser_agent.agent.ask_vision_model")
    def test_captcha_false_success_impossible(self, mock_ask_vlm, mock_verify_completion, mock_screenshot):
        """Simulate browser reaching CAPTCHA while VLM claims verified=True.
        Authoritative final state MUST be BLOCKED, not SUCCESS.
        """
        mock_ask_vlm.return_value = {"action": "done", "reasoning": "I think it's done"}
        mock_verify_completion.return_value = {
            "verified": True,
            "reason": "VLM hallucination: task looks totally complete and successful!",
            "confidence": 0.99,
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("""
            <html>
                <body>
                    <h1>Security Check</h1>
                    <p>Please enter the characters you see below to prove you are a human</p>
                    <input type="text" id="captcha_input" />
                </body>
            </html>
            """)

            agent = BrowserAgent(config={
                "browser": {"headless": True, "start_url": "about:blank"},
                "agent": {"max_steps": 2}
            })

            # Mock controller to use our prepared page
            agent.controller.launch = MagicMock(return_value=page)
            agent.controller.get_active_page = MagicMock(return_value=page)

            result = agent.run("Search for laptop deals")

            self.assertFalse(result["success"], "Agent must NOT succeed when CAPTCHA is present")
            self.assertEqual(result["state"], "BLOCKED", f"Expected BLOCKED but got {result['state']}")
            self.assertFalse(result["verified"])
            self.assertIn("captcha", result["summary"].lower() or result["state"].lower())
            browser.close()

    @patch("browser_agent.agent.take_screenshot")
    @patch("browser_agent.agent.verify_task_completion")
    @patch("browser_agent.agent.ask_vision_model")
    def test_auth_barrier_blocks_success(self, mock_ask_vlm, mock_verify_completion, mock_screenshot):
        """Simulate auth wall while VLM claims verified=True."""
        mock_ask_vlm.return_value = {"action": "done"}
        mock_verify_completion.return_value = {"verified": True, "reason": "Looks good!"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("""
            <html>
                <body>
                    <h2>Access Denied</h2>
                    <p>Sign in to continue to your dashboard</p>
                </body>
            </html>
            """)

            agent = BrowserAgent(config={"agent": {"max_steps": 2}})
            agent.controller.launch = MagicMock(return_value=page)
            agent.controller.get_active_page = MagicMock(return_value=page)

            result = agent.run("Go to dashboard")
            self.assertFalse(result["success"])
            self.assertEqual(result["state"], "BLOCKED")
            browser.close()

    @patch("browser_agent.agent.take_screenshot")
    @patch("browser_agent.agent.verify_task_completion")
    @patch("browser_agent.agent.ask_vision_model")
    def test_rate_limit_blocks_success(self, mock_ask_vlm, mock_verify_completion, mock_screenshot):
        """Simulate 429 Too Many Requests while VLM claims verified=True."""
        mock_ask_vlm.return_value = {"action": "done"}
        mock_verify_completion.return_value = {"verified": True, "reason": "Looks good!"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><h1>429 Too Many Requests</h1><p>Rate limit exceeded</p></body></html>")

            agent = BrowserAgent(config={"agent": {"max_steps": 2}})
            agent.controller.launch = MagicMock(return_value=page)
            agent.controller.get_active_page = MagicMock(return_value=page)

            result = agent.run("Search something")
            self.assertFalse(result["success"])
            self.assertEqual(result["state"], "BLOCKED")
            browser.close()

    @patch("browser_agent.agent.take_screenshot")
    @patch("browser_agent.agent.verify_task_completion")
    @patch("browser_agent.agent.ask_vision_model")
    def test_explicit_failure_overrides_vlm(self, mock_ask_vlm, mock_verify_completion, mock_screenshot):
        """Simulate execution failure while VLM claims verified=True."""
        mock_verify_completion.return_value = {"verified": True, "reason": "Looks good!"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><p>Normal Page</p></body></html>")

            agent = BrowserAgent(config={"agent": {"max_steps": 2}})
            agent.controller.launch = MagicMock(return_value=page)
            agent.controller.get_active_page = MagicMock(return_value=page)

            def set_failed(*args, **kwargs):
                if agent.execution_state:
                    agent.execution_state.execution_failed = True
                    agent.execution_state.failure_reason = "Browser crashed mid-run"
                return {"action": "done"}

            mock_ask_vlm.side_effect = set_failed

            result = agent.run("test task")
            # When execution_state has execution_failed=True, it cannot be SUCCESS
            self.assertFalse(result["success"])
            self.assertEqual(result["state"], "FAILED")
            browser.close()

    @patch("browser_agent.agent.take_screenshot")
    @patch("browser_agent.agent.verify_task_completion")
    @patch("browser_agent.agent.ask_vision_model")
    def test_incomplete_exploration_overrides_vlm(self, mock_ask_vlm, mock_verify_completion, mock_screenshot):
        """Simulate only 1 candidate found when 3 are required, while VLM claims verified=True."""
        mock_ask_vlm.return_value = {"action": "done"}
        mock_verify_completion.return_value = {"verified": True, "reason": "VLM claims complete!"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><p>Listing</p></body></html>")

            agent = BrowserAgent(config={"agent": {"max_steps": 2}})
            agent.controller.launch = MagicMock(return_value=page)
            agent.controller.get_active_page = MagicMock(return_value=page)

            result = agent.run("Find three laptops under 50000")
            # 3 were requested, none/few valid found -> must be INCOMPLETE, not SUCCESS
            self.assertFalse(result["success"])
            self.assertEqual(result["state"], "INCOMPLETE")
            browser.close()


if __name__ == "__main__":
    unittest.main()

