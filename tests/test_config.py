"""
Tests for configuration loading, validation, and environment variable overrides.
"""
import os
import unittest
from browser_agent.config import load_config, validate_config, _get_env_override, _deep_merge


class TestConfig(unittest.TestCase):

    def test_default_config_structure(self):
        config = load_config()
        self.assertIn("ollama", config)
        self.assertIn("browser", config)
        self.assertIn("agent", config)
        self.assertIn("logging", config)
        self.assertEqual(config["ollama"]["model"], "qwen2.5vl:3b")

    def test_validation_passes_valid_config(self):
        config = load_config()
        validated = validate_config(config)
        self.assertEqual(validated, config)

    def test_validation_fails_invalid_url(self):
        config = load_config()
        config["ollama"]["url"] = "not-a-url"
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_deep_merge(self):
        base = {"a": 1, "nested": {"x": 10, "y": 20}}
        override = {"nested": {"y": 99, "z": 30}, "b": 2}
        merged = _deep_merge(base, override)
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["b"], 2)
        self.assertEqual(merged["nested"]["x"], 10)
        self.assertEqual(merged["nested"]["y"], 99)
        self.assertEqual(merged["nested"]["z"], 30)

    def test_env_override(self):
        os.environ["BROWSER_AGENT_AGENT_MAX_STEPS"] = "25"
        val = _get_env_override("agent.max_steps")
        self.assertEqual(val, 25)
        del os.environ["BROWSER_AGENT_AGENT_MAX_STEPS"]


if __name__ == "__main__":
    unittest.main()
