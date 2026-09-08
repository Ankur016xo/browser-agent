"""
Tests for the Web Server HTTP REST endpoints and state reporting.
"""
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from browser_agent.state import AgentState
from web_server import BrowserAgentHTTPHandler, RUNTIME


class TestWebServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = 8999
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), BrowserAgentHTTPHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_status_endpoint_returns_json(self):
        req = Request(f"http://127.0.0.1:{self.port}/api/status")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("state", data)
            self.assertIn("running", data)
            self.assertIn("paused", data)
            self.assertIn("logs", data)

    def test_start_endpoint_validation(self):
        # Empty task should return 400
        req = Request(
            f"http://127.0.0.1:{self.port}/api/start",
            data=json.dumps({"task": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req) as resp:
                self.assertEqual(resp.status, 400)
        except Exception as exc:
            self.assertTrue("400" in str(exc) or hasattr(exc, "code") and exc.code == 400)

    def test_pause_resume_stop_endpoints(self):
        # Test Pause
        req = Request(
            f"http://127.0.0.1:{self.port}/api/pause",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

        # Test Resume
        req = Request(
            f"http://127.0.0.1:{self.port}/api/resume",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

        # Test Stop
        req = Request(
            f"http://127.0.0.1:{self.port}/api/stop",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("state"), AgentState.STOPPED.value)


    def test_root_serves_vision_lite_html(self):
        # Root path "/" should serve vision-lite index.html
        req = Request(f"http://127.0.0.1:{self.port}/")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            content = resp.read().decode("utf-8")
            self.assertIn("vision lite", content.lower())
            self.assertIn('id="root"', content)

        # Explicit "/index.html" should also serve index.html
        req_index = Request(f"http://127.0.0.1:{self.port}/index.html")
        with urlopen(req_index) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_task_state_endpoint(self):
        # GET /api/task/state should return structured AgentState
        req = Request(f"http://127.0.0.1:{self.port}/api/task/state")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("status", data)
            self.assertIn("step", data)
            self.assertIn("maxSteps", data)
            self.assertIn("procedures", data)
            self.assertIn("advanced", data)
            self.assertIn("logs", data)

    def test_static_assets_served(self):
        # Read index.html to find asset filenames
        req_root = Request(f"http://127.0.0.1:{self.port}/")
        with urlopen(req_root) as resp:
            html = resp.read().decode("utf-8")

        import re
        asset_matches = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        self.assertTrue(len(asset_matches) > 0, "Should find compiled assets in index.html")

        for asset_url in asset_matches:
            req_asset = Request(f"http://127.0.0.1:{self.port}{asset_url}")
            with urlopen(req_asset) as resp:
                self.assertEqual(resp.status, 200)
                ct = resp.headers.get("Content-Type", "")
                if asset_url.endswith(".js"):
                    self.assertIn("javascript", ct)
                elif asset_url.endswith(".css"):
                    self.assertIn("css", ct)

    def test_screenshot_fallback(self):
        # Empty /api/screenshot should return 200 with SVG placeholder or live PNG
        req = Request(f"http://127.0.0.1:{self.port}/api/screenshot")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            ct = resp.headers.get("Content-Type", "")
            self.assertTrue("image/svg+xml" in ct or "image/png" in ct)

    def test_task_prefixed_endpoints(self):
        # Test task-prefixed pause/resume/stop
        req_pause = Request(
            f"http://127.0.0.1:{self.port}/api/task/pause",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_pause) as resp:
            self.assertEqual(resp.status, 200)

        req_resume = Request(
            f"http://127.0.0.1:{self.port}/api/task/resume",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_resume) as resp:
            self.assertEqual(resp.status, 200)

        req_stop = Request(
            f"http://127.0.0.1:{self.port}/api/task/stop",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_stop) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("state"), AgentState.STOPPED.value)


if __name__ == "__main__":
    unittest.main()

