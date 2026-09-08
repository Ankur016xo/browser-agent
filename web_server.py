"""
Local HTTP Web Server and API Bridge for the Browser Agent.
Exposes REST endpoints for Start, Pause, Resume, Stop, live screenshots with Set-of-Marks,
element detection inspection, and real-time state updates.
"""
from __future__ import annotations

import json
import mimetypes
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from browser_agent.agent import BrowserAgent
from browser_agent.config import get_config
from browser_agent.logging import get_logger, setup_logging
from browser_agent.state import ActionRecord, AgentState, ElementInfo

logger = get_logger(__name__)

APP_DIR = Path(__file__).resolve().parent
UI_DIST_DIR = APP_DIR / "vision-lite" / "dist"
UI_DIR = UI_DIST_DIR if (UI_DIST_DIR / "index.html").exists() else (APP_DIR / "vision-lite")
UI_FILE = UI_DIR / "index.html"
SCREENSHOT_PATHS = [
    APP_DIR / "agent_screen_annotated.png",
    APP_DIR / "agent_screen.png",
    APP_DIR / "final.png",
]
EMPTY_SCREENSHOT_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500">'
    b'<rect fill="#18181b" width="800" height="500"/>'
    b'<text x="50%" y="50%" text-anchor="middle" dy=".3em" '
    b'font-family="system-ui, -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif" '
    b'font-size="16" fill="#71717a">'
    b'Browser viewport idle'
    b'</text></svg>'
)


class AgentServerRuntime:
    """Thread-safe runtime controller managing a live BrowserAgent instance."""

    def __init__(self) -> None:
        self.agent: BrowserAgent | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()

        self.task: str = ""
        self.state: AgentState = AgentState.IDLE
        self.current_action_desc: str = "Ready for a task"
        self.current_reasoning: str = ""
        self.current_confidence: float = 1.0
        self.last_verification: dict[str, Any] = {}
        self.detected_elements: list[dict[str, Any]] = []
        self.current_url: str = ""
        self.current_title: str = ""
        self.step: int = 0
        self.max_steps: int = 10
        self.started_at: float = 0.0
        self.finished_at: float = 0.0
        self.logs: list[str] = []
        self.history: list[dict[str, Any]] = []
        self.summary: str = ""
        self.extracted_result: dict[str, Any] = {}
        self.final_state_str: str = ""
        self.is_recovering: bool = False
        self.recovery_count: int = 0

    def append_log(self, text: str) -> None:
        with self.lock:
            self.logs = (self.logs + [text])[-150:]

    def on_state_change(self, state: AgentState) -> None:
        with self.lock:
            if self.state == AgentState.STOPPED and state != AgentState.INITIALIZING:
                return
            self.state = state
            if state == AgentState.INITIALIZING:
                self.current_action_desc = "Opening browser..."
            elif state == AgentState.OBSERVING:
                self.current_action_desc = "Observing page..."
            elif state == AgentState.PERCEIVING:
                self.current_action_desc = "Analyzing page elements..."
            elif state == AgentState.THINKING:
                self.current_action_desc = "Planning next step..."
            elif state == AgentState.ACTING:
                self.current_action_desc = "Interacting with page..."
            elif state == AgentState.VERIFYING:
                self.current_action_desc = "Verifying result..."
            elif state == AgentState.PAUSED:
                self.current_action_desc = "Paused"
            elif state == AgentState.STOPPED:
                self.current_action_desc = "Stopped by user"
            elif state == AgentState.COMPLETED:
                self.current_action_desc = "Task completed"
            elif state == AgentState.FAILED:
                self.current_action_desc = "Task concluded or failed"

    def on_step(self, step: int, max_steps: int) -> None:
        with self.lock:
            self.step = step
            self.max_steps = max_steps

    def on_action(self, record: ActionRecord) -> None:
        with self.lock:
            self.current_reasoning = record.reasoning
            self.current_confidence = record.confidence
            self.current_url = record.url_after or record.url_before
            self.current_title = record.title_after or record.title_before

            # Track recovery and loop detection
            reasoning_lower = (record.reasoning or "").lower()
            if "recovery" in reasoning_lower or "loop" in reasoning_lower:
                self.recovery_count += 1
                self.is_recovering = True
            else:
                self.is_recovering = False
            
            # Extract structured target and action type
            act = record.action or {}
            self.current_action_type = str(act.get("action", "")).upper()
            target_str = ""
            if "element_id" in act:
                target_str = f"#{act['element_id']}"
                if act.get("target"):
                    target_str += f" — {act['target']}"
            elif act.get("target"):
                target_str = str(act["target"])
            elif act.get("url"):
                target_str = str(act["url"])
            elif act.get("direction"):
                target_str = f"{act['direction'].upper()} {act.get('amount', 500)}px"
            self.current_target = target_str

            # Update clean current action summary
            act_type = str(act.get("action", "")).lower()
            if act_type == "navigate":
                self.current_action_desc = f"Opening {act.get('url', 'page')}..."
            elif act_type == "type":
                self.current_action_desc = f"Entering '{act.get('text', '')}' into search..."
            elif act_type == "click":
                self.current_action_desc = f"Clicking {act.get('target', 'element')}..."
            elif act_type == "scroll":
                self.current_action_desc = f"Scrolling page {act.get('direction', 'down')}..."
            elif act_type == "wait":
                self.current_action_desc = "Waiting for page to update..."
            elif act_type == "extract":
                self.current_action_desc = "Reading and extracting content..."

            self.last_verification = {
                "verified": record.verified,
                "reason": record.verification_reason,
                "state_changed": record.state_change,
            }
            self.history.append(record.to_dict())

    def on_perceive(self, elements: list[ElementInfo]) -> None:
        with self.lock:
            self.detected_elements = [e.to_dict() for e in elements]

    def start(self, task: str) -> None:
        with self.lock:
            if self.agent and self.state not in (AgentState.IDLE, AgentState.COMPLETED, AgentState.FAILED, AgentState.STOPPED):
                raise RuntimeError("An agent task is already currently running.")

            self.task = task
            self.state = AgentState.INITIALIZING
            self.current_action_desc = "Launching browser agent..."
            self.current_reasoning = ""
            self.current_confidence = 1.0
            self.last_verification = {}
            self.detected_elements = []
            self.current_url = ""
            self.current_title = ""
            self.step = 0
            self.logs = [f"Task received: {task}"]
            self.history = []
            self.summary = ""
            self.extracted_result = {}
            self.final_state_str = ""
            self.is_recovering = False
            self.recovery_count = 0
            self.started_at = time.time()
            self.finished_at = 0.0

            # Invalidate previous screenshots immediately so new task never shows old view
            for sp in SCREENSHOT_PATHS:
                try:
                    if sp.exists():
                        sp.unlink()
                except Exception as exc:
                    logger.debug("Failed to remove stale screenshot %s: %s", sp, exc)

        def _worker():
            try:
                agent = BrowserAgent(
                    on_state_change=self.on_state_change,
                    on_step=self.on_step,
                    on_perceive=self.on_perceive,
                    on_action=self.on_action,
                    on_log=self.append_log,
                )
                with self.lock:
                    self.agent = agent

                res = agent.run(task)
                with self.lock:
                    self.summary = res.get("summary", "")
                    self.extracted_result = res.get("result", {})
                    self.final_state_str = res.get("state", "")
                    self.finished_at = time.time()
            except Exception as exc:
                self.append_log(f"Worker exception: {exc}")
                with self.lock:
                    self.state = AgentState.FAILED
                    self.finished_at = time.time()
            finally:
                time.sleep(0.1)

        self.thread = threading.Thread(target=_worker, daemon=True)
        self.thread.start()

    def pause(self) -> None:
        with self.lock:
            if self.agent:
                self.agent.pause()

    def resume(self) -> None:
        with self.lock:
            if self.agent:
                self.agent.resume()

    def stop(self) -> None:
        with self.lock:
            if self.agent:
                self.agent.stop()
            self.state = AgentState.STOPPED
            self.current_action_desc = "Stopped by user"
            self.finished_at = time.time()

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            running = self.state not in (
                AgentState.IDLE,
                AgentState.COMPLETED,
                AgentState.FAILED,
                AgentState.STOPPED,
            )
            paused = self.state == AgentState.PAUSED

            elapsed = 0.0
            if self.started_at > 0:
                end_time = self.finished_at if self.finished_at > 0 else time.time()
                elapsed = round(end_time - self.started_at, 1)

            # Check screenshot availability
            annotated_shot = APP_DIR / "agent_screen_annotated.png"
            clean_shot = APP_DIR / "agent_screen.png"
            final_shot = APP_DIR / "final.png"

            has_screenshot = False
            for p in (annotated_shot, clean_shot, final_shot):
                if p.exists() and p.stat().st_mtime >= (self.started_at - 1.0):
                    has_screenshot = True
                    break

            # Page details are safely synced by the agent worker thread in on_action

            # Compute summary stats
            verified_count = sum(1 for h in self.history if h.get("verified"))
            avg_conf = 1.0
            if self.history:
                confs = [h.get("confidence", 1.0) for h in self.history if h.get("confidence") is not None]
                if confs:
                    avg_conf = round(sum(confs) / len(confs), 2)

            result_payload = {
                "state": self.state.value,
                "summary": self.summary,
                "extracted_data": getattr(self, "extracted_result", {}),
                "final_url": self.current_url,
                "final_title": self.current_title,
                "step": self.step,
                "max_steps": self.max_steps,
                "elapsed_seconds": elapsed,
                "verified_count": verified_count,
                "total_actions": len(self.history),
                "avg_confidence": avg_conf,
            }

            return {
                "running": running,
                "paused": paused,
                "state": self.state.value,
                "task": self.task,
                "current_action": self.current_action_desc,
                "action_type": getattr(self, "current_action_type", ""),
                "target": getattr(self, "current_target", ""),
                "reasoning": self.current_reasoning,
                "confidence": self.current_confidence,
                "average_confidence": avg_conf,
                "verification": self.last_verification,
                "verified_count": verified_count,
                "total_actions": len(self.history),
                "current_url": self.current_url,
                "current_title": self.current_title,
                "step": self.step,
                "max_steps": self.max_steps,
                "elapsed_seconds": elapsed,
                "has_screenshot": has_screenshot,
                "elements": self.detected_elements,
                "elements_count": len(self.detected_elements),
                "history": self.history,
                "summary": self.summary,
                "extracted_data": getattr(self, "extracted_result", {}),
                "result": result_payload,
                "logs": self.logs,
            }

    @staticmethod
    def _format_action_timeline_description(act: dict[str, Any]) -> str:
        if not act:
            return "Action performed"
        action_type = str(act.get("action", "")).lower()
        if action_type == "navigate":
            url = str(act.get("url", ""))
            if "wikipedia.org" in url:
                return "✓ Navigated to Wikipedia"
            elif "flipkart.com" in url:
                return "✓ Navigated to Flipkart"
            elif "amazon" in url:
                return "✓ Navigated to Amazon"
            return f"✓ Navigated to {url}"
        elif action_type == "type":
            text = str(act.get("text", ""))
            target = act.get("target") or "search field"
            return f'✓ Entered "{text}" into {target}'
        elif action_type == "click":
            target = act.get("target") or f"element #{act.get('element_id', '')}"
            if "india" in str(target).lower():
                return f"✓ Opened {target}"
            return f"✓ Clicked {target}"
        elif action_type == "scroll":
            direction = act.get("direction", "down")
            return f"✓ Scrolled {direction} on page"
        elif action_type == "wait":
            return "✓ Waited for page to update"
        elif action_type == "extract":
            return "✓ Extracted requested details"
        elif action_type == "go_back":
            return "✓ Navigated back"
        elif action_type == "done":
            return "✓ Concluded task execution"
        return f"✓ {action_type.capitalize()}: {act.get('target', '')}"

    @staticmethod
    def _format_clean_verification(reason: str) -> str:
        if not reason:
            return "Verified page state"
        clean = reason.strip()
        if "Matched pattern" in clean:
            clean = "Extracted verified match from page content"
        elif "DOM check" in clean:
            clean = "Target elements confirmed on page"
        elif "Target page confirmed" in clean or "Article confirmed" in clean:
            clean = "Target article page confirmed"
        elif "Search query" in clean:
            clean = "Search query verified on results page"
        elif len(clean) > 75:
            clean = clean[:72] + "..."
        return f"Verified: {clean}"

    def get_ui_agent_state(self) -> dict[str, Any]:
        with self.lock:
            # Map backend AgentState to UI AgentStatus
            if self.state == AgentState.IDLE:
                ui_status = "READY" if self.started_at == 0 else "IDLE"
            elif self.state in (AgentState.INITIALIZING, AgentState.OBSERVING, AgentState.PERCEIVING, AgentState.ACTING):
                ui_status = "RECOVERING" if getattr(self, "is_recovering", False) else "WORKING"
            elif self.state == AgentState.THINKING:
                ui_status = "RECOVERING" if getattr(self, "is_recovering", False) else "THINKING"
            elif self.state == AgentState.VERIFYING:
                ui_status = "VERIFYING"
            elif self.state == AgentState.PAUSED:
                ui_status = "PAUSED"
            elif self.state == AgentState.STOPPED:
                ui_status = "FAILED"
            elif self.state == AgentState.COMPLETED:
                ui_status = "COMPLETED"
            elif self.state == AgentState.FAILED:
                ui_status = "FAILED"
            else:
                ui_status = "READY"

            # Check screenshot availability
            screenshot_url: str | None = None
            for p in SCREENSHOT_PATHS:
                if p.exists() and p.stat().st_mtime >= (self.started_at - 1.0 if self.started_at > 0 else 0):
                    screenshot_url = f"/api/screenshot?_t={int(time.time() * 1000)}"
                    break

            # Authentic procedure checklist from task_plan
            procedures: list[dict[str, Any]] = []
            if self.agent and getattr(self.agent, "task_plan", None) and getattr(self.agent.task_plan, "procedural_requirements", None):
                reqs = self.agent.task_plan.procedural_requirements
                proc_idx = self.agent.memory.procedure_index if (self.agent.memory and hasattr(self.agent.memory, "procedure_index")) else 0
                is_done = self.state == AgentState.COMPLETED
                for idx, pr in enumerate(reqs):
                    if is_done or idx < proc_idx:
                        status = "completed"
                    elif idx == proc_idx and ui_status in ("WORKING", "THINKING", "VERIFYING", "RECOVERING"):
                        status = "active"
                    else:
                        status = "pending"
                    procedures.append({
                        "id": f"proc_{idx+1}",
                        "label": pr,
                        "status": status,
                    })

            # Verification object
            verification_obj = None
            if self.last_verification:
                verification_obj = {
                    "passed": bool(self.last_verification.get("verified", False)),
                    "message": str(self.last_verification.get("reason", "Verification checked.")),
                }

            # Authentic live action timeline grounded in real ActionRecords
            timeline_logs: list[dict[str, Any]] = []
            for i, h in enumerate(self.history):
                act = h.get("action", {})
                ts = int(h.get("timestamp", self.started_at or time.time()) * 1000)
                desc = self._format_action_timeline_description(act)
                timeline_logs.append({
                    "id": f"act_{i}_{ts}",
                    "timestamp": ts,
                    "message": desc,
                    "type": "action",
                })
                if h.get("verified"):
                    v_reason = h.get("verification_reason", "")
                    clean_v = self._format_clean_verification(v_reason)
                    if clean_v:
                        timeline_logs.append({
                            "id": f"ver_{i}_{ts}",
                            "timestamp": ts + 100,
                            "message": f"✓ {clean_v}",
                            "type": "verification",
                        })

            if ui_status in ("WORKING", "THINKING", "VERIFYING", "RECOVERING"):
                now_ts = int(time.time() * 1000)
                timeline_logs.append({
                    "id": f"active_{now_ts}",
                    "timestamp": now_ts,
                    "message": f"◉ {self.current_action_desc}",
                    "type": "action",
                })
            elif ui_status == "COMPLETED":
                fin_ts = int(self.finished_at * 1000) if self.finished_at > 0 else int(time.time() * 1000)
                timeline_logs.append({
                    "id": f"done_{fin_ts}",
                    "timestamp": fin_ts,
                    "message": "✓ Result verified & task completed",
                    "type": "system",
                })
            elif ui_status == "FAILED":
                fin_ts = int(self.finished_at * 1000) if self.finished_at > 0 else int(time.time() * 1000)
                timeline_logs.append({
                    "id": f"failed_{fin_ts}",
                    "timestamp": fin_ts,
                    "message": "✗ Task stopped or could not be completed",
                    "type": "system",
                })

            last_action_json = None
            if self.history:
                try:
                    # Sanitize action JSON so private thoughts/reasoning are omitted
                    act_copy = dict(self.history[-1].get("action", {}))
                    act_copy.pop("reasoning", None)
                    act_copy.pop("thought", None)
                    last_action_json = json.dumps(act_copy, indent=2)
                except Exception:
                    pass

            advanced_info = {
                "url": self.current_url,
                "title": self.current_title,
                "domElements": len(self.detected_elements),
                "somElements": len(self.detected_elements),
                "model": "qwen2.5-vl:3b",
                "confidence": self.current_confidence,
                "actionJson": last_action_json,
                "loopDetected": getattr(self, "is_recovering", False),
                "recoveryEvents": getattr(self, "recovery_count", 0),
                "rawLogs": self.logs[-25:],
            }

            extracted = getattr(self, "extracted_result", {}) or {}
            if not extracted and self.agent and getattr(self.agent, "memory", None):
                extracted = getattr(self.agent.memory, "extracted_data", {}) or {}

            res_summary = self.summary or None
            if not res_summary and self.agent and getattr(self.agent, "memory", None) and self.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.STOPPED):
                if self.state == AgentState.COMPLETED:
                    res_summary = "Task completed successfully."
                else:
                    res_summary = "Task concluded or stopped."

            final_st = getattr(self, "final_state_str", "")
            if not final_st and self.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.STOPPED):
                final_st = "SUCCESS" if self.state == AgentState.COMPLETED else "FAILED"

            return {
                "status": ui_status,
                "task": self.task,
                "step": self.step,
                "maxSteps": self.max_steps,
                "url": self.current_url,
                "title": self.current_title,
                "screenshot": screenshot_url,
                "currentAction": self.current_action_desc,
                "currentProcedure": self.current_action_desc,
                "procedureIndex": getattr(self.agent.memory, "procedure_index", 0) if (self.agent and self.agent.memory) else 0,
                "procedures": procedures,
                "completedProcedures": len([p for p in procedures if p["status"] == "completed"]),
                "verification": verification_obj,
                "result": res_summary,
                "extractedData": extracted,
                "finalState": final_st,
                "logs": timeline_logs,
                "advanced": advanced_info,
                "startedAt": int(self.started_at * 1000) if self.started_at > 0 else None,
            }


RUNTIME = AgentServerRuntime()


class BrowserAgentHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP Request handler for Web UI and REST API."""

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in {"/api/task/state", "/api/state"}:
            return self._json(RUNTIME.get_ui_agent_state())

        if path == "/api/status":
            return self._json(RUNTIME.get_status())

        if path == "/api/screenshot":
            # Return live screenshot (prefer annotated Set-of-Marks screenshot)
            for path_cand in SCREENSHOT_PATHS:
                if path_cand.exists():
                    data = path_cand.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store, must-revalidate")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Content-Length", str(len(EMPTY_SCREENSHOT_SVG)))
            self.end_headers()
            self.wfile.write(EMPTY_SCREENSHOT_SVG)
            return

        if path == "/api/screenshot/clean":
            clean_path = APP_DIR / "agent_screen.png"
            if clean_path.exists():
                data = clean_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(EMPTY_SCREENSHOT_SVG)))
            self.end_headers()
            self.wfile.write(EMPTY_SCREENSHOT_SVG)
            return

        if path == "/api/history":
            return self._json({"history": RUNTIME.get_status()["history"]})

        if (path.startswith("/api/task/") and path.endswith("/events")) or path == "/api/events":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            last_history_len = 0
            try:
                for _ in range(300):  # Stream for up to ~5 minutes
                    status = RUNTIME.get_status()
                    obs_data = {
                        "url": status.get("current_url", ""),
                        "title": status.get("current_title", ""),
                        "screenshot": f"/api/screenshot?_t={int(time.time()*1000)}",
                        "message": status.get("current_action", ""),
                    }
                    self.wfile.write(f"event: observation\ndata: {json.dumps(obs_data)}\n\n".encode("utf-8"))

                    history = status.get("history", [])
                    if len(history) > last_history_len:
                        for i in range(last_history_len, len(history)):
                            item = history[i]
                            act = item.get("action", {})
                            act_msg = f"{act.get('action')}: {act.get('reasoning') or act.get('target') or ''}" if act else f"Step {i+1}"
                            proc_data = {
                                "step": item.get("step", i + 1),
                                "max_steps": status.get("max_steps", 10),
                                "message": act_msg,
                                "verified": item.get("verified", False),
                            }
                            self.wfile.write(f"event: procedure_completed\ndata: {json.dumps(proc_data)}\n\n".encode("utf-8"))
                        last_history_len = len(history)

                    state_val = status.get("state", "")
                    if state_val == "COMPLETED":
                        comp_data = {"summary": status.get("summary", "Task completed successfully.")}
                        self.wfile.write(f"event: task_completed\ndata: {json.dumps(comp_data)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        break
                    elif state_val in ("FAILED", "STOPPED"):
                        fail_data = {"summary": status.get("summary", "Task failed or stopped.")}
                        self.wfile.write(f"event: task_failed\ndata: {json.dumps(fail_data)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        break

                    self.wfile.flush()
                    time.sleep(0.8)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # Serve vision-lite UI and static assets
        ui_dir = UI_DIST_DIR if (UI_DIST_DIR / "index.html").exists() else (APP_DIR / "vision-lite")
        ui_file = ui_dir / "index.html"

        rel_path = path.lstrip("/")
        if rel_path.startswith("vision-lite/"):
            rel_path = rel_path[len("vision-lite/"):].lstrip("/")
        elif rel_path == "vision-lite":
            rel_path = ""

        if not rel_path or rel_path == "index.html":
            rel_path = "index.html"

        candidate = (ui_dir / rel_path).resolve()
        try:
            candidate.relative_to(ui_dir.resolve())
            is_safe = True
        except ValueError:
            is_safe = False

        if is_safe and candidate.is_file():
            mime, _ = mimetypes.guess_type(str(candidate))
            mime = mime or "application/octet-stream"
            if candidate.suffix.lower() == ".js":
                mime = "application/javascript; charset=utf-8"
            elif candidate.suffix.lower() == ".css":
                mime = "text/css; charset=utf-8"
            elif candidate.suffix.lower() == ".html":
                mime = "text/html; charset=utf-8"
            elif candidate.suffix.lower() == ".svg":
                mime = "image/svg+xml; charset=utf-8"
            elif candidate.suffix.lower() == ".webp":
                mime = "image/webp"

            data = candidate.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # SPA fallback for non-API frontend routes
        if ui_file.exists() and not path.startswith("/api/"):
            data = ui_file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        endpoint = self.path.split("?", 1)[0]

        # Normalize endpoints
        if endpoint in {"/api/task/start", "/api/start"}:
            action = "start"
        elif endpoint in {"/api/pause", "/api/task/pause"} or (endpoint.startswith("/api/task/") and endpoint.endswith("/pause")):
            action = "pause"
        elif endpoint in {"/api/resume", "/api/task/resume"} or (endpoint.startswith("/api/task/") and endpoint.endswith("/resume")):
            action = "resume"
        elif endpoint in {"/api/stop", "/api/task/stop"} or (endpoint.startswith("/api/task/") and endpoint.endswith("/stop")):
            action = "stop"
        else:
            return self.send_error(HTTPStatus.NOT_FOUND)

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}") if length > 0 else {}

            if action == "start":
                task = str(payload.get("task_description") or payload.get("task", "")).strip()
                if not task:
                    raise ValueError("Please provide a valid browser task.")
                RUNTIME.start(task)
            elif action == "pause":
                RUNTIME.pause()
            elif action == "resume":
                RUNTIME.resume()
            elif action == "stop":
                RUNTIME.stop()

            self._json({"ok": True, "task_id": "live-session", **RUNTIME.get_status()})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return  # Suppress request spam in console


def main(port: int = 8787, open_browser: bool = True) -> None:
    setup_logging()
    if "--no-browser" in sys.argv:
        open_browser = False
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)

    url = f"http://127.0.0.1:{port}"
    print()
    print("=" * 60)
    print("BROWSER AGENT CONTROL CENTER")
    print(f"Server URL: {url}")
    print("=" * 60)
    print()

    server = ThreadingHTTPServer(("127.0.0.1", port), BrowserAgentHTTPHandler)
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.shutdown()


if __name__ == "__main__":
    main()
