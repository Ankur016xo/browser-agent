"""
Tests for LoopDetector and repetition recovery.
"""
import unittest
from browser_agent.loop_detector import LoopDetector
from browser_agent.state import ActionRecord, AgentMemory


class TestLoopDetector(unittest.TestCase):

    def setUp(self):
        self.detector = LoopDetector(max_identical_actions=2, max_consecutive_failures=3)

    def test_detects_repeated_failed_action(self):
        memory = AgentMemory()
        action = {"action": "click", "target": "Search Button"}

        # First failure
        rec1 = ActionRecord(step=1, action=action, success=False, verified=False, state_change=False)
        memory.add_action(rec1)

        is_loop, _ = self.detector.check_loop(memory, action)
        self.assertFalse(is_loop)  # First attempt, count = 1

        # Second failure of same action
        rec2 = ActionRecord(step=2, action=action, success=False, verified=False, state_change=False)
        memory.add_action(rec2)

        is_loop, advice = self.detector.check_loop(memory, action)
        self.assertTrue(is_loop)
        self.assertIn("has already been attempted", advice)

    def test_detects_consecutive_failures(self):
        memory = AgentMemory()
        for i in range(3):
            rec = ActionRecord(step=i+1, action={"action": f"act_{i}"}, success=False, verified=False, state_change=False)
            memory.add_action(rec)

        is_loop, advice = self.detector.check_loop(memory, {"action": "new_action"})
        self.assertTrue(is_loop)
        self.assertIn("consecutive", advice.lower())


if __name__ == "__main__":
    unittest.main()
