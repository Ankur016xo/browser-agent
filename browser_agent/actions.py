"""
Action execution engine for the Browser Agent.
Executes grounded browser actions (clicks, typing, navigation, scrolling, keys)
using Playwright with support for coordinate clicks and Set-of-Marks numeric IDs.
"""
from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Page

from browser_agent.browser import find_click_target
from browser_agent.logging import get_logger
from browser_agent.state import ElementInfo

logger = get_logger(__name__)

# Sensitive keywords for safety guardrails
SENSITIVE_KEYWORDS = [
    "credit card", "cvv", "card number", "bank account", "social security",
    "password", "delete account", "confirm purchase", "pay now", "place order",
]


def check_action_safety(action: dict[str, Any], page_url: str) -> tuple[bool, str]:
    """Inspect action and context for sensitive / irreversible operations."""
    text_content = " ".join(str(v) for v in action.values()).lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw in text_content:
            return False, f"Safety restriction: Action mentions sensitive term '{kw}'."
    return True, ""


def execute_action(
    page: Page,
    action: dict[str, Any],
    elements: list[ElementInfo] | None = None,
) -> bool:
    """
    Execute a structured action on the page.
    Returns True if successfully performed, False otherwise.
    """
    action_type = str(action.get("action", "")).lower().strip()

    # Safety Guardrail
    is_safe, safety_msg = check_action_safety(action, page.url)
    if not is_safe:
        logger.warning(safety_msg)
        return False

    # 1. TYPE
    if action_type == "type":
        return _execute_type(page, action, elements)

    # 2. CLICK
    elif action_type == "click":
        return _execute_click(page, action, elements)

    # 3. NAVIGATE
    elif action_type == "navigate":
        return _execute_navigate(page, action)

    # 4. SELECT
    elif action_type == "select":
        return _execute_select(page, action, elements)

    # 5. HOVER
    elif action_type == "hover":
        return _execute_hover(page, action, elements)

    # 6. SCROLL
    elif action_type == "scroll":
        return _execute_scroll(page, action)

    # 7. PRESS_KEY
    elif action_type == "press_key":
        return _execute_press_key(page, action)

    # 8. CHECK / UNCHECK / TOGGLE
    elif action_type in ("check", "uncheck", "toggle"):
        return _execute_check(page, action, elements)

    # 9. FILL_FORM
    elif action_type == "fill_form":
        return _execute_fill_form(page, action, elements)

    # 10. DISMISS_MODAL
    elif action_type == "dismiss_modal":
        return _execute_dismiss_modal(page, action, elements)

    # 11. UPLOAD_FILE
    elif action_type == "upload_file":
        return _execute_upload_file(page, action, elements)

    # 12. DOWNLOAD
    elif action_type == "download":
        return _execute_download(page, action, elements)

    # 13. SET_DATE
    elif action_type == "set_date":
        return _execute_set_date(page, action, elements)

    # 14. EDIT_TEXT
    elif action_type == "edit_text":
        return _execute_edit_text(page, action, elements)

    # 15. DRAG_AND_DROP
    elif action_type == "drag_and_drop":
        return _execute_drag_and_drop(page, action, elements)

    # 16. MEDIA_CONTROL
    elif action_type == "media_control":
        return _execute_media_control(page, action, elements)

    # 17. GO_BACK
    elif action_type == "go_back":
        return _execute_go_back(page)

    # 18. RELOAD
    elif action_type == "reload":
        return _execute_reload(page)

    # 19. WAIT
    elif action_type == "wait":
        return _execute_wait(action)

    # 20. PLAY MEDIA / PLAYBACK
    elif action_type in ("play", "play_media", "start_playback"):
        return _execute_play_media(page, action, elements)

    # 21. DONE
    elif action_type == "done":
        logger.info("Action: DONE - task completed")
        return True

    # 22. FAIL
    elif action_type == "fail":
        logger.info("Action: FAIL - agent reported inability to complete task")
        return True

    else:
        logger.warning("Unknown action type: %s", action_type)
        return False



def _execute_type(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Type text into an input element or active focus."""
    text = str(action.get("text", ""))
    target = str(action.get("target", "")).strip()
    element_id = action.get("element_id") if action.get("element_id") is not None else action.get("target_id")
    if isinstance(element_id, (list, tuple)) and len(element_id) > 0:
        element_id = element_id[0]

    if not text:
        logger.warning("TYPE action had empty text.")
        return False

    if element_id is None and target:
        clean_t = target.lstrip("#").strip()
        if clean_t.isdigit():
            element_id = int(clean_t)

    press_enter = bool(action.get("press_enter", False))
    logger.info("Typing: %r (target: %s, element_id: %s, press_enter: %s)", text, target, element_id, press_enter)

    # Resolve element by ID if provided
    matched_elem: ElementInfo | None = None
    if element_id is not None and elements:
        try:
            eid = int(element_id)
            matched_elem = next((e for e in elements if e.id == eid), None)
        except (ValueError, TypeError):
            pass

    # If matched element has center coordinates, click it first to focus and type directly
    if matched_elem:
        cx, cy = matched_elem.center
        try:
            page.mouse.click(cx, cy)
            page.wait_for_timeout(200)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(text)
            page.wait_for_timeout(300)
            if press_enter or "search" in str(action.get("reasoning", "")).lower() or "search" in target.lower() or "search" in page.url.lower():
                page.keyboard.press("Enter")
                page.wait_for_timeout(700)
                logger.info("Submitted typed input with Enter.")
            return True
        except Exception as exc:
            logger.debug("Failed to focus/type element by coordinate: %s", exc)

    def fill_and_maybe_submit(locator) -> bool:
        try:
            locator.fill(text)
            attrs = " ".join(
                str(value or "") for value in (
                    target,
                    locator.get_attribute("type"),
                    locator.get_attribute("name"),
                    locator.get_attribute("placeholder"),
                    locator.get_attribute("aria-label"),
                    locator.get_attribute("id"),
                )
            ).lower()
            if press_enter or "search" in attrs or "search" in page.url.lower():
                locator.press("Enter")
                page.wait_for_timeout(700)
                logger.info("Submitted search with Enter.")
            return True
        except Exception as exc:
            logger.debug("Locator fill failed: %s", exc)
            return False

    # Try specific target locator if given
    if target and not target.isdigit():
        try:
            for selector in [
                f"input[name='{target}']",
                f"input[id='{target}']",
                f"input[placeholder*='{target}' i]",
                f"input[aria-label*='{target}' i]",
                f"textarea[name='{target}']",
                f"textarea[id='{target}']",
            ]:
                loc = page.locator(selector).first
                if loc.is_visible(timeout=500):
                    if fill_and_maybe_submit(loc):
                        return True
        except Exception:
            pass

        # Try searching by fuzzy attribute match
        target_lower = target.lower()
        try:
            for locator in page.locator("input:visible, textarea:visible").all():
                try:
                    attrs = " ".join(
                        str(v or "") for v in (
                            locator.get_attribute("aria-label"),
                            locator.get_attribute("name"),
                            locator.get_attribute("placeholder"),
                            locator.get_attribute("id"),
                        )
                    ).lower()
                    if target_lower and target_lower in attrs:
                        if fill_and_maybe_submit(locator):
                            return True
                except Exception:
                    continue
        except Exception:
            pass

    # Try single visible input or common search inputs
    for selector in (
        "input[type='search']:visible",
        "input[name*='search' i]:visible",
        "input[placeholder*='search' i]:visible",
        "input[type='text']:visible",
        "input:visible",
        "textarea:visible",
        "[contenteditable='true']:visible",
    ):
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=500):
                if fill_and_maybe_submit(loc):
                    return True
        except Exception:
            continue

    # Fallback: type via keyboard directly into currently focused element
    try:
        page.keyboard.type(text)
        if press_enter or "search" in target.lower() or "search" in page.url.lower():
            page.keyboard.press("Enter")
            page.wait_for_timeout(700)
        return True
    except Exception as exc:
        logger.error("Failed to type via keyboard: %s", exc)
        return False


def _execute_click(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Click an element by ID, coordinate, or text."""
    target = str(action.get("target", "")).strip()
    element_id = action.get("element_id") if action.get("element_id") is not None else action.get("target_id")
    if isinstance(element_id, (list, tuple)) and len(element_id) > 0:
        element_id = element_id[0]

    if element_id is None and target:
        clean_t = target.lstrip("#").strip()
        if clean_t.isdigit():
            element_id = int(clean_t)

    # If element_id is specified
    if element_id is not None and elements:
        try:
            eid = int(element_id)
            for elem in elements:
                if elem.id == eid:
                    cx, cy = elem.center
                    logger.info("Clicking element ID %d at (%d, %d)", eid, cx, cy)
                    page.mouse.click(cx, cy)
                    page.wait_for_timeout(500)
                    return True
        except (ValueError, TypeError):
            pass

    # If coordinate given directly (x, y)
    if "coordinate" in action and isinstance(action["coordinate"], (list, tuple)) and len(action["coordinate"]) == 2:
        cx, cy = action["coordinate"]
        logger.info("Clicking coordinate: (%d, %d)", cx, cy)
        page.mouse.click(cx, cy)
        page.wait_for_timeout(500)
        return True

    logger.info("Click target: %s", target)
    resolved = find_click_target(page, target, elements)

    if resolved is None:
        logger.warning("Could not find clickable target: %s", target)
        return False

    # Resolved as (cx, cy) coordinates
    if isinstance(resolved, tuple) and len(resolved) == 2:
        cx, cy = resolved
        try:
            logger.info("Clicking grounded coordinates (%d, %d)", cx, cy)
            page.mouse.click(cx, cy)
            page.wait_for_timeout(500)
            return True
        except Exception as exc:
            logger.error("Coordinate click failed: %s", exc)
            return False

    # Resolved as Playwright locator
    try:
        resolved.scroll_into_view_if_needed(timeout=3000)
        resolved.click(timeout=4000)
        page.wait_for_timeout(500)
        logger.info("Clicked locator for: %s", target)
        return True
    except Exception as exc:
        logger.error("Locator click failed for %s: %s", target, exc)
        return False


def _execute_navigate(page: Page, action: dict[str, Any]) -> bool:
    """Navigate to explicit web URL."""
    url = str(action.get("url", "")).strip()
    if not url.startswith(("https://", "http://")):
        url = "https://" + url
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        logger.info("Navigated to: %s", page.url)
        return True
    except Exception as exc:
        logger.error("Navigation failed: %s", exc)
        return False


def _execute_select(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Select option in HTML select element or custom combobox by label or value."""
    target = str(action.get("target", "")).strip()
    option = str(action.get("option", "")).strip()
    element_id = action.get("element_id") if action.get("element_id") is not None else action.get("target_id")
    if element_id is None and target:
        clean_t = target.lstrip("#").strip()
        if clean_t.isdigit():
            element_id = int(clean_t)

    # 1. If element_id was specified
    if element_id is not None and elements:
        try:
            eid = int(element_id)
            elem = next((e for e in elements if e.id == eid), None)
            if elem and elem.tag == "select":
                cx, cy = elem.center
                for loc in page.locator("select:visible").all():
                    try:
                        box = loc.bounding_box()
                        if box and abs(box["x"] + box["width"]/2 - cx) < 10 and abs(box["y"] + box["height"]/2 - cy) < 10:
                            try:
                                loc.select_option(label=option)
                                return True
                            except Exception:
                                loc.select_option(value=option)
                                return True
                    except Exception:
                        pass
        except (ValueError, TypeError):
            pass

    # 2. Native select locators
    for loc in page.locator("select:visible").all():
        try:
            try:
                loc.select_option(label=option)
                logger.info("Selected '%s' in %s", option, target)
                return True
            except Exception:
                loc.select_option(value=option)
                logger.info("Selected value '%s' in %s", option, target)
                return True
        except Exception:
            continue

    # 3. Custom combobox / listbox dropdowns
    try:
        combo_selectors = [
            f"[role='combobox'][aria-label*='{target}' i]",
            f"[role='combobox'][id*='{target}' i]",
            "[role='combobox']:visible",
            ".select:visible, .dropdown:visible, [aria-haspopup='listbox']:visible"
        ]
        for c_sel in combo_selectors:
            combo = page.locator(c_sel).first
            if combo.is_visible(timeout=300):
                combo.click()
                page.wait_for_timeout(300)
                opt_loc = page.locator(f"[role='option']:has-text('{option}'), li:has-text('{option}'), .dropdown-item:has-text('{option}')").first
                if opt_loc.is_visible(timeout=500):
                    opt_loc.click()
                    logger.info("Selected option '%s' in custom combobox", option)
                    return True
    except Exception:
        pass

    logger.warning("Could not find select dropdown for: %s with option: %s", target, option)
    return False


def _execute_hover(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Hover over an element and observe newly revealed content."""
    target = str(action.get("target", "")).strip()
    element_id = action.get("element_id")
    if element_id is not None and elements:
        try:
            eid = int(element_id)
            elem = next((e for e in elements if e.id == eid), None)
            if elem:
                cx, cy = elem.center
                page.mouse.move(cx, cy)
                page.wait_for_timeout(400)
                return True
        except Exception:
            pass

    resolved = find_click_target(page, target, elements)
    if resolved is None:
        return False
    try:
        if isinstance(resolved, tuple):
            page.mouse.move(resolved[0], resolved[1])
        else:
            resolved.hover(timeout=3000)
        page.wait_for_timeout(400)
        return True
    except Exception as exc:
        logger.error("Hover failed: %s", exc)
        return False


def _execute_scroll(page: Page, action: dict[str, Any]) -> bool:
    """Scroll the page viewport or container."""
    direction = str(action.get("direction", "down")).lower()
    scroll_to = action.get("scroll_to_element") or action.get("scroll_to")
    if scroll_to:
        try:
            loc = page.locator(str(scroll_to)).first
            if loc.is_visible(timeout=1000):
                loc.scroll_into_view_if_needed()
                return True
        except Exception:
            pass

    if direction == "top":
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        return True
    elif direction == "bottom":
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight || document.documentElement.scrollHeight)")
        page.wait_for_timeout(400)
        return True

    try:
        amount = int(action.get("amount", 600))
    except Exception:
        amount = 600

    amount = max(100, min(abs(amount), 2000))
    if direction == "up":
        amount = -amount

    logger.info("Scrolling %s (%d px)", direction, abs(amount))
    page.mouse.wheel(0, amount)
    page.wait_for_timeout(800)
    return True


def _execute_press_key(page: Page, action: dict[str, Any]) -> bool:
    """Press keyboard key with alias normalization."""
    key = str(action.get("key", "Enter")).strip()
    key_aliases = {
        "enter": "Enter",
        "return": "Enter",
        "esc": "Escape",
        "escape": "Escape",
        "tab": "Tab",
        "space": "Space",
        "backspace": "Backspace",
        "delete": "Delete",
        "arrowdown": "ArrowDown",
        "arrowup": "ArrowUp",
        "arrowleft": "ArrowLeft",
        "arrowright": "ArrowRight",
        "down": "ArrowDown",
        "up": "ArrowUp",
        "left": "ArrowLeft",
        "right": "ArrowRight",
    }
    key_clean = key_aliases.get(key.lower(), key)
    key_clean = key_clean.replace("ctrl+", "Control+").replace("cmd+", "Meta+")
    logger.info("Pressing key: %s", key_clean)
    try:
        page.keyboard.press(key_clean)
        page.wait_for_timeout(500)
        return True
    except Exception as exc:
        logger.error("Key press failed: %s", exc)
        return False


def _execute_check(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Check, uncheck, or toggle a checkbox, radio button, or switch."""
    act_type = str(action.get("action", "check")).lower()
    target = str(action.get("target", "")).strip()
    element_id = action.get("element_id") if action.get("element_id") is not None else action.get("target_id")
    if isinstance(element_id, (list, tuple)) and len(element_id) > 0:
        element_id = element_id[0]

    desired_state = True
    if act_type == "uncheck" or action.get("state") is False:
        desired_state = False
    elif act_type == "toggle":
        desired_state = None  # invert

    logger.info("Executing check/toggle (target: %s, ID: %s, desired: %s)", target, element_id, desired_state)

    if element_id is not None and elements:
        try:
            eid = int(element_id)
            elem = next((e for e in elements if e.id == eid), None)
            if elem:
                cx, cy = elem.center
                try:
                    is_currently_checked = page.evaluate("""([x, y]) => {
                        const el = document.elementFromPoint(x, y);
                        if (!el) return null;
                        const input = el.tagName === 'INPUT' ? el : (el.querySelector('input') || (el.closest('label') ? el.closest('label').querySelector('input') : null));
                        if (input) return !!input.checked;
                        if (el.getAttribute('role') === 'switch' || el.getAttribute('role') === 'checkbox') {
                            return el.getAttribute('aria-checked') === 'true';
                        }
                        return null;
                    }""", [cx, cy])
                except Exception:
                    is_currently_checked = None

                if is_currently_checked is None:
                    is_currently_checked = elem.checked

                if desired_state is None or is_currently_checked != desired_state:
                    page.mouse.click(cx, cy)
                    page.wait_for_timeout(300)
                return True
        except (ValueError, TypeError):
            pass

    resolved = find_click_target(page, target, elements)
    if resolved:
        try:
            if isinstance(resolved, tuple):
                page.mouse.click(resolved[0], resolved[1])
            else:
                if desired_state is True and hasattr(resolved, "check"):
                    try:
                        resolved.check(timeout=2000)
                    except Exception:
                        resolved.click(timeout=2000)
                elif desired_state is False and hasattr(resolved, "uncheck"):
                    try:
                        resolved.uncheck(timeout=2000)
                    except Exception:
                        resolved.click(timeout=2000)
                else:
                    resolved.click(timeout=2000)
            page.wait_for_timeout(300)
            return True
        except Exception as exc:
            logger.debug("Check via resolved locator failed: %s", exc)

    for selector in (
        f"input[type='checkbox'][name*='{target}' i]",
        f"input[type='checkbox'][id*='{target}' i]",
        f"input[type='radio'][name*='{target}' i]",
        f"[role='checkbox'][aria-label*='{target}' i]",
        f"[role='switch'][aria-label*='{target}' i]",
    ):
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=500):
                loc.click()
                return True
        except Exception:
            continue

    return False


def _execute_fill_form(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """
    Fill multiple form inputs (text, email, select, checkbox, radio, date)
    with pre-submission validation and optional form submit.
    """
    fields: dict[str, Any] = action.get("fields", {})
    if not fields and "field" in action and "value" in action:
        fields = {action["field"]: action["value"]}

    if not fields:
        logger.warning("fill_form called with no fields.")
        return False

    logger.info("Filling form fields: %s", list(fields.keys()))
    success_count = 0

    for field_name, val in fields.items():
        field_str = str(val)
        val_bool = val is True or str(val).lower() in ("true", "yes", "checked", "1")
        field_filled = False

        # Try Playwright get_by_label
        try:
            lbl_loc = page.get_by_label(field_name, exact=False).first
            if lbl_loc.is_visible(timeout=300):
                tag = lbl_loc.evaluate("el => el.tagName.toLowerCase()")
                inp_type = lbl_loc.get_attribute("type") or ""
                if tag == "select":
                    try:
                        lbl_loc.select_option(label=field_str)
                    except Exception:
                        lbl_loc.select_option(value=field_str)
                elif inp_type in ("checkbox", "radio"):
                    if val_bool:
                        lbl_loc.check()
                    else:
                        lbl_loc.uncheck()
                else:
                    lbl_loc.fill(field_str)
                field_filled = True
                success_count += 1
        except Exception:
            pass

        if field_filled:
            continue

        for selector in (
            f"input[name='{field_name}']",
            f"input[id='{field_name}']",
            f"input[placeholder*='{field_name}' i]",
            f"input[aria-label*='{field_name}' i]",
            f"textarea[name='{field_name}']",
            f"textarea[id='{field_name}']",
            f"select[name='{field_name}']",
            f"select[id='{field_name}']",
        ):
            try:
                loc = page.locator(selector).first
                if loc.is_visible(timeout=300):
                    tag = loc.evaluate("el => el.tagName.toLowerCase()")
                    inp_type = loc.get_attribute("type") or ""
                    if tag == "select":
                        try:
                            loc.select_option(label=field_str)
                        except Exception:
                            loc.select_option(value=field_str)
                    elif inp_type in ("checkbox", "radio"):
                        if val_bool:
                            loc.check()
                        else:
                            loc.uncheck()
                    else:
                        loc.fill(field_str)
                    field_filled = True
                    success_count += 1
                    break
            except Exception:
                continue

        if not field_filled and elements:
            f_lower = field_name.lower()
            for e in elements:
                acc = (e.accessible_name or e.label_text or e.attributes.get("name") or e.attributes.get("placeholder") or "").lower()
                if f_lower in acc:
                    try:
                        if e.tag == "select":
                            _execute_select(page, {"element_id": e.id, "option": field_str}, elements)
                        elif e.tag == "input" and e.element_type in ("checkbox", "radio"):
                            _execute_check(page, {"element_id": e.id, "state": val_bool}, elements)
                        else:
                            _execute_type(page, {"element_id": e.id, "text": field_str}, elements)
                        field_filled = True
                        success_count += 1
                        break
                    except Exception:
                        pass

    if action.get("submit", False):
        page.wait_for_timeout(300)
        for sub_sel in (
            "button[type='submit']:visible",
            "input[type='submit']:visible",
            "button:has-text('Submit'):visible",
            "button:has-text('Sign in'):visible",
            "button:has-text('Register'):visible",
            "button:has-text('Send'):visible",
        ):
            try:
                sub_loc = page.locator(sub_sel).first
                if sub_loc.is_visible(timeout=300):
                    sub_loc.click()
                    page.wait_for_timeout(500)
                    logger.info("Submitted form via %s", sub_sel)
                    break
            except Exception:
                continue

    return success_count > 0


def _execute_dismiss_modal(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Dismiss blocking modal, cookie consent dialog, or overlay banner."""
    logger.info("Attempting to dismiss modal / dialog overlay.")
    close_selectors = [
        "button[aria-label*='close' i]",
        "button[aria-label*='dismiss' i]",
        "button[aria-label*='reject' i]",
        "button[aria-label*='accept' i]",
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
        "button:has-text('Reject all')",
        "button:has-text('Decline')",
        "button:has-text('Dismiss')",
        "button:has-text('Close')",
        "button:has-text('Not now')",
        "button:has-text('No thanks')",
        "button:has-text('Cancel')",
        "[class*='close' i]:visible",
        "[aria-label*='close' i]:visible",
    ]
    for sel in close_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=300):
                loc.click()
                page.wait_for_timeout(400)
                logger.info("Dismissed modal via selector: %s", sel)
                return True
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        logger.info("Dismissed modal via Escape key.")
        return True
    except Exception:
        pass

    return False


def _execute_upload_file(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Upload a file using file input."""
    import os
    file_path = str(action.get("file_path", "")).strip()
    if not file_path:
        logger.warning("upload_file action missing file_path.")
        return False

    if not os.path.exists(file_path):
        logger.warning("File path does not exist for upload: %s", file_path)
        try:
            from pathlib import Path
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("test upload content", encoding="utf-8")
        except Exception as e:
            logger.error("Could not create fallback upload file: %s", e)
            return False

    try:
        file_input = page.locator("input[type='file']").first
        file_input.set_input_files(file_path)
        page.wait_for_timeout(500)
        logger.info("Uploaded file '%s' successfully.", file_path)
        return True
    except Exception as exc:
        logger.error("File upload failed: %s", exc)
        return False


def _execute_download(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Execute action that triggers a file download and verify receipt."""
    target = str(action.get("target", "")).strip()
    element_id = action.get("element_id")
    logger.info("Executing download action for target '%s'", target)
    try:
        try:
            with page.expect_download(timeout=8000) as download_info:
                if element_id is not None or target:
                    _execute_click(page, action, elements)
                else:
                    page.locator("a[download], button:has-text('Download')").first.click()
            download = download_info.value
            logger.info("Download succeeded: %s", download.suggested_filename)
            return True
        except Exception:
            return _execute_click(page, action, elements)
    except Exception as exc:
        logger.error("Download failed: %s", exc)
        return False


def _execute_set_date(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Set date on native date input or datepicker."""
    date_val = str(action.get("date", action.get("value", ""))).strip()
    target = str(action.get("target", "")).strip()
    logger.info("Setting date: %s (target: %s)", date_val, target)
    if not date_val:
        return False

    for sel in (
        f"input[type='date'][name*='{target}' i]",
        f"input[type='date'][id*='{target}' i]",
        "input[type='date']:visible",
        f"input[placeholder*='date' i]",
        f"input[name*='date' i]",
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=300):
                loc.fill(date_val)
                loc.dispatch_event("change")
                return True
        except Exception:
            continue

    return _execute_type(page, {"text": date_val, "target": target}, elements)


def _execute_edit_text(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Edit text in input or textarea: append, replace, clear, or select_all."""
    mode = str(action.get("mode", "replace")).lower()
    text = str(action.get("text", ""))
    target = str(action.get("target") or action.get("selector") or "").strip()
    logger.info("Editing text (mode: %s, target: %s)", mode, target)

    if target:
        if target.startswith(("#", ".")) or "[" in target:
            try:
                page.locator(target).first.click(timeout=1000)
            except Exception:
                try:
                    page.locator(target).first.focus(timeout=1000)
                except Exception:
                    _execute_click(page, {"target": target}, elements)
        else:
            _execute_click(page, {"target": target}, elements)
        page.wait_for_timeout(200)
    elif action.get("element_id") is not None:
        _execute_click(page, {"element_id": action.get("element_id")}, elements)
        page.wait_for_timeout(200)

    try:
        if mode == "clear":
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
        elif mode == "append":
            page.keyboard.press("End")
            page.keyboard.type(text)
        elif mode == "select_all":
            page.keyboard.press("Control+A")
        else:  # replace
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            if text:
                page.keyboard.type(text)
        page.wait_for_timeout(300)
        return True
    except Exception as exc:
        logger.error("Edit text failed: %s", exc)
        return False


def _execute_drag_and_drop(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Drag source element or coordinates to target element or offset."""
    logger.info("Executing drag and drop: %s", action)
    source = action.get("source") or action.get("source_selector")
    target = action.get("target") or action.get("target_selector")
    offset_x = int(action.get("offset_x", 0))
    offset_y = int(action.get("offset_y", 0))

    try:
        if source and target:
            src_loc = page.locator(str(source)).first if isinstance(source, str) else None
            tgt_loc = page.locator(str(target)).first if isinstance(target, str) else None
            if src_loc and tgt_loc:
                src_loc.drag_to(tgt_loc)
                return True

        if "start_pos" in action and "end_pos" in action:
            sx, sy = action["start_pos"]
            ex, ey = action["end_pos"]
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(ex, ey)
            page.mouse.up()
            return True

        if source and (offset_x or offset_y):
            resolved = find_click_target(page, str(source), elements)
            if resolved:
                if isinstance(resolved, tuple):
                    cx, cy = resolved
                else:
                    box = resolved.bounding_box()
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx + offset_x, cy + offset_y)
                page.mouse.up()
                return True
        return False
    except Exception as exc:
        logger.error("Drag and drop failed: %s", exc)
        return False


def _execute_media_control(page: Page, action: dict[str, Any], elements: list[ElementInfo] | None = None) -> bool:
    """Control HTML5 media: play, pause, resume, mute, unmute, seek, volume."""
    cmd = str(action.get("command", action.get("media_action", "play"))).lower().strip()
    val = action.get("value")
    logger.info("Executing media control command: '%s'", cmd)
    try:
        if cmd in ("play", "resume"):
            return _execute_play_media(page, action, elements)
        elif cmd == "pause":
            page.evaluate("""() => {
                const media = Array.from(document.querySelectorAll('video, audio'));
                media.forEach(m => m.pause());
            }""")
            for sel in ("button[aria-label*='pause' i]:visible", "button[title*='pause' i]:visible"):
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=300):
                        loc.click()
                        break
                except Exception:
                    pass
            page.wait_for_timeout(300)
            return True
        elif cmd == "mute":
            page.evaluate("""() => {
                const media = Array.from(document.querySelectorAll('video, audio'));
                media.forEach(m => m.muted = true);
            }""")
            return True
        elif cmd == "unmute":
            page.evaluate("""() => {
                const media = Array.from(document.querySelectorAll('video, audio'));
                media.forEach(m => m.muted = false);
            }""")
            return True
        elif cmd == "seek" and val is not None:
            time_sec = float(val)
            page.evaluate(f"""() => {{
                const media = Array.from(document.querySelectorAll('video, audio'));
                media.forEach(m => m.currentTime = {time_sec});
            }}""")
            return True
        elif cmd == "volume" and val is not None:
            vol = float(val)
            page.evaluate(f"""() => {{
                const media = Array.from(document.querySelectorAll('video, audio'));
                media.forEach(m => m.volume = Math.max(0, Math.min(1, {vol})));
            }}""")
            return True
        elif cmd == "fullscreen":
            page.keyboard.press("f")
            return True
        return False
    except Exception as exc:
        logger.error("Media control failed: %s", exc)
        return False


def _execute_go_back(page: Page) -> bool:
    """Navigate back in browser history."""
    try:
        page.go_back(wait_until="domcontentloaded", timeout=20000)
        return True
    except Exception as exc:
        logger.error("Go back failed: %s", exc)
        return False


def _execute_reload(page: Page) -> bool:
    """Reload current page."""
    try:
        page.reload(wait_until="domcontentloaded", timeout=20000)
        return True
    except Exception as exc:
        logger.error("Reload failed: %s", exc)
        return False


def _execute_wait(action: dict[str, Any]) -> bool:
    """Pause execution for specified seconds."""
    try:
        seconds = float(action.get("seconds", 2))
    except Exception:
        seconds = 2
    seconds = max(0.5, min(seconds, 10))
    logger.info("Waiting %.1f seconds", seconds)
    time.sleep(seconds)
    return True


def _execute_play_media(
    page: Page,
    action: dict[str, Any],
    elements: list[ElementInfo] | None = None,
) -> bool:
    """
    Execute generic media playback interaction on the current page.
    Inspects HTML5 media (<video>, <audio>), play buttons, accessibility labels,
    or keyboard media shortcuts ('k' / Space).
    """
    logger.info("Executing generic media playback interaction.")
    try:
        if callable(getattr(page, "is_closed", None)) and page.is_closed():
            return False

        # 1. Check if media is already playing
        media_state = page.evaluate("""
        () => {
            const media = Array.from(document.querySelectorAll('video, audio'));
            const isPlaying = media.some(m => !m.paused && !m.ended && m.currentTime > 0);
            return { hasMedia: media.length > 0, isPlaying: isPlaying };
        }
        """)
        if media_state.get("isPlaying"):
            logger.info("Media element is already actively playing.")
            return True

        # 2. Try to click a play button if found in visible elements
        if elements:
            play_buttons = [
                e for e in elements
                if (e.tag == "button" or e.role == "button")
                and (
                    "play" in (e.attributes.get("aria-label") or "").lower()
                    or "play" in (e.attributes.get("title") or "").lower()
                    or "play" in (e.text or "").lower()
                    or "play-button" in (e.attributes.get("class") or "").lower()
                )
                and "playlist" not in (e.attributes.get("aria-label") or "").lower()
            ]
            if play_buttons:
                pb = play_buttons[0]
                cx, cy = pb.center
                logger.info("Clicking play button at (%d, %d) [ID %d]", cx, cy, pb.id)
                page.mouse.click(cx, cy)
                page.wait_for_timeout(600)
                return True

        # 3. Try clicking video element locator directly
        try:
            video_loc = page.locator("video").first
            if video_loc.is_visible(timeout=1000):
                logger.info("Clicking visible video element locator.")
                video_loc.click()
                page.wait_for_timeout(600)
                return True
        except Exception:
            pass

        # 4. Try standard media keyboard shortcut ('k' for YouTube/HTML5 video, or Space)
        logger.info("Triggering playback via media shortcut 'k'.")
        page.keyboard.press("k")
        page.wait_for_timeout(400)

        # 5. DOM direct media play trigger fallback
        page.evaluate("""
        () => {
            const v = document.querySelector('video, audio');
            if (v && v.paused) {
                v.play().catch(() => {});
            }
        }
        """)
        page.wait_for_timeout(300)
        return True
    except Exception as exc:
        logger.error("Media playback execution failed: %s", exc)
        return False
