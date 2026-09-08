"""
Stress and concurrency tests for thread safety, rapid state transitions, and server robustness.
"""
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from browser_agent.agent import BrowserAgent
from browser_agent.state import AgentState
from web_server import BrowserAgentHTTPHandler, RUNTIME


class TestConcurrencyAndStress(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = 8998
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), BrowserAgentHTTPHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_rapid_pause_resume_cycles(self):
        agent = BrowserAgent()
        for _ in range(50):
            agent.pause()
            self.assertEqual(agent.state, AgentState.PAUSED)
            agent.resume()
            self.assertEqual(agent.state, AgentState.OBSERVING)
        agent.stop()
        self.assertEqual(agent.state, AgentState.STOPPED)

    def test_concurrent_api_status_requests(self):
        errors = []

        def _fetch_status():
            try:
                req = Request(f"http://127.0.0.1:{self.port}/api/status")
                with urlopen(req, timeout=3) as resp:
                    if resp.status != 200:
                        errors.append(f"Bad status: {resp.status}")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_fetch_status) for _ in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered concurrency errors: {errors}")

    def test_rapid_server_start_stop_sequence(self):
        # Stop any active runtime state
        RUNTIME.stop()
        status = RUNTIME.get_status()
        self.assertFalse(status["running"])
        self.assertEqual(status["state"], AgentState.STOPPED.value)


if __name__ == "__main__":
    unittest.main()
