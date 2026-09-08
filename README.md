# Vision Lite
### Lightweight Visual Browser Agent

**Vision Lite** is a fast, intelligent, and lightweight on-device visual browser agent that uses local vision-language models (e.g. Qwen2.5-VL via Ollama) and Playwright to observe web pages, ground interactive elements with Set-of-Marks visual badges, execute verified actions, and complete web tasks.

---

## Key Features

- **Set-of-Marks (SOM) Visual Grounding**: Extracts interactive DOM elements, computes precise bounding boxes, and overlays numbered color-coded badges on screenshots for the VLM to eliminate text-matching fragility.
- **Intelligent Action Verification**: Performs pre/post action state diffing (URL changes, DOM mutations, input value checks, scroll offsets) to immediately verify whether an action had its intended effect.
- **Short-Term Memory & State Machine**: Tracks structured agent lifecycle states (`IDLE`, `OBSERVING`, `PERCEIVING`, `THINKING`, `ACTING`, `VERIFYING`, `PAUSED`, `COMPLETED`, `FAILED`, `STOPPED`) and maintains action history with success/failure context.
- **Loop Detection & Recovery**: Detects repeated failing actions, oscillating navigation cycles, and identical page states, automatically prompting the model to reassess or fallback gracefully.
- **Execution Controls (Pause / Resume / Stop)**: Thread-safe controls allowing instant pausing, resumption, or stopping during live runs.
- **Modern Web Control Center**: A clean, responsive dark-mode developer UI with live browser viewport, toggleable Set-of-Marks overlay, confidence meters, reasoning breakdowns, and step-by-step action timeline.
- **Safety Guardrails**: Built-in safety filters against sensitive financial and account-deletion operations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser Agent Loop                     │
│                                                             │
│   USER TASK ──▶ OBSERVE ──▶ PERCEIVE (DOM + Set-of-Marks)   │
│                    ▲                      │                 │
│                    │                      ▼                 │
│                 REPEAT        REASON (Local Qwen2.5-VL)     │
│                    │                      │                 │
│                    │                      ▼                 │
│                 VERIFY  ◀──  EXECUTE ACTION (Playwright)    │
│              (State Diff)                                   │
└─────────────────────────────────────────────────────────────┘
```

**Core Subsystems (`browser_agent/`):**
- `agent.py` — Main state machine, loop orchestration, and lifecycle callbacks.
- `perception.py` — DOM element extraction, coordinate calculation, and Set-of-Marks visual annotation.
- `verifier.py` — Pre/post action state diffing and verification engine.
- `loop_detector.py` — Loop detection, repetition monitoring, and recovery advice.
- `actions.py` — Grounded action execution (coordinate clicks, element ID typing, scrolling, key presses).
- `browser.py` — Playwright browser controller and navigation manager.
- `vision.py` — Ollama vision client with robust JSON extraction and error recovery.
- `state.py` — Data models (`ElementInfo`, `ActionRecord`, `AgentMemory`, `AgentState`).
- `config.py` — TOML configuration and environment variable overrides.

---

## Requirements

- **Python 3.11+**
- **Ollama** running locally with a vision model (e.g. `qwen2.5vl:3b`)
- **Playwright** Chromium

---

## Quick Start

### 1. Start Ollama with a Vision Model
```bash
# Pull model
ollama pull qwen2.5vl:3b

# Start Ollama server
ollama serve
```

### 2. Install Dependencies
```bash
pip install -e .
playwright install chromium
```

### 3. Launch the Web Control Center
```bash
# Start Web UI (opens http://127.0.0.1:8787)
python web_server.py

# Or run root entrypoint with no arguments:
python agent.py
```

### 4. Or Run via CLI
```bash
python -m browser_agent.agent "Search DuckDuckGo for Python documentation"

# Or with explicit starting URL:
python -m browser_agent.agent "Open https://example.com and check the page header"
```

---

## Configuration (`config.toml`)

```toml
[ollama]
url = "http://localhost:11434"
model = "qwen2.5vl:3b"
timeout = 30.0

[browser]
headless = false
viewport_width = 1280
viewport_height = 800
start_url = "https://duckduckgo.com"
page_load_timeout = 2000
step_wait_timeout = 1000

[agent]
max_steps = 10
screenshot_path = "agent_screen.png"
screenshot_quality = 80

[logging]
level = "INFO"
format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
```

Any setting can be overridden with environment variables (e.g. `BROWSER_AGENT_BROWSER_HEADLESS=true`).

---

## REST API Endpoints

The Web Control Center provides a complete REST API:

- `POST /api/start` — Start a task (`{"task": "..."}`)
- `POST /api/pause` — Pause the running agent
- `POST /api/resume` — Resume execution
- `POST /api/stop` — Stop agent execution immediately
- `GET /api/status` — Get live status, step count, reasoning, confidence, and action history
- `GET /api/screenshot` — Get latest Set-of-Marks annotated screenshot
- `GET /api/screenshot/clean` — Get clean unannotated page screenshot

---

## Running the Automated Test Suite

Run the full automated test suite:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

Test coverage includes:
- Configuration parsing & validation
- Perception & Set-of-Marks image annotation
- Action grounding & execution (clicks, types, keys, scrolls)
- Pre/Post action state verification
- Loop detection & recovery triggers
- State machine transitions & Pause/Resume/Stop controls
- Web server REST API endpoints
- End-to-end agent orchestration flow

---

## License

MIT