"""
Unit tests for robust Vision-Language Model JSON parsing and repair.
"""
import unittest

from browser_agent.vision import clean_json


class TestVisionJsonParsing(unittest.TestCase):
    """Test clean_json handling of diverse model response formats."""

    def test_clean_json_standard(self):
        raw = '{"action": "click", "element_id": 3, "confidence": 0.95, "reasoning": "Click search"}'
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "click")
        self.assertEqual(parsed.get("element_id"), 3)

    def test_clean_json_markdown_fence(self):
        raw = '```json\n{"action": "type", "element_id": 1, "text": "laptop bag", "confidence": 0.9}\n```'
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "type")
        self.assertEqual(parsed.get("text"), "laptop bag")

    def test_clean_json_surrounding_conversational_text(self):
        raw = 'Here is the next action to perform:\n{"action": "scroll", "direction": "down", "amount": 500}\nHope this helps!'
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "scroll")
        self.assertEqual(parsed.get("direction"), "down")

    def test_clean_json_trailing_commas(self):
        raw = '{"action": "click", "element_id": 4, "confidence": 0.9,}'
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "click")
        self.assertEqual(parsed.get("element_id"), 4)

    def test_clean_json_single_quotes(self):
        raw = "{'action': 'done', 'confidence': 0.98, 'reasoning': 'Task finished'}"
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "done")
        self.assertEqual(parsed.get("reasoning"), "Task finished")

    def test_clean_json_unquoted_keys(self):
        raw = '{action: "click", element_id: 2, confidence: 0.9}'
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "click")
        self.assertEqual(parsed.get("element_id"), 2)

    def test_clean_json_plain_text_done_fallback(self):
        raw = "I have extracted the requested information and the task is now complete."
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "done")

    def test_clean_json_plain_text_click_fallback(self):
        raw = "Click element 5 to open the product."
        parsed = clean_json(raw)
        self.assertEqual(parsed.get("action"), "click")
        self.assertEqual(parsed.get("element_id"), 5)

    def test_clean_json_empty_or_gibberish_raises(self):
        with self.assertRaises(ValueError):
            clean_json("")
        with self.assertRaises(ValueError):
            clean_json("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")


if __name__ == "__main__":
    unittest.main()
