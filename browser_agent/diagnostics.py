"""
System diagnostics and self-test utility for Browser Agent.
"""
import sys
import socket
import logging
from pathlib import Path
import urllib.request
import json
from browser_agent.config import get_config

# Ensure safe output on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger(__name__)


def check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    ok = v.major == 3 and v.minor >= 11
    msg = f"Python {v.major}.{v.minor}.{v.micro} (Requires Python >= 3.11)"
    return ok, msg


def check_dependencies() -> tuple[bool, list[str]]:
    results = []
    all_ok = True

    # Pillow
    try:
        import PIL
        results.append(f"[OK] Pillow {PIL.__version__} installed")
    except ImportError:
        results.append("[FAIL] Pillow missing (pip install pillow)")
        all_ok = False

    # Playwright
    try:
        import playwright
        results.append(f"[OK] Playwright installed")
    except ImportError:
        results.append("[FAIL] Playwright missing (pip install playwright && playwright install chromium)")
        all_ok = False

    # Ollama package
    try:
        import ollama
        results.append(f"[OK] Ollama Python client installed")
    except ImportError:
        results.append("[FAIL] Ollama Python client missing (pip install ollama)")
        all_ok = False

    return all_ok, results


def check_playwright_chromium() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><h1>Diagnostics OK</h1></body></html>")
            text = page.locator("h1").inner_text()
            browser.close()
            if text == "Diagnostics OK":
                return True, "[OK] Chromium browser binary launched and verified"
            return False, "[FAIL] Playwright Chromium failed content test"
    except Exception as exc:
        return False, f"[FAIL] Playwright Chromium launch failed: {exc} (run: playwright install chromium)"


def check_ollama_server(url: str = "http://localhost:11434") -> tuple[bool, list[str]]:
    results = []
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                results.append(f"[OK] Ollama server reachable at {url}")
                results.append(f"     Available models ({len(models)}): {', '.join(models) if models else 'None'}")
                return True, results
    except Exception as exc:
        results.append(f"[WARN] Ollama server not reachable at {url} ({exc})")
        results.append("       Hint: Ensure Ollama is running (`ollama serve`)")
        return False, results


def check_port_availability(port: int = 8787) -> tuple[bool, str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True, f"[OK] Port {port} is available for Web Control Center"
        except OSError:
            return False, f"[WARN] Port {port} is currently in use"


def run_all_checks() -> bool:
    print("=" * 60)
    print("  BROWSER AGENT DIAGNOSTICS & SYSTEM CHECK")
    print("=" * 60)

    overall_ok = True

    # 1. Python Version
    py_ok, py_msg = check_python_version()
    print(f"\n[1/6] Python Version: {'[PASS]' if py_ok else '[FAIL]'}")
    print(f"      {py_msg}")
    if not py_ok:
        overall_ok = False

    # 2. Dependencies
    dep_ok, dep_msgs = check_dependencies()
    print(f"\n[2/6] Python Dependencies: {'[PASS]' if dep_ok else '[FAIL]'}")
    for m in dep_msgs:
        print(f"      {m}")
    if not dep_ok:
        overall_ok = False

    # 3. Configuration
    try:
        cfg = get_config()
        print(f"\n[3/6] Configuration (config.toml): [PASS]")
        print(f"      Model: {cfg.get('ollama', {}).get('model')} | Viewport: {cfg.get('browser', {}).get('viewport_width')}x{cfg.get('browser', {}).get('viewport_height')}")
    except Exception as exc:
        print(f"\n[3/6] Configuration (config.toml): [FAIL]")
        print(f"      {exc}")
        overall_ok = False

    # 4. Playwright Chromium
    pw_ok, pw_msg = check_playwright_chromium()
    print(f"\n[4/6] Playwright Chromium: {'[PASS]' if pw_ok else '[FAIL]'}")
    print(f"      {pw_msg}")
    if not pw_ok:
        overall_ok = False

    # 5. Ollama Connectivity
    ollama_url = get_config().get("ollama", {}).get("url", "http://localhost:11434")
    ol_ok, ol_msgs = check_ollama_server(ollama_url)
    print(f"\n[5/6] Ollama VLM Connectivity: {'[PASS]' if ol_ok else '[NOTICE]'}")
    for m in ol_msgs:
        print(f"      {m}")

    # 6. Web Port
    port_ok, port_msg = check_port_availability(8787)
    print(f"\n[6/6] Web UI Server Port: {'[PASS]' if port_ok else '[NOTICE]'}")
    print(f"      {port_msg}")

    print("\n" + "=" * 60)
    if overall_ok:
        print("  [SUCCESS] All core diagnostics passed! Ready for execution.")
    else:
        print("  [ERROR] Some checks failed. Please review the output above.")
    print("=" * 60 + "\n")

    return overall_ok


if __name__ == "__main__":
    success = run_all_checks()
    sys.exit(0 if success else 1)
