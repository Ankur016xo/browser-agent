"""
Playwright browser utilities and robust controller for the Browser Agent.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from browser_agent.logging import get_logger
from browser_agent.state import ElementInfo, TabInfo

logger = get_logger(__name__)


class BrowserController:
    """Manages browser lifecycle, navigation, and robust page interactions."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def launch(self, start_url: str | None = None) -> Page:
        """Launch Playwright browser context and initialize active page."""
        b_cfg = self.config.get("browser", {})
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=b_cfg.get("headless", False)
        )
        self.context = self.browser.new_context(
            viewport={
                "width": b_cfg.get("viewport_width", 1280),
                "height": b_cfg.get("viewport_height", 800),
            },
            accept_downloads=True,
        )
        self.page = self.context.new_page()
        self.page._tab_id = "tab_0"

        # Handle dialogs (alerts, confirms, prompts) gracefully
        self.page.on("dialog", lambda dialog: dialog.accept())

        # Track newly opened tabs/popups (e.g. target="_blank" links)
        self.context.on("page", self._handle_new_tab)

        # Navigate to start URL if provided
        dest = start_url or b_cfg.get("start_url")
        if dest:
            self.goto(dest)

        return self.page

    start = launch

    def _handle_new_tab(self, new_page: Page) -> None:
        """Switch active tracking to new tab/popup if opened."""
        try:
            logger.info("New browser tab opened. Switching active focus.")
            new_page.on("dialog", lambda dialog: dialog.accept())
            new_page._tab_id = f"tab_{len(self.context.pages) if self.context else 1}"
            self.page = new_page
            try:
                new_page.bring_to_front()
            except Exception:
                pass
        except Exception as exc:
            logger.debug("Failed to switch to new tab: %s", exc)

    def get_active_page(self) -> Page | None:
        """Return currently active and valid page in context."""
        if self.context and self.context.pages:
            if self.page and not self.page.is_closed():
                return self.page
            # Fallback to the latest open page
            for p in reversed(self.context.pages):
                if not p.is_closed():
                    self.page = p
                    return self.page
        return self.page

    def get_tab_registry(self) -> list[TabInfo]:
        """Return registry of all open tabs."""
        tabs: list[TabInfo] = []
        if not self.context:
            return tabs
        for idx, p in enumerate(self.context.pages):
            if p.is_closed():
                continue
            p_id = getattr(p, "_tab_id", f"tab_{idx}")
            is_act = (p == self.page)
            t_url = getattr(p, "url", "")
            t_title = p.title() if callable(getattr(p, "title", None)) else ""
            tabs.append(TabInfo(
                page_id=p_id,
                url=t_url,
                title=t_title,
                is_active=is_act,
                current_state="active" if is_act else "background",
            ))
        return tabs

    def switch_tab(self, page_id_or_index: str | int) -> Page | None:
        """Switch active focus to tab by ID or index."""
        if not self.context or not self.context.pages:
            return self.page
        if isinstance(page_id_or_index, int):
            if 0 <= page_id_or_index < len(self.context.pages):
                self.page = self.context.pages[page_id_or_index]
        else:
            for p in self.context.pages:
                if getattr(p, "_tab_id", "") == page_id_or_index:
                    self.page = p
                    break
        if self.page and not self.page.is_closed():
            try:
                self.page.bring_to_front()
            except Exception:
                pass
        return self.page

    def new_tab(self, url: str = "") -> Page | None:
        """Open a new browser tab in the current context."""
        if not self.context:
            return self.page
        new_p = self.context.new_page()
        new_p.on("dialog", lambda dialog: dialog.accept())
        new_p._tab_id = f"tab_{len(self.context.pages)}"
        self.page = new_p
        if url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            self.goto(url)
        return self.page

    def close_active_tab(self) -> Page | None:
        """Close current active tab and return previous page if available."""
        try:
            if self.context and len(self.context.pages) > 1:
                cur = self.page
                # Switch to previous page
                remaining = [p for p in self.context.pages if p != cur and not p.is_closed()]
                if cur and not cur.is_closed():
                    cur.close()
                if remaining:
                    self.page = remaining[-1]
                    try:
                        self.page.bring_to_front()
                    except Exception:
                        pass
                    return self.page
        except Exception as exc:
            logger.debug("Failed to close active tab: %s", exc)
        return self.get_active_page()

    def goto(self, url: str) -> bool:
        """Navigate to URL with retry and sensible timeout."""
        page = self.get_active_page()
        if not page:
            return False
        try:
            logger.info("Navigating to: %s", url)
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            load_wait = self.config.get("browser", {}).get("page_load_timeout", 1500)
            page.wait_for_timeout(load_wait)
            return True
        except Exception as exc:
            logger.error("Navigation to %s failed: %s", url, exc)
            return False

    def close(self) -> None:
        """Clean up all browser resources safely."""
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None


def find_click_target(page: Page, target: str, elements: list[ElementInfo] | None = None) -> Any | None:
    """
    Find a clickable Playwright locator matching the target description or numeric ID
    using 6-tier candidate ranking and accessibility grounding.
    """
    target = str(target or "").strip()
    if not target:
        return None

    # Tier 1: Numeric ID (Set-of-Marks label)
    if elements:
        try:
            target_id = int(target.strip("[]# "))
            for elem in elements:
                if elem.id == target_id:
                    cx, cy = elem.center
                    if cx > 0 and cy > 0:
                        logger.debug("Resolved element ID %d at (%d, %d)", target_id, cx, cy)
                        return (cx, cy)
        except ValueError:
            pass

    clean_target = " ".join(target.split())
    target_lower = clean_target.lower()

    # Tier 2: Accessible Name Match in Extracted Elements
    if elements:
        for elem in elements:
            acc_name = (elem.accessible_name or elem.label_text or "").strip().lower()
            if acc_name and (acc_name == target_lower or target_lower in acc_name):
                cx, cy = elem.center
                if cx > 0 and cy > 0:
                    logger.debug("Resolved accessible name '%s' for target '%s' to ID %d at (%d, %d)", acc_name, target, elem.id, cx, cy)
                    return (cx, cy)

    # Tier 3: Role-specific locator match (link, button, tab, checkbox, radio, menuitem, option)
    for role in ("link", "button", "tab", "checkbox", "radio", "menuitem", "option"):
        try:
            locator = page.get_by_role(role, name=clean_target, exact=True).first
            if locator.is_visible(timeout=300):
                return locator
        except Exception:
            pass

    # Tier 4: Exact text match
    try:
        locator = page.get_by_text(clean_target, exact=True).first
        if locator.is_visible(timeout=300):
            return locator
    except Exception:
        pass

    # Tier 5: Fuzzy regex text match & token containment
    try:
        locator = page.get_by_text(re.compile(re.escape(clean_target), re.IGNORECASE)).first
        if locator.is_visible(timeout=300):
            return locator
    except Exception:
        pass

    # Tier 6: Extracted elements text containment
    if elements:
        for elem in elements:
            elem_text = (elem.text or "").strip().lower()
            if elem_text and target_lower in elem_text:
                cx, cy = elem.center
                if cx > 0 and cy > 0:
                    logger.debug("Fuzzy matched element text '%s' to ID %d at (%d, %d)", elem.text[:30], elem.id, cx, cy)
                    return (cx, cy)

    # Fallback: visible anchor or button containing keywords
    try:
        for selector in ("a:visible", "button:visible", "[role='button']:visible", "[role='tab']:visible"):
            for loc in page.locator(selector).all():
                try:
                    loc_text = (loc.inner_text() or loc.get_attribute("aria-label") or "").strip().lower()
                    if target_lower in loc_text:
                        return loc
                except Exception:
                    continue
    except Exception:
        pass

    logger.warning("Could not find clickable target: %s", target)
    return None


def get_visible_links(page: Page, max_links: int = 30) -> list[dict]:
    """Extract visible links from the page."""
    links = []
    try:
        for element in page.locator("a:visible").all():
            try:
                text = element.inner_text().strip()
                href = element.get_attribute("href")
                if text and len(text) <= 150:
                    links.append({"text": text, "href": href})
            except Exception:
                pass
    except Exception:
        pass

    unique = []
    seen = set()
    for link in links:
        key = (link["text"], link["href"])
        if key not in seen:
            seen.add(key)
            unique.append(link)
    return unique[:max_links]


def get_visible_buttons(page: Page, max_buttons: int = 20) -> list[str]:
    """Extract visible button texts from the page."""
    buttons = []
    try:
        for element in page.locator("button:visible, [role='button']:visible").all():
            try:
                text = element.inner_text().strip() or element.get_attribute("aria-label") or element.get_attribute("title")
                if text and len(text) <= 100:
                    buttons.append(text.strip())
            except Exception:
                pass
    except Exception:
        pass
    return list(dict.fromkeys(buttons))[:max_buttons]


def get_page_context(page: Page) -> tuple[str, list[dict], list[str]]:
    """Return human/model readable page context."""
    links = get_visible_links(page)
    buttons = get_visible_buttons(page)

    link_text = "\n".join(f"{i}. {link['text']}" for i, link in enumerate(links, start=1))
    button_text = "\n".join(f"- {button}" for button in buttons)

    context = f"""
CURRENT URL:
{page.url}

CURRENT PAGE TITLE:
{page.title()}

VISIBLE LINKS:
{link_text or "None"}

VISIBLE BUTTONS:
{button_text or "None"}
""".strip()

    return context, links, buttons


def create_browser(config: dict[str, Any]):
    """Convenience helper for creating browser (backward compatibility)."""
    controller = BrowserController(config)
    page = controller.launch()
    return controller.playwright, controller.browser, page


def close_browser(p: Any, browser: Any) -> None:
    """Convenience helper for closing browser (backward compatibility)."""
    try:
        if browser:
            browser.close()
    except Exception:
        pass
    try:
        if p:
            p.stop()
    except Exception:
        pass
