"""
Tests for state transitions, memory management, and Pause/Resume/Stop controls.
"""
import unittest
from browser_agent.agent import BrowserAgent, normalize_task
from browser_agent.state import AgentState


class TestStateAndControls(unittest.TestCase):

    def test_task_normalization(self):
        self.assertEqual(normalize_task("Search DuckDuckGo for Python"), "Python")
        self.assertEqual(normalize_task("Search Google for Galgotias University"), "Galgotias University")
        self.assertEqual(normalize_task("Open https://example.com"), "Open https://example.com")
        self.assertEqual(normalize_task("look up latest news"), "latest news")

    def test_pause_resume_stop_events(self):
        state_history = []

        def on_state(state):
            state_history.append(state)

        agent = BrowserAgent(on_state_change=on_state)
        self.assertEqual(agent.state, AgentState.IDLE)

        # Test Pause
        agent.pause()
        self.assertEqual(agent.state, AgentState.PAUSED)
        self.assertIn(AgentState.PAUSED, state_history)

        # Test Resume
        agent.resume()
        self.assertEqual(agent.state, AgentState.OBSERVING)

        # Test Stop
        agent.stop()
        self.assertEqual(agent.state, AgentState.STOPPED)


if __name__ == "__main__":
    unittest.main()
