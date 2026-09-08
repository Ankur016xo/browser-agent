"""
Integration test for BrowserAgent loop, callbacks, verification, and state transitions.
"""
import unittest
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from browser_agent.agent import BrowserAgent
from browser_agent.state import AgentState, ActionRecord


class TestAgentFlow(unittest.TestCase):

    def test_agent_initialization_and_configuration(self):
        agent = BrowserAgent()
        self.assertEqual(agent.state, AgentState.IDLE)
        self.assertIsNotNone(agent.perception)
        self.assertIsNotNone(agent.verifier)
        self.assertIsNotNone(agent.loop_detector)

    @patch("browser_agent.agent.ask_vision_model")
    @patch("browser_agent.agent.verify_task_completion")
    def test_mocked_end_to_end_agent_flow(self, mock_verify, mock_ask_vision):
        mock_ask_vision.side_effect = [
            {"action": "type", "element_id": 1, "text": "Python", "reasoning": "Entering search term", "confidence": 0.95},
            {"action": "done", "reasoning": "Search submitted and completed", "confidence": 0.99},
        ]
        mock_verify.return_value = {"verified": True, "reason": "Task completed successfully"}

        states_observed = []
        actions_observed = []

        agent = BrowserAgent(
            config={
                "browser": {
                    "headless": True,
                    "viewport_width": 1024,
                    "viewport_height": 768,
                    "start_url": "about:blank",
                    "page_load_timeout": 500,
                    "step_wait_timeout": 200,
                },
                "agent": {
                    "max_steps": 5,
                    "screenshot_path": "test_agent_screen.png",
                    "screenshot_quality": 80,
                },
                "ollama": {
                    "url": "http://localhost:11434",
                    "model": "qwen2.5vl:3b",
                    "timeout": 30.0,
                },
                "logging": {
                    "level": "INFO",
                    "format": "%(message)s",
                }
            },
            on_state_change=lambda s: states_observed.append(s),
            on_action=lambda r: actions_observed.append(r),
        )

        result = agent.run("Search for Python")

        self.assertTrue(result.get("success"))
        self.assertIn(AgentState.INITIALIZING, states_observed)
        self.assertIn(AgentState.OBSERVING, states_observed)
        self.assertIn(AgentState.PERCEIVING, states_observed)
        self.assertIn(AgentState.THINKING, states_observed)
        self.assertIn(AgentState.ACTING, states_observed)
        self.assertIn(AgentState.COMPLETED, states_observed)
        self.assertGreater(len(actions_observed), 0)


if __name__ == "__main__":
    unittest.main()
