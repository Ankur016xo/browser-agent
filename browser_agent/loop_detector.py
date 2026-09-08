"""
Loop Detection and Error Recovery Engine.
Monitors agent action sequences, state changes, and DOM hashes to detect
stuck loops and trigger intelligent recovery strategies.
"""
from __future__ import annotations

import re
from typing import Any

from browser_agent.logging import get_logger
from browser_agent.state import ActionRecord, AgentMemory

logger = get_logger(__name__)


def actions_equivalent(act1: dict[str, Any] | None, act2: dict[str, Any] | None) -> bool:
    if not act1 or not act2:
        return False
    return (
        act1.get("action") == act2.get("action")
        and act1.get("direction") == act2.get("direction")
        and act1.get("target") == act2.get("target")
        and act1.get("element_id") == act2.get("element_id")
        and act1.get("text") == act2.get("text")
    )


class LoopDetector:
    """Detects repeated or cyclical actions and offers recovery recommendations."""

    def __init__(self, max_identical_actions: int = 2, max_consecutive_failures: int = 3) -> None:
        self.max_identical_actions = max_identical_actions
        self.max_consecutive_failures = max_consecutive_failures

    def check_loop(self, memory: AgentMemory, proposed_action: dict[str, Any]) -> tuple[bool, str]:
        """
        Check if the proposed action is part of an unproductive loop.
        Returns (is_loop: bool, recovery_advice: str).
        """
        history = memory.action_history
        if not history:
            return False, ""

        # Check 1: Repeating the same action that just failed or caused no state change
        last_rec = history[-1]
        is_same_action = actions_equivalent(last_rec.action, proposed_action)

        if is_same_action and (not last_rec.success or not last_rec.state_change):
            memory.identical_action_count += 1
            if memory.identical_action_count >= self.max_identical_actions:
                target = proposed_action.get("target") or proposed_action.get("element_id")
                advice = (
                    f"Action '{proposed_action.get('action')}' on target '{target}' has already been attempted "
                    f"{memory.identical_action_count} times without producing any page change. "
                    "DO NOT repeat this action. Check if the requested information is already visible on the current page. "
                    "If YES, return action 'done'. Otherwise choose a different element ID, scroll, or take an alternative step."
                )
                logger.warning("Repeated failed action loop detected: %s", advice)
                return True, advice
        else:
            memory.identical_action_count = 0

        # Check 2: Consecutive action failures
        if memory.consecutive_failed_actions >= self.max_consecutive_failures:
            advice = (
                f"The last {memory.consecutive_failed_actions} consecutive actions all failed or produced no state change. "
                "Re-evaluate the visible elements carefully. If the desired element is not visible, "
                "use 'scroll' or 'wait'."
            )
            logger.warning("Consecutive failure threshold reached: %s", advice)
            return True, advice

        # Check 3: URL oscillation / repeating visited URLs without navigating away
        recent_urls = [rec.url_after for rec in history if rec.url_after]
        if len(recent_urls) >= 3:
            last_url = recent_urls[-1]
            recent_recs = history[-3:]
            # Flag if the last 3 consecutive states were stuck on the exact same URL without progress/state change
            no_progress = all(not rec.state_change or not rec.success for rec in recent_recs)
            if recent_urls[-3:] == [last_url, last_url, last_url] and no_progress:
                advice = (
                    f"The agent has remained on URL '{last_url}' for 3 consecutive actions without progress. "
                    "You are in a navigation loop. If the goal is satisfied, return action 'done'. "
                    "Otherwise, select an action other than clicking links that return to this page."
                )
                logger.warning("URL loop detected: %s", advice)
                return True, advice

        # Check 4: Action oscillation cycle (A -> B -> A -> B or A -> B -> A and proposed B)
        if len(history) >= 4:
            a1 = history[-1].action
            b1 = history[-2].action
            a2 = history[-3].action
            b2 = history[-4].action
            if actions_equivalent(a1, a2) and actions_equivalent(b1, b2):
                advice = (
                    "Oscillating loop detected between two actions. "
                    "Stop switching between these actions. If the information is visible, return 'done', "
                    "otherwise choose a completely different action."
                )
                logger.warning("Oscillation loop detected: %s", advice)
                return True, advice
        if len(history) >= 3:
            a1 = history[-1].action
            b1 = history[-2].action
            a2 = history[-3].action
            if actions_equivalent(a1, a2) and actions_equivalent(b1, proposed_action):
                advice = (
                    "Oscillating loop detected: proposed action continues oscillation cycle. "
                    "Choose a completely different action or navigate."
                )
                logger.warning("Oscillation loop detected with proposed action: %s", advice)
                return True, advice

        return False, ""

    def get_recovery_action(
        self,
        memory: AgentMemory,
        elements: list[ElementInfo],
        page: Any,
        failed_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate a structured recovery action that is logically different from the failed action.
        Follows priority:
        1. Inspect current content if on target page.
        2. Scroll down / up if on article or results page.
        3. Choose an alternative relevant element.
        4. Submit with 'Enter' key if click on search button failed.
        5. Navigate back or wait.
        """
        failed_act_type = (failed_action.get("action") if failed_action else "").lower()
        failed_target_id = failed_action.get("element_id") if failed_action else None

        curr_url = getattr(page, "url", "").lower()

        # 0. Check if any procedural requirement is pending - highest priority
        if memory.task_plan and getattr(memory.task_plan, "procedural_requirements", None):
            memory.is_procedure_satisfied(page)
            next_proc = memory.current_procedure
            if next_proc and next_proc not in getattr(memory, "failed_procedures", []):
                proc_lower = next_proc.lower()

                # If next is go_back, execute go_back
                if any(v in proc_lower for v in ["go back", "navigate back", "return"]):
                    return {
                        "action": "go_back",
                        "reasoning": f"Loop recovery: executing pending procedural requirement: {next_proc}",
                        "confidence": 0.95,
                    }

                # If next is click, inspect DOM
                if any(v in proc_lower for v in ["click", "press", "select"]):
                    m = re.search(r"\b(?:called|titled|named)\s+[\"']?([^\"'\n\r]+)[\"']?", next_proc, re.I)
                    target_txt = m.group(1).strip().lower() if m else re.sub(r"^(?:click|press|select)\s+(?:on\s+)?(?:the\s+|a\s+)?(?:link\s+|button\s+)?", "", next_proc, flags=re.I).strip().lower()
                    target_txt = target_txt.strip("\"'")

                    from browser_agent.exploration import inspect_procedural_element
                    dom_info = inspect_procedural_element(page, target_txt, elements)

                    if not dom_info.get("exists", False):
                        if not hasattr(memory, "failed_procedures"):
                            memory.failed_procedures = []
                        memory.failed_procedures.append(next_proc)
                        return {
                            "action": "fail",
                            "reasoning": f"Loop recovery: procedural element '{target_txt}' does not exist on page. Terminating impossible procedure search.",
                            "confidence": 0.95,
                        }

                    # If exists and in viewport: click it
                    if dom_info.get("inViewport", False):
                        matching_elem = next(
                            (e for e in elements if target_txt in (e.text or "").lower() or (e.attributes.get("title") or "").lower() == target_txt),
                            None
                        )
                        eid = matching_elem.id if matching_elem else None
                        return {
                            "action": "click",
                            "element_id": eid,
                            "target": target_txt,
                            "reasoning": f"Loop recovery: clicking procedural target '{target_txt}' (found in viewport)",
                            "confidence": 0.95,
                        }

                    # If exists outside viewport: scroll in that direction (DO NOT alternate!)
                    s_dir = dom_info.get("scrollDirection", "down")
                    s_dist = dom_info.get("scrollDistance", 600)
                    if s_dir not in ("up", "down"):
                        s_dir = "down"
                    if s_dist <= 0:
                        s_dist = 600
                    return {
                        "action": "scroll",
                        "direction": s_dir,
                        "amount": s_dist,
                        "reasoning": f"Loop recovery: scrolling {s_dir} toward procedural target '{target_txt}' ({s_dist}px).",
                        "confidence": 0.9,
                    }

        # 1. If click on search button/input failed repeatedly, try Enter key or scroll
        if failed_act_type == "click":
            # If clicked an input or button and didn't submit, try Enter key
            if any(e.id == failed_target_id and (e.tag in ("input", "button") or "search" in (e.text or "").lower()) for e in elements):
                return {
                    "action": "press_key",
                    "key": "Enter",
                    "reasoning": "Loop recovery: previous click produced no page change; pressing Enter to submit search.",
                    "confidence": 0.9,
                }

            # If on content/article page, scroll to inspect
            if not memory.scroll_state.reached_bottom:
                return {
                    "action": "scroll",
                    "direction": "down",
                    "amount": 600,
                    "reasoning": "Loop recovery: click failed to make progress; scrolling down to inspect content below the fold.",
                    "confidence": 0.85,
                }
            elif not memory.scroll_state.reached_top:
                return {
                    "action": "scroll",
                    "direction": "up",
                    "amount": 600,
                    "reasoning": "Loop recovery: reached bottom; scrolling up to inspect remaining sections.",
                    "confidence": 0.8,
                }

        # 2. If scroll produced no change, switch direction or select unvisited link
        if failed_act_type == "scroll":
            failed_dir = (failed_action.get("direction") if failed_action else "down").lower()
            if failed_dir == "down" and not memory.scroll_state.reached_top:
                return {
                    "action": "scroll",
                    "direction": "up",
                    "amount": 600,
                    "reasoning": "Loop recovery: page bottom reached; scrolling up to explore alternate sections.",
                    "confidence": 0.8,
                }

        # 3. Check if on target page
        is_target_sat, _ = memory.is_target_page_satisfied(page)

        if is_target_sat:

            # On target page without procedural link match: DO NOT navigate away to arbitrary pages!
            # If not at scroll boundary, scroll to explore content on this page
            if not memory.scroll_state.reached_bottom:
                return {
                    "action": "scroll",
                    "direction": "down",
                    "amount": 600,
                    "reasoning": "Loop recovery: remaining on satisfied target page; scrolling down to inspect content.",
                    "confidence": 0.85,
                }
            elif not memory.scroll_state.reached_top:
                return {
                    "action": "scroll",
                    "direction": "up",
                    "amount": 600,
                    "reasoning": "Loop recovery: remaining on satisfied target page; scrolling up to inspect alternate sections.",
                    "confidence": 0.8,
                }

            # At boundaries on target page: wait for page stabilization, do NOT abandon target
            return {
                "action": "wait",
                "seconds": 2,
                "reasoning": "Loop recovery: remaining on satisfied target page; waiting for page elements to stabilize.",
                "confidence": 0.6,
            }

        # 4. If on search results or listing page, select the best candidate content item
        from browser_agent.exploration import select_best_candidate_link
        exclude_eids = {rec.action.get("element_id") for rec in memory.action_history[-4:] if rec.action.get("element_id") is not None}
        if failed_target_id is not None:
            exclude_eids.add(failed_target_id)

        candidate_action = select_best_candidate_link(
            elements,
            query=memory.normalized_query,
            target=memory.task_plan.target if memory.task_plan else "",
            procedure=memory.current_procedure or "",
            exclude_ids=exclude_eids,
        )
        if candidate_action:
            candidate_action["reasoning"] = f"Loop recovery: {candidate_action['reasoning']}"
            return candidate_action

        # Scroll to reveal new content if not at bottom
        if not memory.scroll_state.reached_bottom:
            return {
                "action": "scroll",
                "direction": "down",
                "amount": 600,
                "reasoning": "Loop recovery: scrolling to reveal additional content items.",
                "confidence": 0.8,
            }

        # 5. Fallback: wait for page stabilization
        return {
            "action": "wait",
            "seconds": 2,
            "reasoning": "Loop recovery: waiting for page elements to stabilize.",
            "confidence": 0.5,
        }


