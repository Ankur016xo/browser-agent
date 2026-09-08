"""
Unit tests for the diagnostics module.
"""
import unittest
from browser_agent.diagnostics import check_python_version, check_dependencies, check_port_availability


class TestDiagnostics(unittest.TestCase):

    def test_python_version_check(self):
        ok, msg = check_python_version()
        self.assertTrue(ok)
        self.assertIn("Python", msg)

    def test_dependencies_check(self):
        ok, msgs = check_dependencies()
        self.assertTrue(ok)
        self.assertGreater(len(msgs), 0)

    def test_port_check(self):
        ok, msg = check_port_availability(59999)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
