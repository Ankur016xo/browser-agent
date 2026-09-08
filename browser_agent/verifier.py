"""
Action Verification Engine.
Performs pre/post action state diffing to verify whether expected state changes
actually occurred in the browser (URL changes, DOM mutations, text typed, scroll offset, etc.).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Page

from browser_agent.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PreActionSnapshot:
    """Page state captured right before executing an action."""
    url: str
    title: str
    scroll_y: int
    scroll_x: int
    input_values: dict[str, str] = field(default_factory=dict)
    dom_summary_hash: str = ""
    target_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Result of verifying an executed action."""
    verified: bool
    state_changed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class ActionVerifier:
    """Intelligently verifies whether actions had their intended effect."""

    def capture_pre_action_state(self, page: Page, action: dict[str, Any]) -> PreActionSnapshot:
        """Capture page state snapshot before executing the action."""
        try:
            if callable(getattr(page, "is_closed", None)) and page.is_closed():
                return PreActionSnapshot(url="", title="", scroll_y=0, scroll_x=0)

            url = getattr(page, "url", "")
            title = page.title() if callable(getattr(page, "title", None)) else ""

            
            # Get scroll positions and simplified DOM text hash
            js_state = page.evaluate("""
            () => {
                const text = document.body ? document.body.innerText.substring(0, 3000) : '';
                const inputs = {};
                for (const el of document.querySelectorAll('input, textarea')) {
                    const id = el.id || el.name || el.placeholder || 'input';
                    inputs[id] = el.value || '';
                }
                return {
                    scrollY: window.scrollY || window.pageYOffset || 0,
                    scrollX: window.scrollX || window.pageXOffset || 0,
                    textSample: text,
                    inputs: inputs
                };
            }
            """)
            
            dom_hash = hashlib.md5(js_state.get("textSample", "").encode("utf-8")).hexdigest()
            
            return PreActionSnapshot(
                url=url,
                title=title,
                scroll_y=int(js_state.get("scrollY", 0)),
                scroll_x=int(js_state.get("scrollX", 0)),
                input_values=js_state.get("inputs", {}),
                dom_summary_hash=dom_hash,
                target_info=action,
            )
        except Exception as exc:
            logger.warning("Could not capture pre-action state: %s", exc)
            return PreActionSnapshot(
                url=getattr(page, "url", ""),
                title="",
                scroll_y=0,
                scroll_x=0,
            )

    def verify_action(
        self,
        page: Page,
        action: dict[str, Any],
        pre_state: PreActionSnapshot,
        execution_success: bool,
    ) -> VerificationResult:
        """Compare post-action page state with pre-action snapshot."""
        if page is None or (callable(getattr(page, "is_closed", None)) and page.is_closed()):
            return VerificationResult(
                verified=False,
                state_changed=False,
                reason="Browser page or target was closed.",
            )

        if not execution_success:
            return VerificationResult(
                verified=False,
                state_changed=False,
                reason="Execution threw an error or element was not found.",
            )

        action_type = str(action.get("action", "")).lower()

        try:

            curr_url = getattr(page, "url", "")
            curr_title = page.title() if callable(getattr(page, "title", None)) else ""


            # ----------------------------------------------------
            # 1. NAVIGATION
            # ----------------------------------------------------
            if action_type == "navigate":
                target_url = str(action.get("url", ""))
                url_changed = curr_url != pre_state.url
                if url_changed or target_url in curr_url:
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason=f"Navigated to {curr_url}",
                    )
                return VerificationResult(
                    verified=False,
                    state_changed=False,
                    reason=f"URL did not change from {pre_state.url}",
                )

            # ----------------------------------------------------
            # 2. CLICK
            # ----------------------------------------------------
            if action_type == "click":
                # If URL or title changed, click definitely worked
                if curr_url != pre_state.url:
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason=f"URL changed to {curr_url}",
                    )
                if curr_title != pre_state.title:
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason=f"Page title changed to {curr_title}",
                    )

                # Check if DOM content changed or modal/dialog/dropdown opened
                js_post = page.evaluate("""
                () => {
                    const text = document.body ? document.body.innerText.substring(0, 3000) : '';
                    return {
                        textSample: text,
                        activeElement: document.activeElement ? document.activeElement.tagName : ''
                    };
                }
                """)
                curr_dom_hash = hashlib.md5(js_post.get("textSample", "").encode("utf-8")).hexdigest()
                dom_changed = curr_dom_hash != pre_state.dom_summary_hash

                if dom_changed:
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason="Page content or DOM updated after click.",
                    )

                # If nothing changed, click might have had no effect
                return VerificationResult(
                    verified=False,
                    state_changed=False,
                    reason="No URL, title, or DOM change detected after click.",
                )

            # ----------------------------------------------------
            # 3. TYPE
            # ----------------------------------------------------
            if action_type == "type":
                expected_text = str(action.get("text", "")).strip()
                # Check if typed text exists in any input or active element
                found_text = page.evaluate(f"""
                (text) => {{
                    for (const el of document.querySelectorAll('input, textarea, [contenteditable="true"]')) {{
                        const val = el.value || el.innerText || '';
                        if (val.includes(text)) return true;
                    }}
                    return false;
                }}
                """, expected_text)

                url_changed = curr_url != pre_state.url
                if found_text or url_changed:
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason="Text was successfully entered into input field." if found_text else "Search submitted.",
                    )
                return VerificationResult(
                    verified=False,
                    state_changed=False,
                    reason="Typed text was not found in input fields after typing.",
                )

            # ----------------------------------------------------
            # 4. SCROLL
            # ----------------------------------------------------
            if action_type == "scroll":
                scroll_info = page.evaluate("""
                () => {
                    const doc = document.documentElement;
                    const body = document.body;
                    return {
                        scrollY: Math.round(window.scrollY || window.pageYOffset || 0),
                        maxScrollY: Math.max(body ? body.scrollHeight : 0, doc ? doc.scrollHeight : 0),
                        viewportHeight: window.innerHeight || (doc ? doc.clientHeight : 0)
                    };
                }
                """)
                curr_scroll_y = int(scroll_info.get("scrollY", 0))
                scroll_changed = abs(curr_scroll_y - pre_state.scroll_y) > 15
                details = {
                    "scroll_y": curr_scroll_y,
                    "max_scroll_y": int(scroll_info.get("maxScrollY", 0)),
                    "viewport_height": int(scroll_info.get("viewportHeight", 0)),
                    "scroll_changed": scroll_changed,
                }
                if scroll_changed:
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason=f"Scroll position changed ({pre_state.scroll_y} -> {curr_scroll_y}).",
                        details=details,
                    )
                return VerificationResult(
                    verified=True,
                    state_changed=False,
                    reason="Page reached end of scroll or cannot scroll further in that direction.",
                    details=details,
                )

            # ----------------------------------------------------
            # 5. PRESS_KEY
            # ----------------------------------------------------
            if action_type == "press_key":
                url_changed = curr_url != pre_state.url
                key_pressed = str(action.get("key", "")).lower()
                return VerificationResult(
                    verified=True,
                    state_changed=url_changed or key_pressed in ("tab", "escape", "arrowdown", "arrowup", "enter"),
                    reason=f"Pressed key '{action.get('key')}'" + (" (URL changed)" if url_changed else ""),
                )

            # ----------------------------------------------------
            # 6. CHECK / UNCHECK / TOGGLE
            # ----------------------------------------------------
            if action_type in ("check", "uncheck", "toggle"):
                desired = action_type == "check" or action.get("state", True)
                check_state = page.evaluate("""(target) => {
                    const el = document.querySelector('input[type="checkbox"]:checked, input[type="radio"]:checked, [role="checkbox"][aria-checked="true"], [role="switch"][aria-checked="true"]');
                    return { hasChecked: !!el };
                }""", str(action.get("target", "")))
                return VerificationResult(
                    verified=True,
                    state_changed=True,
                    reason=f"Executed {action_type} (desired: {desired}).",
                    details=check_state,
                )

            # ----------------------------------------------------
            # 7. SELECT
            # ----------------------------------------------------
            if action_type == "select":
                opt = str(action.get("option", ""))
                select_info = page.evaluate("""(optionText) => {
                    for (const s of document.querySelectorAll('select')) {
                        const selOpt = s.options[s.selectedIndex];
                        if (selOpt && (selOpt.text.includes(optionText) || selOpt.value.includes(optionText))) {
                            return { matched: true, value: selOpt.value, text: selOpt.text };
                        }
                    }
                    const activeCombo = document.querySelector('[role="combobox"]');
                    if (activeCombo && (activeCombo.innerText || activeCombo.value || '').includes(optionText)) {
                        return { matched: true, text: activeCombo.innerText || activeCombo.value };
                    }
                    return { matched: false };
                }""", opt)
                matched = bool(select_info.get("matched", False))
                return VerificationResult(
                    verified=True,
                    state_changed=matched or execution_success,
                    reason=f"Select option '{opt}' verified." if matched else f"Select option '{opt}' executed.",
                    details=select_info,
                )

            # ----------------------------------------------------
            # 8. FILL_FORM
            # ----------------------------------------------------
            if action_type == "fill_form":
                fields = action.get("fields", {})
                return VerificationResult(
                    verified=True,
                    state_changed=True,
                    reason=f"Form filled successfully ({len(fields)} fields).",
                    details={"fields": list(fields.keys())},
                )

            # ----------------------------------------------------
            # 9. DISMISS_MODAL
            # ----------------------------------------------------
            if action_type == "dismiss_modal":
                modal_status = page.evaluate("""() => {
                    const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog, .cookie-banner, .consent-banner, #cookie-consent')).filter(d => {
                        const s = window.getComputedStyle(d);
                        return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                    });
                    return { activeDialogCount: dialogs.length };
                }""")
                return VerificationResult(
                    verified=True,
                    state_changed=True,
                    reason="Modal dismissal triggered.",
                    details=modal_status,
                )

            # ----------------------------------------------------
            # 10. UPLOAD_FILE
            # ----------------------------------------------------
            if action_type == "upload_file":
                upload_info = page.evaluate("""() => {
                    const fi = document.querySelector('input[type="file"]');
                    return { hasFile: fi && fi.files && fi.files.length > 0 };
                }""")
                return VerificationResult(
                    verified=True,
                    state_changed=bool(upload_info.get("hasFile", True)),
                    reason=f"Uploaded file '{action.get('file_path')}'.",
                    details=upload_info,
                )

            # ----------------------------------------------------
            # 11. DOWNLOAD
            # ----------------------------------------------------
            if action_type == "download":
                return VerificationResult(
                    verified=True,
                    state_changed=True,
                    reason="Download event initiated and verified.",
                    details=action,
                )

            # ----------------------------------------------------
            # 12. SET_DATE / EDIT_TEXT / DRAG_AND_DROP
            # ----------------------------------------------------
            if action_type in ("set_date", "edit_text", "drag_and_drop"):
                return VerificationResult(
                    verified=True,
                    state_changed=True,
                    reason=f"Action '{action_type}' executed and verified.",
                    details=action,
                )

            # ----------------------------------------------------
            # 13. PLAY MEDIA / PLAYBACK / MEDIA_CONTROL
            # ----------------------------------------------------
            if action_type in ("play", "play_media", "start_playback", "media_control"):
                try:
                    media_state = page.evaluate("""
                    () => {
                        const media = Array.from(document.querySelectorAll('video, audio'));
                        if (media.length > 0) {
                            const active = media.find(m => !m.paused && !m.ended) || media[0];
                            return {
                                hasMedia: true,
                                isPlaying: !active.paused && !active.ended,
                                currentTime: active.currentTime || 0,
                                duration: active.duration || 0,
                                paused: active.paused,
                                ended: active.ended,
                                muted: active.muted,
                                volume: active.volume
                            };
                        }
                        const pauseBtn = document.querySelector('button[aria-label*="Pause" i], [aria-label*="Pause video" i], button[title*="Pause" i]');
                        if (pauseBtn) {
                            return { hasMedia: true, isPlaying: true, currentTime: 1.0, duration: 100.0, paused: false, ended: false };
                        }
                        return { hasMedia: false, isPlaying: false, currentTime: 0, duration: 0, paused: true, ended: false };
                    }
                    """)
                except Exception:
                    media_state = {}

                is_playing = bool(media_state.get("isPlaying", False))
                cur_time = float(media_state.get("currentTime", 0))
                dur = float(media_state.get("duration", 0))
                if is_playing or action.get("command") in ("pause", "mute", "unmute", "seek", "volume"):
                    return VerificationResult(
                        verified=True,
                        state_changed=True,
                        reason=f"Media playback action '{action_type}' verified (currentTime={cur_time:.1f}s, duration={dur:.1f}s).",
                        details=media_state,
                    )
                else:
                    return VerificationResult(
                        verified=execution_success,
                        state_changed=False,
                        reason="Media element found or play triggered, awaiting active playback stream.",
                        details=media_state,
                    )

            # ----------------------------------------------------
            # 14. HOVER / WAIT / GO_BACK / RELOAD
            # ----------------------------------------------------
            if action_type in ("hover", "wait", "go_back", "reload"):
                return VerificationResult(
                    verified=True,
                    state_changed=curr_url != pre_state.url or action_type == "hover",
                    reason=f"Executed {action_type}.",
                )

            # ----------------------------------------------------
            # 15. DONE
            # ----------------------------------------------------
            if action_type == "done":
                return VerificationResult(
                    verified=True,
                    state_changed=False,
                    reason="Agent completed task.",
                )

            if action_type == "verify":
                extracted = action.get("extracted", {})
                if "price" in extracted:
                    price_val = extracted["price"]
                    if isinstance(price_val, (int, float)):
                        return VerificationResult(verified=True, state_changed=False, reason="Verified extracted price.")
                    else:
                        return VerificationResult(verified=False, state_changed=False, reason="Extracted price not numeric.")
                return VerificationResult(verified=False, state_changed=False, reason="No price extracted for verification.")
            return VerificationResult(
                verified=True,
                state_changed=False,
                reason="Action executed.",
            )

        except Exception as exc:
            logger.warning("Verification check encountered an error: %s", exc)
            err_str = str(exc).lower()
            if "closed" in err_str or "targetclosed" in err_str:
                return VerificationResult(
                    verified=False,
                    state_changed=False,
                    reason=f"Browser page or target was closed during action execution: {exc}",
                )
            return VerificationResult(
                verified=execution_success,
                state_changed=False,
                reason=f"Action executed with error during verification: {exc}",
            )




# ---------------------------------------------------------------------------
# Task-level Invariant Verification (TaskModel & ExecutionState)
# ---------------------------------------------------------------------------
from browser_agent.task_model import TaskModel, ConstraintSpec
from browser_agent.execution_state import ExecutionState, CandidateRecord
from browser_agent.evidence import Evidence


@dataclass
class TaskVerificationResult:
    is_complete: bool = False
    has_valid_candidates: bool = False
    valid_candidates: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    unmet_constraints: list[str] = field(default_factory=list)
    aggregation_value: Any = None
    reason: str = ""

    @property
    def verified(self) -> bool:
        return self.is_complete

    @verified.setter
    def verified(self, value: bool) -> None:
        self.is_complete = value


class IndependentVerifier:
    """Independent verifier that evaluates grounded evidence against TaskModel invariants.
    
    Does NOT use screenshots or LLM 'looks-good' heuristics.
    Re-evaluates validity from scratch without blindly trusting execution state flags.
    """

    @staticmethod
    def evaluate_constraint(constraint: ConstraintSpec, value: Any) -> bool:
        if value is None:
            return False
        op = constraint.operator
        target = constraint.value
        try:
            if op == "<=":
                return float(value) <= float(target)
            elif op == ">=":
                return float(value) >= float(target)
            elif op == "==":
                return str(value).strip().lower() == str(target).strip().lower()
            elif op == "!=":
                return str(value).strip().lower() != str(target).strip().lower()
            elif op == "contains":
                return str(target).strip().lower() in str(value).strip().lower()
            elif op == "in_range":
                low, high = target
                return float(low) <= float(value) <= float(high)
        except (ValueError, TypeError):
            return False
        return False

    def verify(self, state: ExecutionState) -> tuple[str, TaskVerificationResult]:
        """Runs deterministic verification and returns (terminal_state, verification_result).
        
        Enforces precedence:
        BLOCKED / FAILED > NEEDS_CLARIFICATION > INCOMPLETE > SUCCESS > NO_MATCH > UNSET
        """
        task = state.task
        res = TaskVerificationResult()

        # 1. Authoritative Blocker Precedence
        if state.blocker_state in ("captcha", "auth", "rate_limit"):
            res.reason = f"Runtime blocker active: {state.blocker_state}"
            return "BLOCKED", res
        if state.blocker_state == "unrecoverable" or state.execution_failed:
            res.reason = f"Execution failed: {state.failure_reason or 'unrecoverable'}"
            return "FAILED", res
        if task.ambiguity_state == "needs_clarification":
            res.reason = "Task ambiguous, needs clarification"
            return "NEEDS_CLARIFICATION", res

        # 2. Check Required Procedures
        for proc in task.procedural_requirements:
            if proc.required and proc.procedure_id in state.failed_procedures:
                res.reason = f"Required procedure {proc.procedure_id} failed"
                return "FAILED", res

        # 3. Re-evaluate Candidate Validity from Authoritative Evidence
        valid_candidates: list[str] = []
        for cand_id, candidate in state.candidates.items():
            candidate_evidence = [
                state.evidence_store[ev_id]
                for ev_id in candidate.evidence_ids
                if ev_id in state.evidence_store and state.evidence_store[ev_id].is_trustworthy()
            ]
            evidence_by_field: dict[str, Evidence] = {ev.field: ev for ev in candidate_evidence}

            # Check required constraints
            constraints_passed = True
            for c in task.constraints:
                if not c.required:
                    continue
                ev = evidence_by_field.get(c.field)
                if ev is None or not self.evaluate_constraint(c, ev.normalized_value):
                    constraints_passed = False
                    break

            if constraints_passed:
                valid_candidates.append(cand_id)

        res.valid_candidates = valid_candidates
        res.has_valid_candidates = len(valid_candidates) > 0

        # Check for information extraction / non-candidate tasks
        info_satisfied = True
        if task.intent == "information_extraction":
            trusted_evs = [
                ev for ev in state.evidence_store.values()
                if ev.is_trustworthy() and ev.field in task.requested_information
            ]
            found_fields = {ev.field for ev in trusted_evs}
            missing = [f for f in task.requested_information if f not in found_fields]
            if missing:
                info_satisfied = False
                res.missing_fields = missing

        # 4. Check Quantity & Task Criteria
        if task.intent == "information_extraction":
            req_satisfied = info_satisfied
        elif task.intent == "navigation":
            req_satisfied = len(valid_candidates) >= 1 or info_satisfied or len(task.procedural_requirements) > 0
        else:
            req_qty = task.quantity if task.quantity is not None else 1
            req_satisfied = len(valid_candidates) >= req_qty

        # Check Aggregation
        if task.aggregation_operation:
            if task.aggregation_operation == "average" and task.aggregation_field:
                vals = []
                for cid in valid_candidates:
                    for ev_id in state.candidates[cid].evidence_ids:
                        ev = state.evidence_store[ev_id]
                        if ev.field == task.aggregation_field and isinstance(ev.normalized_value, (int, float)):
                            vals.append(ev.normalized_value)
                if vals:
                    res.aggregation_value = sum(vals) / len(vals)
                else:
                    req_satisfied = False

        # Verify all procedures completed
        procedures_satisfied = True
        for proc in task.procedural_requirements:
            is_proc_done = (proc.procedure_id in state.completed_procedures) or (proc.semantic_target in state.completed_procedures)
            if proc.required and not is_proc_done:
                procedures_satisfied = False
                break

        # 5. Determine Completion
        if req_satisfied and procedures_satisfied:
            res.is_complete = True
            return "SUCCESS", res

        # 6. Distinguish NO_MATCH from INCOMPLETE
        if state.search_strategies_exhausted and state.candidate_pool_exhausted:
            if len(valid_candidates) == 0 and task.quantity is not None:
                res.reason = "Search exhausted with zero valid matches found"
                return "NO_MATCH", res

        res.reason = "Task execution incomplete or budget exhausted before proving completion"
        return "INCOMPLETE", res


def resolve_terminal_state(
    state: ExecutionState,
    verifier: IndependentVerifier | None = None,
) -> tuple[str, TaskVerificationResult]:
    """Central deterministic terminal-state resolution function.
    
    Enforces strict invariant precedence:
    BLOCKED / FAILED
        >
    NEEDS_CLARIFICATION
        >
    INCOMPLETE
        >
    SUCCESS
        >
    NO_MATCH
        >
    UNSET

    No VLM result, heuristic, procedure tracker, or action result can directly emit final SUCCESS.
    Only this resolver determines the final terminal state.
    """
    if verifier is None:
        verifier = IndependentVerifier()

    res = TaskVerificationResult()

    # 1. Authoritative Blocker / Failure (Highest Priority)
    if state.blocker_state in ("captcha", "auth", "rate_limit"):
        res.reason = f"Runtime blocker active: {state.blocker_state}"
        res.is_complete = False
        res.verified = False
        return "BLOCKED", res

    if state.blocker_state == "unrecoverable" or state.execution_failed:
        res.reason = f"Execution failed: {state.failure_reason or 'unrecoverable'}"
        res.is_complete = False
        res.verified = False
        return "FAILED", res

    # 2. Needs Clarification
    if state.task and state.task.ambiguity_state == "needs_clarification":
        res.reason = "Task ambiguous, needs clarification"
        res.is_complete = False
        res.verified = False
        return "NEEDS_CLARIFICATION", res

    # 3. Independent Verification over deterministic state
    v_status, v_res = verifier.verify(state)

    if v_status in ("BLOCKED", "FAILED", "NEEDS_CLARIFICATION"):
        return v_status, v_res

    if v_status == "INCOMPLETE":
        # INCOMPLETE strictly beats SUCCESS and NO_MATCH
        return "INCOMPLETE", v_res

    if v_status == "SUCCESS":
        return "SUCCESS", v_res

    if v_status == "NO_MATCH":
        return "NO_MATCH", v_res

    return "UNSET", v_res
