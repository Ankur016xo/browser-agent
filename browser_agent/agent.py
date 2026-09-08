"""
Core Browser Agent orchestration loop and state machine.
Integrates perception, reasoning, action execution, verification, memory,
loop detection, and thread-safe execution controls (pause/resume/stop).
"""
from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from browser_agent.actions import execute_action
from browser_agent.browser import BrowserController
from browser_agent.config import get_config, reset_config
from browser_agent.constraints import (
    TaskConstraints,
    check_feature_present,
    evaluate_candidate,
    extract_task_constraints,
    parse_numeric_price,
    parse_numeric_rating,
    pick_best_ranked_candidate,
)
from browser_agent.logging import get_logger, setup_logging
from browser_agent.loop_detector import LoopDetector
from browser_agent.perception import PerceptionEngine
from browser_agent.state import ActionRecord, AgentMemory, AgentState, ElementInfo, PageState
from browser_agent.verifier import ActionVerifier
from browser_agent.vision import (
    ask_vision_model,
    summarize_task_result,
    take_screenshot,
    verify_task_completion,
)
from browser_agent.exploration import (
    choose_goal_exploration_action,
    find_candidate_content_items,
    select_best_candidate_link,
)

logger = get_logger(__name__)


def is_page_alive(page: Any) -> bool:
    """Check if page is non-null, open, and responsive."""
    if page is None:
        return False
    try:
        is_closed_fn = getattr(page, "is_closed", None)
        if callable(is_closed_fn) and is_closed_fn() is True:
            return False
        return True
    except Exception:
        return False


def safe_page_title(page: Any) -> str:
    """Safely obtain page title without raising TargetClosedError."""
    if not is_page_alive(page):
        return ""
    try:
        t = getattr(page, "title", None)
        if callable(t):
            res = t()
            if isinstance(res, str):
                return res
            if hasattr(res, "_mock_name"):  # unconfigured mock
                return ""
            return str(res) if res is not None else ""
        return str(t) if t is not None else ""
    except Exception:
        return ""


def safe_page_url(page: Any) -> str:
    """Safely obtain page URL without raising TargetClosedError."""
    if not is_page_alive(page):
        return ""
    try:
        u = getattr(page, "url", "")
        if callable(u):
            res = u()
            if isinstance(res, str):
                return res
            if hasattr(res, "_mock_name"):
                return ""
            return str(res) if res is not None else ""
        if isinstance(u, str):
            return u
        if hasattr(u, "_mock_name"):
            return ""
        return str(u) if u is not None else ""
    except Exception:
        return ""


def is_page_actively_loading(page: Any) -> bool:
    """Check if page DOM indicates ongoing loading/spinners."""
    if not is_page_alive(page) or not hasattr(page, "evaluate"):
        return False
    try:
        res = page.evaluate("""() => {
            if (document.readyState !== 'complete') return true;
            const busy = document.querySelector('[aria-busy="true"], [role="progressbar"], .spinner, .loading, .skeleton');
            return !!busy;
        }""")
        return res is True or (isinstance(res, bool) and res)
    except Exception:
        return False


KNOWN_DESTINATIONS = {
    "flipkart": "https://www.flipkart.com",
    "amazon": "https://www.amazon.in",
    "wikipedia": "https://www.wikipedia.org",
    "youtube": "https://www.youtube.com",
    "github": "https://www.github.com",
    "reddit": "https://www.reddit.com",
    "duckduckgo": "https://duckduckgo.com",
    "google": "https://www.google.com",
    "bing": "https://www.bing.com",
}

# Default exploration budget (max unique candidates inspected)
DEFAULT_EXPLORATION_BUDGET = 30


def extract_destination_url(task: str) -> str | None:
    """
    Extract destination URL from explicit URL or recognized platform in the task string.
    Examples:
        'Open https://example.com and check heading' -> 'https://example.com'
        'Go to Flipkart and find laptop bags' -> 'https://www.flipkart.com'
        'Open Amazon and find headphones' -> 'https://www.amazon.in'
        'Search DuckDuckGo for Python' -> 'https://duckduckgo.com'
    """
    # 1. Explicit http(s) URL
    match = re.search(r"https?://[^\s<>()]+", task, re.IGNORECASE)
    if match:
        return match.group(0).rstrip(".,!?'")

    # 1b. Domain like example.com
    domain_match = re.search(r"\b([a-zA-Z0-9\-]+\.(?:com|org|net|edu|gov|io|ai|in|co))\b", task, re.IGNORECASE)
    if domain_match:
        dom = domain_match.group(1).lower()
        if dom not in ("duckduckgo.com", "google.com", "bing.com"):
            return f"https://{dom}"

    # 2. Known destination keyword
    task_lower = task.lower()
    for name, url in KNOWN_DESTINATIONS.items():
        if re.search(rf"\b(?:go\s+to|open|visit|navigate\s+to|search\s+on|on|in)\s+{name}\b", task_lower) or re.search(rf"\b{name}\b", task_lower):
            return url

    return None


KNOWN_PLATFORMS_REGEX = r"(?:google|duckduckgo|bing|yahoo|flipkart|amazon|youtube|wikipedia|github|reddit|ebay|walmart)"


from browser_agent.planner import TaskPlan, parse_task_plan
from browser_agent.exploration import (
    choose_goal_exploration_action,
    find_matching_target_link,
    inspect_page_for_requested_info,
    is_page_relevant_to_target,
)


def normalize_task(task: str) -> str:
    """
    Extract the core search item/term from a natural-language task instruction.
    Uses structured TaskPlan to ensure target entity is preserved.
    """
    plan = parse_task_plan(task)
    return plan.search_query or task.strip()


def find_product_links(elements: list[ElementInfo]) -> list[ElementInfo]:
    """
    Find elements that link directly to individual product detail pages (/p/, /dp/, pid=).
    Strictly filters out category navigation, breadcrumbs, search filters, and boilerplate links.
    """
    CATEGORY_BLACKLIST = {
        "bags, wallets & belts", "bags", "wallets", "belts", "explore plus", "become a seller",
        "cart", "top offers", "grocery", "mobiles", "fashion", "electronics",
        "home & furniture", "appliances", "travel", "beauty, toys & more",
        "two wheelers", "filters", "clear all", "sort by", "relevance",
        "popularity", "price -- low to high", "price -- high to low",
        "newest first", "help center", "about us", "terms of use", "privacy policy",
        "login", "sign in", "request otp", "flipkart", "amazon", "all categories", "view all",
        "men's bags", "women's bags", "luggage & travel"
    }

    product_links = []
    for elem in elements:
        if elem.tag != 'a':
            continue
        href = (elem.attributes.get('href') or "").lower()
        text = (elem.text or "").strip().lower()

        # Reject blacklisted categories and breadcrumbs
        if text in CATEGORY_BLACKLIST:
            continue
        if any(cat == text for cat in CATEGORY_BLACKLIST):
            continue
        if any(cat in href for cat in ["/bags-wallets-belts", "/pr?sid=", "/categorytree", "otracker=categorytree"]):
            continue

        # Reject search query suggestions / augment links
        if any(seg in href for seg in ["/search?", "augment=", "as-show="]) and not any(seg in href for seg in ["/p/", "/dp/", "pid="]):
            continue

        # Check positive product indicators: /p/, /dp/, pid=
        is_product_url = any(seg in href for seg in ["/p/", "/dp/", "pid=", "/product/"])
        if not is_product_url:
            continue

        # Ensure element text is informative if it was blank
        if not elem.text.strip():
            fallback_title = elem.attributes.get('title') or elem.attributes.get('aria-label') or ''
            if not fallback_title and href:
                slug_match = re.search(r"/([a-zA-Z0-9_-]{5,80})(?:/p/|/dp/|\?|$)", href)
                if slug_match:
                    fallback_title = re.sub(r"[-_]+", " ", slug_match.group(1)).title()
            if fallback_title:
                elem.text = fallback_title

        product_links.append(elem)

    return product_links


def find_organic_search_results(elements: list[ElementInfo], query: str) -> list[ElementInfo]:
    """
    Find external search result links on search engine pages (DuckDuckGo, Google, Bing).
    Filters out internal search engine query links, subdomains, sidebars, and control buttons.
    """
    SEARCH_CONTROLS = {
        "search domain", "search for", "related search", "search assist", "all regions", "any time",
        "safe search", "privacy policy", "terms of", "help center", "feedback", "settings", "images",
        "videos", "news", "maps", "login", "sign in", "duck.ai", "chat", "more"
    }
    SEARCH_ENGINES = ["duckduckgo.com", "duck.ai", "google.com", "bing.com", "yahoo.com", "yandex.com", "baidu.com"]

    q_words = [w.lower() for w in query.split() if len(w) > 2]
    scored: list[tuple[ElementInfo, int]] = []

    for elem in elements:
        if elem.tag != 'a':
            continue
        href = (elem.attributes.get('href') or "").lower()
        text = (elem.text or "").strip().lower()

        if len(text) < 4:
            continue
        if any(se in href for se in SEARCH_ENGINES):
            continue
        if href.startswith("javascript:") or href.startswith("#") or href.startswith("/?") or "q=" in href:
            continue
        if any(c in text for c in SEARCH_CONTROLS):
            continue

        score = sum(1 for w in q_words if w in text or w in href)
        if score > 0:
            scored.append((elem, score))

    if scored:
        scored.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored]
    return []


class BrowserAgent:
    """Orchestrates the intelligent visual browser agent loop."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        on_state_change: Callable[[AgentState], None] | None = None,
        on_step: Callable[[int, int], None] | None = None,
        on_perceive: Callable[[list[ElementInfo]], None] | None = None,
        on_action: Callable[[ActionRecord], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config or get_config()
        self.on_state_change = on_state_change
        self.on_step = on_step
        self.on_perceive = on_perceive
        self.on_action = on_action
        self.on_log = on_log

        self.state = AgentState.IDLE
        self.memory = AgentMemory()
        self.controller = BrowserController(self.config)
        self.perception = PerceptionEngine()
        self.verifier = ActionVerifier()
        self.loop_detector = LoopDetector()
        self.constraints = TaskConstraints()
        self.evaluated_candidates: set[str] = set()
        self.evaluated_candidate_details: list[dict[str, Any]] = []
        # Exploration budget: maximum number of UNIQUE candidates inspected
        self.exploration_budget: int = DEFAULT_EXPLORATION_BUDGET
        # Requested quantity (valid candidates needed). Will be set after task parsing.
        self.requested_quantity: int = 0
        self.candidates_inspected: int = 0
        self.valid_candidates_found: int = 0
        self.search_exhausted: bool = False
        self.budget_exhausted: bool = False
        self.consecutive_vlm_failures: int = 0


        # Thread-safe execution controls
        self._stop_requested = threading.Event()
        self._pause_requested = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()  # Not paused by default
        self._lock = threading.Lock()

    def set_state(self, state: AgentState) -> None:
        """Update current agent state and trigger listeners."""
        with self._lock:
            self.state = state
        logger.debug("State -> %s", state.value)
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception as exc:
                logger.debug("on_state_change callback error: %s", exc)

    def log(self, message: str) -> None:
        """Log message and forward to listener."""
        logger.info(message)
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    def pause(self) -> None:
        """Pause agent execution before the next action."""
        self._pause_requested.set()
        self._resume_event.clear()
        self.set_state(AgentState.PAUSED)
        self.log("Agent paused by user.")

    def resume(self) -> None:
        """Resume agent execution from paused state."""
        self._pause_requested.clear()
        self._resume_event.set()
        self.set_state(AgentState.OBSERVING)
        self.log("Agent resumed.")

    def stop(self) -> None:
        """Stop agent execution immediately."""
        self._stop_requested.set()
        self.set_state(AgentState.STOPPED)
        self.log("Agent stopped by user.")

    def _ground_page_metadata(self, page: Any, elements: list[ElementInfo] | None = None) -> None:
        """Inspect active page and ground requested factual attributes (heading, title, URL, product info)."""
        if not is_page_alive(page):
            return
        task_lower = self.memory.task.lower()
        curr_url = safe_page_url(page)
        curr_title = safe_page_title(page)

        # Don't auto-extract from search engine root or search results pages if task has search/navigation intent
        is_search_engine = any(se in curr_url.lower() for se in ["duckduckgo.com", "google.com", "bing.com", "yahoo.com"])
        has_search_intent = bool(self.memory.normalized_query and self.memory.normalized_query != self.memory.task)
        if is_search_engine and has_search_intent:
            return

        updates: dict[str, Any] = {}
        if ("page title" in task_lower or "title of the page" in task_lower or "title" in task_lower) and curr_title:
            updates["page_title"] = curr_title
        if "url" in task_lower and curr_url and not curr_url.startswith("about:"):
            updates["page_url"] = curr_url

        if ("heading" in task_lower or "header" in task_lower) and hasattr(page, "query_selector"):
            try:
                h1_el = page.query_selector("h1, h2, header h1, main h1")
                if h1_el:
                    h_text = h1_el.inner_text().strip()
                    if h_text and len(h_text) > 2:
                        updates["page_heading"] = h_text
            except Exception:
                pass

        # If on an individual product page (e.g. Flipkart /p/, Amazon /dp/), extract product details
        is_product_page = any(seg in curr_url.lower() for seg in ["/p/", "/dp/", "/product/", "/item/"])
        if is_product_page:
            # 1. Product Title/Name from clean page title or DOM
            if " | flipkart" in curr_title.lower() or " : amazon" in curr_title.lower() or " | amazon" in curr_title.lower():
                clean_name = re.split(r"\s+-\s+Price\s+in\s+India|\s+\|\s+Flipkart|\s+:\s+Amazon|\s+\|\s+Amazon", curr_title, flags=re.IGNORECASE)[0].strip()
                if clean_name and len(clean_name) > 3:
                    updates["product_name"] = clean_name
            if hasattr(page, "query_selector"):
                try:
                    title_el = page.query_selector("h1, span#productTitle, span.B_NuCI, span.VU-ZEz, h1.VU-ZEz, [data-testid='product-title']")
                    if title_el:
                        t_text = title_el.inner_text().strip()
                        if t_text and len(t_text) > 3:
                            updates["product_name"] = t_text
                except Exception:
                    pass
            if not updates.get("product_name") and curr_title:
                updates["product_name"] = curr_title.split("-")[0].strip()

            # 2. Extract Price & Rating from DOM selectors and body text
            if hasattr(page, "evaluate"):
                try:
                    js_extracted = page.evaluate(r"""
                    () => {
                        const res = {};
                        // 1. Selector based price
                        const pEl = document.querySelector('div._30jeq3, div.Nx9daj, div.hl05eU, span.a-price-whole, div._25b18c, div._16Jk6d, [data-testid="product-price"]');
                        if (pEl && pEl.innerText && pEl.innerText.trim().match(/^[₹$Rs]/i)) {
                            res.price = pEl.innerText.trim().replace(/\s+/g, ' ');
                        }
                        
                        // 2. Selector based rating
                        const rEl = document.querySelector('div._3LWZlK, div.XQDdHH, span.a-icon-alt, div._2d4LTz, [class*="rating"]');
                        if (rEl && rEl.innerText.trim()) {
                            res.rating = rEl.innerText.trim();
                        }

                        // 3. Body text regex fallback
                        const bodyText = document.body ? document.body.innerText : '';
                        if (!res.price) {
                            const pMatch = bodyText.match(/(?:₹|\$|Rs\.?)\s*[\d,]{2,7}/i);
                            if (pMatch) res.price = pMatch[0].replace(/\s+/g, ' ').trim();
                        }
                        if (!res.rating) {
                            const rMatch = bodyText.match(/\b([1-5]\.\d)\s*(?:★|Ratings|out of 5|\/5)/i) || bodyText.match(/\b([1-5]\.\d)\b/);
                            if (rMatch) res.rating = rMatch[1];
                            else if (bodyText.includes("No ratings") || bodyText.includes("Be the first to review")) {
                                res.rating = "No ratings yet";
                            }
                        }

                        // 4. Specifications and highlights
                        const specsEl = document.querySelector('div._1UhVsV, div.x7WrMb, div#feature-bullets, div#productDetails_techSpec_section_1');
                        if (specsEl && specsEl.innerText) {
                            res.specifications = specsEl.innerText.substring(0, 3000);
                        }
                        const highEl = document.querySelector('div._2c2kV-, ul._2-riNZ, div#featurebullets_feature_div');
                        if (highEl && highEl.innerText) {
                            res.highlights = highEl.innerText.substring(0, 1500);
                        }
                        return res;
                    }
                    """)
                    if isinstance(js_extracted, dict):
                        if js_extracted.get("price"):
                            updates["price"] = str(js_extracted["price"]).replace("\n", " ").strip()
                        if js_extracted.get("rating"):
                            updates["rating"] = str(js_extracted["rating"]).replace("\n", " ").strip()
                        if js_extracted.get("specifications"):
                            updates["specifications"] = str(js_extracted["specifications"]).strip()
                        if js_extracted.get("highlights"):
                            updates["highlights"] = str(js_extracted["highlights"]).strip()
                except Exception as exc:
                    logger.debug("JS product extraction exception: %s", exc)

        if updates:
            self.memory.update_extracted_data(updates)

    def _check_and_dismiss_modal(self, page: Any, elements: list[ElementInfo]) -> bool:
        """Check for blocking login/signup/modal overlay and dismiss it if present."""
        if not elements:
            return False

        # Look for close button or dismiss element
        close_candidates = []
        for e in elements:
            text = (e.text or "").strip().lower()
            aria = (e.attributes.get("aria-label") or "").lower()
            cls = (e.attributes.get("class") or "").lower()

            if text in ("✕", "x", "close", "not now", "maybe later", "dismiss", "skip", "cancel"):
                close_candidates.append(e)
            elif "close" in aria or "dismiss" in aria:
                close_candidates.append(e)
            elif "_2kpz6l" in cls or "_2doktt" in cls or "close" in cls:
                close_candidates.append(e)

        if close_candidates:
            target_elem = close_candidates[0]
            self.log(f"Detected blocking modal/popup. Dismissing by clicking element #{target_elem.id} ('{target_elem.text}')")
            cx, cy = target_elem.center
            try:
                page.mouse.click(cx, cy)
                page.wait_for_timeout(500)
                return True
            except Exception:
                pass

        # Try Escape key
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return True
        except Exception:
            pass
        return False

    def run(self, task: str) -> dict[str, Any]:
        """Execute the full agent loop for a user task."""
        task = task.strip()
        if not task:
            self.set_state(AgentState.FAILED)
            return {"success": False, "error": "No task provided."}

        self._stop_requested.clear()
        self._pause_requested.clear()
        self._resume_event.set()

        self.task_plan = parse_task_plan(task)
        # Determine the number of valid candidates the user requests.
        if getattr(self.task_plan, "quantity", None) is not None:
            self.requested_quantity = self.task_plan.quantity
        else:
            # Implicit single‑candidate semantics for product/search tasks.
            self.requested_quantity = 1 if self.task_plan.intent in ("product_search", "ranked_search") else 0
        dest_url = self.task_plan.destination_url or extract_destination_url(task) or self.config.get("browser", {}).get("start_url", "https://duckduckgo.com")

        self.constraints = extract_task_constraints(task)
        self.evaluated_candidates = set()
        self.evaluated_candidate_details = []

        self.search_results_url = None

        self.memory = AgentMemory(
            task=task,
            normalized_query=self.task_plan.search_query or normalize_task(task),
            start_url=dest_url,
            max_steps=self.config.get("agent", {}).get("max_steps", 10),
            constraints=self.constraints,
            task_plan=self.task_plan,
        )

        self.set_state(AgentState.INITIALIZING)
        self.log(f"Starting browser agent for task: '{task}'")
        self.log(f"Parsed TaskPlan: {self.task_plan.summary()}")
        self.log(f"Target destination: '{dest_url}'")
        self.log(f"Normalized search query: '{self.memory.normalized_query}'")
        if self.constraints.has_constraints():
            self.log(f"Parsed task constraints: {self.constraints.summary()}")

        try:
            # Clear old screenshot files to prevent stale observation
            screenshot_path = Path(self.config.get("agent", {}).get("screenshot_path", "agent_screen.png"))
            annotated_path = Path(self.config.get("agent", {}).get("annotated_path", "agent_screen_annotated.png"))
            for sp in (screenshot_path, annotated_path):
                try:
                    if sp.exists():
                        sp.unlink()
                except Exception:
                    pass

            page = self.controller.launch(start_url=dest_url)

            task_completed = False
            max_steps = self.memory.max_steps
            if self.task_plan and getattr(self.task_plan, "procedural_requirements", None):
                max_steps = max(max_steps, len(self.task_plan.procedural_requirements) * 2 + 4)
            quality = self.config.get("agent", {}).get("screenshot_quality", 80)

            for step in range(1, max_steps + 1):
                if self._stop_requested.is_set():
                    self.set_state(AgentState.STOPPED)
                    self.log("Agent run halted due to stop request.")
                    break

                # Wait if paused
                if self._pause_requested.is_set():
                    self.set_state(AgentState.PAUSED)
                    self._resume_event.wait()
                    if self._stop_requested.is_set():
                        break

                self.memory.step_count = step
                page = self.controller.get_active_page() or page
                if self.on_step:
                    try:
                        self.on_step(step, max_steps)
                    except Exception:
                        pass

                self.log("=" * 60)
                self.log(f"AGENT STEP {step}/{max_steps}")
                self.log("=" * 60)
                self.log(f"Current URL: {safe_page_url(page)}")
                self.log(f"Current title: {safe_page_title(page)}")

                if not is_page_alive(page):
                    self.log("Browser page, context, or target closed before step observation.")
                    self.set_state(AgentState.FAILED)
                    self.memory.failure_reason = "Browser page or target was closed unexpectedly."
                    break

                # ----------------------------------------------------
                # 1. OBSERVE & SCREENSHOT
                # ----------------------------------------------------
                self.set_state(AgentState.OBSERVING)
                try:
                    take_screenshot(page, screenshot_path, quality)
                except Exception as exc:
                    err_str = str(exc).lower()
                    if "closed" in err_str or "targetclosed" in err_str or not is_page_alive(page):
                        self.log(f"Browser page closed during screenshot: {exc}")
                        self.set_state(AgentState.FAILED)
                        self.memory.failure_reason = "Browser page or target was closed unexpectedly."
                        break
                self.memory.current_url = safe_page_url(page)
                self.memory.current_title = safe_page_title(page)
                if hasattr(self.controller, "get_tab_registry"):
                    self.memory.tab_registry = self.controller.get_tab_registry()


                # Auto-ground visible page metadata
                self._ground_page_metadata(page)

                # Check and advance open/visit procedure if satisfied on current page
                if self.memory.current_procedure:
                    if self.memory.check_and_advance_open_procedure(page):
                        self.log(f"Open procedure satisfied on page: '{self.memory.completed_procedures[-1]}'. Advanced procedure index to {self.memory.procedure_index}/{self.memory.total_procedures}.")

                # Check if all requested information is already grounded and satisfied
                if self.memory.extracted_data.get("status") == "NO_MATCH":
                    self.log("Task concluded with honest NO_MATCH.")
                    task_completed = True
                    break

                if self.constraints.has_constraints():
                    is_prod_page = any(seg in page.url.lower() for seg in ["/p/", "/dp/", "/product/", "/item/"])
                    if is_prod_page:
                        page_text = ""
                        try:
                            page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                        except Exception:
                            page_text = ""
                        candidate_dict = {**self.memory.extracted_data, "title": safe_page_title(page), "url": safe_page_url(page)}
                        eval_res = evaluate_candidate(candidate_dict, page_text, self.constraints)
                        if eval_res["satisfied"]:
                            self.log("All requested information and constraints are SATISFIED on current product page. Concluding task immediately.")
                            action = {
                                "action": "done",
                                "confidence": 0.98,
                                "reasoning": f"Product satisfies all constraints: {self.constraints.summary()}",
                                "result": dict(self.memory.extracted_data),
                            }
                            self.memory.last_reasoning = action.get("reasoning", "")
                            self.memory.last_confidence = float(action.get("confidence", 0.98))
                            record = ActionRecord(
                                step=step,
                                action=action,
                                success=True,
                                verified=True,
                                state_change=False,
                                reasoning=action.get("reasoning", ""),
                                confidence=action.get("confidence", 1.0),
                                url_before=safe_page_url(page),
                                url_after=safe_page_url(page),
                                title_before=safe_page_title(page),
                                title_after=safe_page_title(page),
                            )
                            self.memory.add_action(record)
                            task_completed = True
                            break
                elif self.task_plan and self.task_plan.intent in ("navigation", "media_interaction") and (self.task_plan.target or self.task_plan.navigation_requirement or getattr(self.task_plan, "procedural_requirements", None)):
                    is_target_sat, target_reason = self.memory.is_target_page_satisfied(page)
                    is_proc_sat, _ = self.memory.is_procedure_satisfied(page)
                    if is_target_sat and is_proc_sat:
                        self.log(f"Goal SATISFIED: {target_reason}. Concluding task immediately.")
                        action = {
                            "action": "done",
                            "confidence": 0.98,
                            "reasoning": f"Target goal reached and verified: {target_reason}",
                            "result": {"url": safe_page_url(page), "title": safe_page_title(page), **dict(self.memory.extracted_data)},
                        }
                        self.memory.last_reasoning = action.get("reasoning", "")
                        self.memory.last_confidence = float(action.get("confidence", 0.98))
                        record = ActionRecord(
                            step=step,
                            action=action,
                            success=True,
                            verified=True,
                            state_change=False,
                            reasoning=action.get("reasoning", ""),
                            confidence=action.get("confidence", 1.0),
                            url_before=safe_page_url(page),
                            url_after=safe_page_url(page),
                            title_before=safe_page_title(page),
                            title_after=safe_page_title(page),
                        )
                        self.memory.add_action(record)
                        task_completed = True
                        break
                elif self.memory.is_task_satisfied(page, self.memory.task, self.constraints)[0]:
                    self.log("All task requirements (target, procedure, information) have been satisfied. Concluding task immediately.")
                    action = {
                        "action": "done",
                        "confidence": 0.98,
                        "reasoning": "All requested information is grounded and satisfied on the current page.",
                        "result": dict(self.memory.extracted_data),
                    }
                    self.memory.last_reasoning = action.get("reasoning", "")
                    self.memory.last_confidence = float(action.get("confidence", 0.98))
                    record = ActionRecord(
                        step=step,
                        action=action,
                        success=True,
                        verified=True,
                        state_change=False,
                        reasoning=action.get("reasoning", ""),
                        confidence=action.get("confidence", 1.0),
                        url_before=safe_page_url(page),
                        url_after=safe_page_url(page),
                        title_before=safe_page_title(page),
                        title_after=safe_page_title(page),
                    )
                    self.memory.add_action(record)
                    task_completed = True
                    break

                # ----------------------------------------------------
                # 2. PERCEIVE & SET-OF-MARKS ANNOTATION
                # ----------------------------------------------------
                self.set_state(AgentState.PERCEIVING)
                elements = self.perception.extract_interactive_elements(page)
                if self.on_perceive:
                    try:
                        self.on_perceive(elements)
                    except Exception:
                        pass

                # Check if a login/modal is blocking and dismiss it
                has_login_modal = any(
                    "login" in (e.text or "").lower() or "request otp" in (e.text or "").lower()
                    for e in elements
                )
                if has_login_modal:
                    dismissed = self._check_and_dismiss_modal(page, elements)
                    if dismissed:
                        page.wait_for_timeout(500)
                        elements = self.perception.extract_interactive_elements(page)

                vp = (page.viewport_size["width"], page.viewport_size["height"]) if page.viewport_size else None
                annotated_path = self.perception.annotate_screenshot(screenshot_path, elements, viewport=vp)
                elements_text = self.perception.format_elements_for_prompt(elements)

                # ----------------------------------------------------
                # 3. REASONING & PHASE-AWARE ACTION SELECTION
                # ----------------------------------------------------
                self.set_state(AgentState.THINKING)
                curr_url_lower = safe_page_url(page).lower()
                is_prod_page = any(seg in curr_url_lower for seg in ["/p/", "/dp/", "/product/", "/item/"])
                is_search_results_page = (
                    any(seg in curr_url_lower for seg in ["/search", "/results", "?q=", "&q=", "search_query=", "duckduckgo.com/?", "/pr?sid="])
                    or (("q=" in curr_url_lower or "query=" in curr_url_lower) and any(se in curr_url_lower for se in ["duckduckgo", "google", "bing", "flipkart", "youtube", "yahoo"]))
                ) and not is_prod_page
                if is_search_results_page:
                    self.search_results_url = safe_page_url(page)
                is_prod_task = (
                    (self.task_plan and self.task_plan.intent in ("product_search", "ranked_search"))
                    or any(kw in self.memory.task.lower() for kw in ["product", "laptop bag", "bag", "item", "price", "rating", "buy", "shoe", "headphone", "backpack", "laptop"])
                    or (self.constraints and self.constraints.has_constraints())
                )

                action: dict[str, Any] | None = None

                # PHASE A: PRODUCT DETAIL PAGE IS AUTHORITATIVE
                if is_prod_page:
                    self._ground_page_metadata(page)
                    if self.constraints.has_constraints():
                        page_text = ""
                        try:
                            page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                        except Exception:
                            page_text = ""
                        candidate_dict = {**self.memory.extracted_data, "title": page.title(), "url": page.url}
                        eval_res = evaluate_candidate(candidate_dict, page_text, self.constraints)
                        cand_name = str(candidate_dict.get("product_name") or page.title())

                        if eval_res["satisfied"]:
                             # Record a valid candidate
                             self.valid_candidates_found += 1
                             self.log(f"Product '{cand_name[:40]}' SATISFIES all constraints ({self.constraints.summary()}).")
                             # Optionally record details of the valid candidate
                             self.evaluated_candidate_details.append({
                                 "name": cand_name,
                                 "price": candidate_dict.get("price"),
                                 "rating": candidate_dict.get("rating"),
                                 "url": page.url,
                                 "checks": eval_res.get("checks", {}),
                                 "rejection_reasons": [],
                             })
                             action = {
                                 "action": "done",
                                 "confidence": 0.98,
                                 "reasoning": f"Product satisfies all constraints: {self.constraints.summary()}",
                                 "result": dict(self.memory.extracted_data),
                             }
                        else:
                             self.evaluated_candidates.add(page.url.lower())
                             self.evaluated_candidates.add(cand_name.lower())
                             for iid in re.findall(r"itm[a-z0-9]+|pid=[a-z0-9]+", page.url.lower()):
                                 self.evaluated_candidates.add(iid.lower())

                             self.evaluated_candidate_details.append({
                                 "name": cand_name,
                                 "price": candidate_dict.get("price"),
                                 "rating": candidate_dict.get("rating"),
                                 "url": page.url,
                                 "checks": eval_res.get("checks", {}),
                                 "rejection_reasons": eval_res["rejection_reasons"],
                             })
                             self.log(f"Candidate '{cand_name[:40]}' REJECTED by constraint evaluation: {'; '.join(eval_res['rejection_reasons'])}")
                             for c_name, c_info in eval_res.get("checks", {}).items():
                                 pass_str = "PASS" if c_info.get("passed") else "FAIL"
                                 self.log(f"  [{pass_str}] {c_name}: {c_info.get('reason') or c_info.get('actual')}")

                             # Increment inspected count for this evaluated candidate
                             self.candidates_inspected += 1
                             if self.candidates_inspected >= self.exploration_budget:
                                 self.budget_exhausted = True
                                 self.log(f"Exploration budget ({self.exploration_budget}) exhausted after inspecting {self.candidates_inspected} candidates.")
                                 action = None
                             else:
                                 prev_page = self.controller.close_active_tab()
                                 if prev_page and prev_page != page:
                                     page = prev_page
                                 if self.search_results_url and not any(seg in page.url.lower() for seg in ["/search", "?q=", "&q=", "/pr?sid="]):
                                     self.controller.goto(self.search_results_url)
                                     page = self.controller.get_active_page() or page
                                 action = {
                                     "action": "wait",
                                     "seconds": 1,
                                     "reasoning": "Closed rejected product tab; continuing search on search results page",
                                     "confidence": 0.9,
                                 }
                    elif self.task_plan and self.task_plan.intent == "ranked_search":
                        cand_name = str(self.memory.extracted_data.get("product_name") or page.title())
                        raw_price = self.memory.extracted_data.get("price")
                        raw_rating = self.memory.extracted_data.get("rating")
                        num_rating = parse_numeric_rating(raw_rating)
                        num_price = parse_numeric_price(raw_price)

                        self.evaluated_candidates.add(page.url.lower())
                        self.evaluated_candidates.add(cand_name.lower())
                        for iid in re.findall(r"itm[a-z0-9]+|pid=[a-z0-9]+", page.url.lower()):
                            self.evaluated_candidates.add(iid.lower())

                        candidate_info = {
                            "name": cand_name,
                            "price": raw_price,
                            "numeric_price": num_price,
                            "rating": raw_rating,
                            "numeric_rating": num_rating,
                            "url": page.url,
                            "extracted_data": dict(self.memory.extracted_data),
                        }
                        self.evaluated_candidate_details.append(candidate_info)
                        self.log(f"Evaluated ranked candidate {len(self.evaluated_candidate_details)}/{self.exploration_budget}: '{cand_name[:40]}' (Rating: {raw_rating}, Price: {raw_price})")

                        # Increment inspected count for this ranked candidate
                        self.candidates_inspected += 1
                        if self.candidates_inspected >= self.exploration_budget:
                            self.budget_exhausted = True
                            self.log(f"Exploration budget ({self.exploration_budget}) exhausted after inspecting {self.candidates_inspected} ranked candidates.")
                            action = None
                        if len(self.evaluated_candidate_details) >= self.requested_quantity:
                            # Enough valid candidates for ranking/comparison
                            rank_field = getattr(self.task_plan, "ranking_field", "rating") or "rating"
                            rank_order = getattr(self.task_plan, "ranking_order", "desc") or "desc"

                            best_cand, valid_cands = pick_best_ranked_candidate(
                                self.evaluated_candidate_details,
                                self.constraints,
                                rank_field=rank_field,
                                rank_order=rank_order,
                            )

                            if best_cand:
                                self.memory.extracted_data = dict(best_cand["extracted_data"])
                                self.memory.extracted_data["product_name"] = best_cand["name"]
                                self.log(f"Ranked search selected best candidate '{best_cand['name'][:40]}' ({rank_field}={best_cand.get(f'numeric_{rank_field}')})")
                                action = {
                                    "action": "done",
                                    "confidence": 0.98,
                                    "reasoning": f"Ranked search completed. Evaluated {len(self.evaluated_candidate_details)} candidates ({len(valid_cands)} valid); selected '{best_cand['name']}' with top {rank_field}.",
                                    "result": dict(self.memory.extracted_data),
                                }
                            else:
                                self.log("All evaluated candidates failed constraints. Concluding with honest NO_MATCH.")
                                self.memory.extracted_data = {
                                    "status": "NO_MATCH",
                                    "message": f"No product satisfying all conditions ({self.constraints.summary()}) was found after evaluating {len(self.evaluated_candidate_details)} candidate(s).",
                                    "evaluated_candidates": self.evaluated_candidate_details,
                                }
                                action = {
                                    "action": "done",
                                    "confidence": 0.98,
                                    "reasoning": f"Evaluated {len(self.evaluated_candidate_details)} candidate(s), none satisfied constraints ({self.constraints.summary()}); concluding with honest NO_MATCH.",
                                    "result": dict(self.memory.extracted_data),
                                }
                        else:
                            prev_page = self.controller.close_active_tab()
                            if prev_page and prev_page != page:
                                page = prev_page
                            if self.search_results_url and not any(seg in page.url.lower() for seg in ["/search", "?q=", "&q=", "/pr?sid="]):
                                self.controller.goto(self.search_results_url)
                                page = self.controller.get_active_page() or page
                            action = {
                                "action": "wait",
                                "seconds": 1,
                                "reasoning": f"Evaluated candidate {len(self.evaluated_candidate_details)}/{self.exploration_budget}; returning to search results for next candidate",
                                "confidence": 0.9,
                            }
                    else:
                        if self.memory.is_information_satisfied(self.memory.task, page, constraints=self.constraints):
                            self.log("All requested product information is grounded and satisfied. Concluding task immediately.")
                            action = {
                                "action": "done",
                                "confidence": 0.98,
                                "reasoning": "Product details (name, price, rating) successfully grounded from product page.",
                                "result": dict(self.memory.extracted_data),
                            }
                        else:
                            # Reveal lazy-loaded price/ratings by slight scroll on product page
                            action = {
                                "action": "scroll",
                                "direction": "down",
                                "amount": 300,
                                "reasoning": "Revealing product details, price, and rating on product page.",
                                "confidence": 0.9,
                            }

                # PHASE B: SEARCH RESULTS PAGE DETERMINISTIC GROUNDING
                elif is_search_results_page:
                    if is_prod_task:
                        candidate_prod_links = find_product_links(elements)
                        # Filter unvisited candidates
                        unvisited = []
                        for elem in candidate_prod_links:
                            href = (elem.attributes.get("href") or "").lower()
                            text = (elem.text or "").lower()
                            elem_ids = re.findall(r"itm[a-z0-9]+|pid=[a-z0-9]+", href)
                            is_seen = any(iid in self.evaluated_candidates for iid in elem_ids)
                            if not is_seen:
                                for c in self.evaluated_candidates:
                                    if len(c) > 6 and (c in href or href in c or c in text or (len(text) > 10 and text in c)):
                                        is_seen = True
                                        break
                            if not is_seen:
                                unvisited.append(elem)

                        if unvisited:
                            target_prod = unvisited[0]
                            cand_num = len(self.evaluated_candidate_details) + 1
                            self.log(f"Deterministic product candidate {cand_num}/{self.exploration_budget} found: '{target_prod.text[:50]}' (ID {target_prod.id})")
                            action = {
                                "action": "click",
                                "element_id": target_prod.id,
                                "reasoning": f"Opening candidate product link '{target_prod.text[:40]}'",
                                "confidence": 0.95,
                            }
                        else:
                            # No unvisited candidates on current view; try to load more results if budget permits
                            if len(self.evaluated_candidate_details) < self.exploration_budget:
                                self.log("No unvisited candidates on current page; scrolling to load more results.")
                                action = {
                                    "action": "scroll",
                                    "direction": "down",
                                    "amount": 300,
                                    "reasoning": "Scrolling search results to reveal more products",
                                    "confidence": 0.9,
                                }
                            else:
                                # Budget exhausted; let later logic handle ranking or NO_MATCH
                                action = None

                    else:
                        # General organic search results (e.g. YouTube videos, Wikipedia articles, Python docs)
                        pref = "video" if any(k in (self.task_plan.target if self.task_plan else "").lower() or k in self.memory.task.lower() for k in ["video", "song", "track"]) else None
                        best_cand = select_best_candidate_link(
                            elements,
                            query=self.memory.normalized_query,
                            target=self.task_plan.target if self.task_plan else "",
                            preferred_type=pref,
                            unvisited_only=True,
                            visited_hrefs=self.evaluated_candidates,
                        )
                        if best_cand:
                            self.log(f"Deterministic candidate grounding found: '{best_cand.text[:50]}' (ID {best_cand.id})")
                            action = {
                                "action": "click",
                                "element_id": best_cand.id,
                                "reasoning": f"Opening candidate content link '{best_cand.text[:40]}'",
                                "confidence": 0.95,
                            }
                        else:
                            organic_links = find_organic_search_results(elements, self.memory.normalized_query)
                            if organic_links:
                                target_link = organic_links[0]
                                self.log(f"Deterministic search result grounding found: '{target_link.text[:50]}' (ID {target_link.id})")
                                action = {
                                    "action": "click",
                                    "element_id": target_link.id,
                                    "reasoning": f"Opening search result '{target_link.text[:40]}'",
                                    "confidence": 0.95,
                                }

                # PHASE C: GOAL-AWARE EXPLORATION (BEFORE ASKING VLM)
                if action is None and not self.constraints.has_constraints():
                    action = choose_goal_exploration_action(page, elements, self.memory)
                    if action:
                        self.log(f"Goal exploration selected: {action.get('action')} - {action.get('reasoning', '')}")

                # PHASE D: VLM DECISION (WITH DETERMINISTIC RECOVERY ON FAILURE)
                if action is None:
                    loop_warning = ""
                    history_summaries = self.memory.get_recent_history_summary(6)
                    active_img = annotated_path if Path(annotated_path).exists() else screenshot_path

                    try:
                        action = ask_vision_model(
                            task=self.memory.task,
                            search_term=self.memory.normalized_query,
                            url=safe_page_url(page),
                            title=safe_page_title(page),
                            elements_text=elements_text,
                            screenshot_path=active_img,
                            action_history_summaries=history_summaries,
                            loop_warning=loop_warning,
                            target_page=self.task_plan.target if self.task_plan else "",
                        )
                        self.consecutive_vlm_failures = 0
                    except Exception as exc:
                        self.consecutive_vlm_failures += 1
                        self.log(f"Vision model decision failed (consecutive failures: {self.consecutive_vlm_failures}): {exc}")

                        # Check if page is actively loading/busy before deciding what to do
                        if is_page_actively_loading(page):
                            self.log("Page is actively loading; waiting for stabilization.")
                            action = {"action": "wait", "seconds": 2, "reasoning": "Page is actively loading; waiting for stabilization", "confidence": 0.5}
                        elif self.consecutive_vlm_failures >= 4:
                            self.log(f"VLM failed {self.consecutive_vlm_failures} times consecutively. Concluding with honest failure.")
                            action = {
                                "action": "fail",
                                "reasoning": f"Vision model unavailable or repeatedly returned invalid output ({self.consecutive_vlm_failures} consecutive failures).",
                                "confidence": 0.9,
                            }
                        else:
                            # Controlled deterministic recovery based on current navigation & procedural state
                            is_target_sat, _ = self.memory.is_target_page_satisfied(page)
                            curr_proc = (self.memory.current_procedure or "").lower()

                            # 1. If on target/watch page and procedure is to play or media task:
                            if (is_target_sat or "watch" in safe_page_url(page).lower()) and any(k in curr_proc or k in self.memory.task.lower() for k in ["play", "playback", "start"]):
                                action = {
                                    "action": "play",
                                    "reasoning": "Deterministic recovery: starting media playback on target/watch page",
                                    "confidence": 0.9,
                                }
                            # 2. If on search results page:
                            elif is_search_results_page:
                                if is_prod_task:
                                    candidate_prod_links = find_product_links(elements)
                                    unvisited = [e for e in candidate_prod_links if not any(c.lower() in (e.attributes.get('href') or '').lower() for c in self.evaluated_candidates)]
                                    if unvisited:
                                        action = {
                                            "action": "click",
                                            "element_id": unvisited[0].id,
                                            "reasoning": f"Deterministic recovery: opening product link '{unvisited[0].text[:40]}'",
                                            "confidence": 0.9,
                                        }
                                    else:
                                        action = {
                                            "action": "scroll",
                                            "direction": "down",
                                            "amount": 600,
                                            "reasoning": "Deterministic recovery: scrolling search results to reveal product cards",
                                            "confidence": 0.8,
                                        }
                                else:
                                    pref = "video" if any(k in (self.task_plan.target if self.task_plan else "").lower() or k in self.memory.task.lower() for k in ["video", "song", "track"]) else None
                                    best_cand = select_best_candidate_link(
                                        elements,
                                        query=self.memory.normalized_query,
                                        target=self.task_plan.target if self.task_plan else "",
                                        preferred_type=pref,
                                        unvisited_only=True,
                                        visited_hrefs=self.evaluated_candidates,
                                    )
                                    if best_cand:
                                        action = {
                                            "action": "click",
                                            "element_id": best_cand.id,
                                            "reasoning": f"Deterministic recovery: opening candidate link '{best_cand.text[:40]}'",
                                            "confidence": 0.9,
                                        }
                                    else:
                                        organic_links = find_organic_search_results(elements, self.memory.normalized_query)
                                        if organic_links:
                                            target_link = organic_links[0]
                                            action = {
                                                "action": "click",
                                                "element_id": target_link.id,
                                                "reasoning": f"Deterministic recovery: opening result '{target_link.text[:40]}'",
                                                "confidence": 0.9,
                                            }
                                        else:
                                            action = {
                                                "action": "scroll",
                                                "direction": "down",
                                                "amount": 600,
                                                "reasoning": "Deterministic recovery: scrolling search results",
                                                "confidence": 0.8,
                                            }
                            # 3. If on home or general page and need to search:
                            elif not is_search_results_page and ("search" not in safe_page_url(page).lower() or any(se in safe_page_url(page).lower() for se in ["duckduckgo.com", "google.com", "bing.com", "flipkart.com", "amazon.com", "youtube.com"])):
                                search_inputs = [
                                    e for e in elements
                                    if e.tag == 'input' or 'search' in (e.attributes.get('placeholder') or '').lower() or (e.attributes.get('type') or '').lower() == 'search'
                                ]
                                if search_inputs:
                                    action = {
                                        "action": "type",
                                        "element_id": search_inputs[0].id,
                                        "text": self.memory.normalized_query,
                                        "reasoning": f"Deterministic recovery: typing search query '{self.memory.normalized_query}' into search field",
                                        "confidence": 0.9,
                                    }
                                else:
                                    action = {"action": "wait", "seconds": 2, "reasoning": "Deterministic recovery: waiting for page", "confidence": 0.4}
                            else:
                                action = {"action": "wait", "seconds": 2, "reasoning": "VLM decision unavailable; waiting for page stabilization", "confidence": 0.3}

                # Check for loop before executing
                is_loop, loop_advice = self.loop_detector.check_loop(self.memory, action)
                if is_loop:
                    self.log(f"Loop detected! Applying structured recovery action: {loop_advice}")
                    recovery_action = self.loop_detector.get_recovery_action(self.memory, elements, page, failed_action=action)
                    action = recovery_action

                self.log(f"AI ACTION: {action}")
                self.memory.last_reasoning = action.get("reasoning", "")
                self.memory.last_confidence = float(action.get("confidence", 0.9))

                action_type = str(action.get("action", "")).lower()

                # Guard against premature DONE when procedural requirements remain
                if action_type == "done" and self.memory.current_procedure is not None:
                    self.log(f"Blocked premature 'done': procedure {self.memory.procedure_index + 1}/{self.memory.total_procedures} ('{self.memory.current_procedure}') remains pending.")
                    procedural_action = choose_goal_exploration_action(page, elements, self.memory)
                    if procedural_action and str(procedural_action.get("action", "")).lower() != "done":
                        action = procedural_action
                        action_type = str(action.get("action", "")).lower()
                        self.log(f"Redirected to procedural action: {action.get('action')} - {action.get('reasoning', '')}")
                    else:
                        action = {"action": "wait", "seconds": 2, "reasoning": f"Waiting to advance procedure '{self.memory.current_procedure}'", "confidence": 0.5}
                        action_type = "wait"

                # Handle DONE or FAIL
                if action_type == "done":
                    self.log("AI decided the task is complete.")
                    if isinstance(action.get("result"), dict):
                        self.memory.update_extracted_data(action["result"])
                        self.log(f"Extracted result: {self.memory.extracted_data}")
                    self._ground_page_metadata(page)
                    record = ActionRecord(
                        step=step,
                        action=action,
                        success=True,
                        verified=True,
                        state_change=False,
                        reasoning=action.get("reasoning", ""),
                        confidence=action.get("confidence", 1.0),
                        url_before=safe_page_url(page),
                        url_after=safe_page_url(page),
                        title_before=safe_page_title(page),
                        title_after=safe_page_title(page),
                    )
                    self.memory.add_action(record)
                    task_completed = True
                    break

                if action_type == "fail":
                    if action.get("auth_required") or getattr(self.memory, "auth_required", False):
                        self.log(f"Authentication / CAPTCHA barrier detected: {action.get('reasoning')}. Cleanly pausing agent for user.")
                        self.set_state(AgentState.PAUSED)
                        record = ActionRecord(
                            step=step,
                            action=action,
                            success=False,
                            verified=False,
                            state_change=False,
                            reasoning=action.get("reasoning", ""),
                            confidence=1.0,
                            url_before=safe_page_url(page),
                            url_after=safe_page_url(page),
                            title_before=safe_page_title(page),
                            title_after=safe_page_title(page),
                        )
                        self.memory.add_action(record)
                        break

                    self.log("AI reported it cannot complete the task.")
                    record = ActionRecord(
                        step=step,
                        action=action,
                        success=False,
                        verified=False,
                        state_change=False,
                        reasoning=action.get("reasoning", ""),
                        confidence=action.get("confidence", 1.0),
                        url_before=safe_page_url(page),
                        url_after=safe_page_url(page),
                        title_before=safe_page_title(page),
                        title_after=safe_page_title(page),
                    )
                    self.memory.add_action(record)
                    break

                # Multi-tab action handling
                if action_type == "switch_tab":
                    target_tab = action.get("tab_id", action.get("index", 0))
                    page = self.controller.switch_tab(target_tab) or page
                elif action_type == "new_tab":
                    target_url = action.get("url", "")
                    page = self.controller.new_tab(target_url) or page
                elif action_type == "close_tab":
                    page = self.controller.close_active_tab() or page

                # ----------------------------------------------------
                # 4. ACTION EXECUTION & PRE/POST VERIFICATION
                # ----------------------------------------------------
                self.set_state(AgentState.ACTING)
                if not is_page_alive(page):
                    self.log("Cannot execute action: browser page is closed.")
                    self.set_state(AgentState.FAILED)
                    self.memory.failure_reason = "Browser page or target was closed unexpectedly."
                    break

                try:
                    pre_state = self.verifier.capture_pre_action_state(page, action)
                    url_before = safe_page_url(page)
                    title_before = safe_page_title(page)
                    if action_type in ("switch_tab", "new_tab", "close_tab"):
                        exec_success = True
                    else:
                        exec_success = execute_action(page, action, elements)
                except Exception as act_exc:
                    err_str = str(act_exc).lower()
                    if "closed" in err_str or "targetclosed" in err_str or not is_page_alive(page):
                        self.log(f"Browser page closed during action execution: {act_exc}")
                        self.set_state(AgentState.FAILED)
                        self.memory.failure_reason = "Browser page or target was closed unexpectedly during action."
                        break
                    self.log(f"Action execution error: {act_exc}")
                    exec_success = False
                    pre_state = None
                    url_before = safe_page_url(page)
                    title_before = safe_page_title(page)

                self.set_state(AgentState.VERIFYING)
                if not is_page_alive(page):
                    self.log("Browser page was closed after action execution.")
                    self.set_state(AgentState.FAILED)
                    self.memory.failure_reason = "Browser page or target was closed unexpectedly after action."
                    break

                try:
                    verification = self.verifier.verify_action(page, action, pre_state, exec_success)
                    url_after = safe_page_url(page)
                    title_after = safe_page_title(page)
                except Exception as ver_exc:
                    err_str = str(ver_exc).lower()
                    if "closed" in err_str or "targetclosed" in err_str or not is_page_alive(page):
                        self.log(f"Browser page closed during verification: {ver_exc}")
                        self.set_state(AgentState.FAILED)
                        self.memory.failure_reason = "Browser page or target was closed unexpectedly during verification."
                        break
                    from browser_agent.verifier import ActionVerification
                    verification = ActionVerification(verified=False, reason=f"Verification error: {ver_exc}")
                    url_after = safe_page_url(page)
                    title_after = safe_page_title(page)

                record = ActionRecord(
                    step=step,
                    action=action,
                    success=exec_success,
                    verified=verification.verified,
                    verification_reason=verification.reason,
                    state_change=verification.state_changed,
                    reasoning=action.get("reasoning", ""),
                    confidence=float(action.get("confidence", 0.9)),
                    url_before=url_before,
                    url_after=url_after,
                    title_before=title_before,
                    title_after=title_after,
                )
                self.memory.add_action(record)

                if self.on_action:
                    try:
                        self.on_action(record)
                    except Exception:
                        pass

                if action_type == "scroll" and verification.details:
                    self.memory.scroll_state.update(
                        verification.details.get("scroll_y", 0),
                        verification.details.get("max_scroll_y", 0),
                        verification.details.get("viewport_height", 0),
                    )

                if verification.verified:
                    self.log(f"ACTION VERIFIED: {verification.reason}")
                else:
                    self.log(f"ACTION UNVERIFIED: {verification.reason}")

                # Advance procedural state machine if postcondition is met
                if self.memory.current_procedure is not None:
                    curr_p = self.memory.current_procedure
                    adv = self.memory.advance_procedure(page, action, verification)
                    if adv:
                        self.log(f"Procedure completed ({self.memory.procedure_index}/{self.memory.total_procedures}): '{curr_p}'. Advancing to procedure index {self.memory.procedure_index}.")
                    else:
                        can_adv, fail_reason = self.memory.can_advance_procedure(page, action, verification)
                        self.log(f"Procedure '{curr_p}' not yet completed: {fail_reason}")

                # Check if action output satisfied information requirements
                if isinstance(action.get("result"), dict):
                    self.memory.update_extracted_data(action["result"])

                # Wait step delay
                step_wait = self.config.get("browser", {}).get("step_wait_timeout", 1000)
                page.wait_for_timeout(step_wait)

            # ----------------------------------------------------
            # 5. FINAL VERIFICATION & OUTCOME
            # ----------------------------------------------------
            if self._stop_requested.is_set():
                self.set_state(AgentState.STOPPED)
                return {"success": False, "state": "STOPPED", "memory": self.memory}

            self.set_state(AgentState.VERIFYING)
            self.log("=" * 60)
            self.log("FINAL TASK VERIFICATION")
            self.log("=" * 60)

            # Ground metadata one last time on final page
            page = self.controller.get_active_page() or page
            if is_page_alive(page):
                self._ground_page_metadata(page)

            final_screenshot = Path("final.png")
            if is_page_alive(page):
                try:
                    take_screenshot(page, final_screenshot, quality)
                except Exception:
                    pass

            info_triggers = ["tell me", "what is", "find the", "check the", "get the", "give me", "show me", "product name", "price", "rating"]
            is_info_task = any(t in task.lower() for t in info_triggers)
            info_satisfied = self.memory.is_information_satisfied(self.memory.task, page, constraints=self.constraints) if is_page_alive(page) else False

            if self.constraints.has_constraints():
                if self.memory.extracted_data.get("status") == "NO_MATCH" or (
                    self.evaluated_candidate_details and all(c.get("rejection_reasons") for c in self.evaluated_candidate_details) and not is_prod_page
                ):
                    self.memory.extracted_data = {
                        "status": "NO_MATCH",
                        "message": f"No product satisfying all conditions ({self.constraints.summary()}) was found after evaluating {len(self.evaluated_candidate_details)} candidate(s).",
                        "evaluated_candidates": self.evaluated_candidate_details,
                    }
                    ver_result = {
                        "verified": True,
                        "reason": f"No product satisfied all constraints ({self.constraints.summary()}); NO_MATCH reported honestly.",
                        "confidence": 0.98,
                    }
                    is_success = True
                    final_state_str = "NO_MATCH"
                else:
                    page_text = ""
                    try:
                        page_text = page.evaluate("() => document.body ? document.body.innerText : ''") if is_page_alive(page) else ""
                    except Exception:
                        page_text = ""
                    candidate_dict = {**self.memory.extracted_data, "title": safe_page_title(page), "url": safe_page_url(page)}
                    eval_res = evaluate_candidate(candidate_dict, page_text, self.constraints)
                    if eval_res["satisfied"]:
                        ver_result = {
                            "verified": True,
                            "reason": f"All constraints satisfied: {self.constraints.summary()}",
                            "confidence": 0.98,
                        }
                        is_success = True
                        final_state_str = "SUCCESS"
                    else:
                        ver_result = {
                            "verified": False,
                            "reason": f"Constraints not satisfied by candidate: {'; '.join(eval_res['rejection_reasons'])}",
                            "confidence": 0.0,
                        }
                        is_success = False
                        final_state_str = "FAILED"
            elif self.task_plan and self.task_plan.intent == "ranked_search":
                if self.evaluated_candidate_details and (self.memory.extracted_data.get("rating") or self.memory.extracted_data.get("price") or self.memory.extracted_data.get("product_name")):
                    best_name = self.memory.extracted_data.get("product_name") or self.evaluated_candidate_details[0].get("name", "Product")
                    ver_result = {
                        "verified": True,
                        "reason": f"Ranked search successfully evaluated {len(self.evaluated_candidate_details)} candidate(s) and selected top candidate '{best_name}'.",
                        "confidence": 0.98,
                    }
                    is_success = True
                    final_state_str = "SUCCESS"
                else:
                    ver_result = {
                        "verified": False,
                        "reason": "Ranked search did not extract candidate product details.",
                        "confidence": 0.0,
                    }
                    is_success = False
                    final_state_str = "FAILED"
            elif self.task_plan and (self.task_plan.navigation_requirement or (self.task_plan.target and self.task_plan.target_type in ("article", "website", "documentation")) or self.task_plan.procedural_requirements):
                is_target_sat, target_reason = self.memory.is_target_page_satisfied(page)
                is_proc_sat, proc_reason = self.memory.is_procedure_satisfied(page)
                if not is_target_sat:
                    ver_result = {
                        "verified": False,
                        "reason": f"Required target page '{self.task_plan.target}' was not satisfied: {target_reason}",
                        "confidence": 0.0,
                    }
                    is_success = False
                    final_state_str = "FAILED" if getattr(self.memory, "failed_procedures", None) else "INCOMPLETE"
                elif not is_proc_sat:
                    ver_result = {
                        "verified": False,
                        "reason": f"Procedural requirements remaining: {proc_reason}",
                        "confidence": 0.0,
                    }
                    is_success = False
                    final_state_str = "FAILED" if getattr(self.memory, "failed_procedures", None) else "INCOMPLETE"
                elif self.task_plan.intent in ("navigation", "media_interaction"):
                    ver_result = {
                        "verified": True,
                        "reason": f"Target page/goal '{self.task_plan.target or self.task_plan.destination}' reached and satisfied successfully ({target_reason}).",
                        "confidence": 0.98,
                    }
                    is_success = True
                    final_state_str = "SUCCESS"
                elif is_info_task:
                    if info_satisfied:
                        ver_result = {
                            "verified": True,
                            "reason": f"Target page '{self.task_plan.target}' reached and requested information grounded.",
                            "confidence": 0.98,
                        }
                        is_success = True
                        final_state_str = "SUCCESS"
                    else:
                        ver_result = {
                            "verified": False,
                            "reason": f"Target page '{self.task_plan.target}' reached, but requested information was not grounded or extracted.",
                            "confidence": 0.0,
                        }
                        is_success = False
                        final_state_str = "INCOMPLETE"
                else:
                    ver_result = verify_task_completion(task, page, final_screenshot)
                    is_success = bool(ver_result.get("verified", False))
                    final_state_str = "SUCCESS" if is_success else "INCOMPLETE"
            elif is_info_task and info_satisfied:
                ver_result = {
                    "verified": True,
                    "reason": "All requested information was successfully extracted and grounded on the page.",
                    "confidence": 0.98,
                }
                is_success = True
                final_state_str = "SUCCESS"
            else:
                ver_result = verify_task_completion(task, page, final_screenshot)
                if is_info_task and not info_satisfied:
                    ver_result["verified"] = False
                    ver_result["reason"] = "Requested information criteria not fully satisfied on destination page."
                is_success = bool(ver_result.get("verified", False))
                final_state_str = "SUCCESS" if is_success else "FAILED"

            self.log(f"Verification: {ver_result}")

            if self.constraints.has_constraints():
                if final_state_str == "NO_MATCH":
                    cands_summary = []
                    for idx, c in enumerate(self.evaluated_candidate_details, 1):
                        reasons = "; ".join(c.get("rejection_reasons", []))
                        cands_summary.append(f"{idx}. {c.get('name', 'Product')} (Price: {c.get('price', 'N/A')}, Rating: {c.get('rating', 'N/A')}) -> Rejected: {reasons}")
                    cand_block = "\n".join(cands_summary) if cands_summary else "No candidates could be opened."
                    summary = (
                        f"**TASK RESULT: NO MATCHING PRODUCT FOUND**\n\n"
                        f"- **Task Constraints**: {self.constraints.summary()}\n"
                        f"- **Candidates Evaluated ({len(self.evaluated_candidate_details)})**:\n{cand_block}\n"
                        f"- **Conclusion**: No product satisfied all required conditions. Reported honestly without hallucinating or relaxing constraints."
                    )
                elif final_state_str == "SUCCESS":
                    prod_name = self.memory.extracted_data.get("product_name") or safe_page_title(page)
                    p_val = self.memory.extracted_data.get("price", "N/A")
                    r_val = self.memory.extracted_data.get("rating", "N/A")
                    summary = (
                        f"**TASK RESULT: SUCCESS**\n\n"
                        f"- **Product Found**: {prod_name}\n"
                        f"- **Price**: {p_val}\n"
                        f"- **Rating**: {r_val}\n"
                        f"- **URL**: {safe_page_url(page)}\n"
                        f"- **Satisfied Constraints**: {self.constraints.summary()}"
                    )
                else:  # FAILED
                    cands_summary = []
                    for idx, c in enumerate(self.evaluated_candidate_details, 1):
                        reasons = "; ".join(c.get("rejection_reasons", []))
                        cands_summary.append(f"{idx}. {c.get('name', 'Product')} (Price: {c.get('price', 'N/A')}, Rating: {c.get('rating', 'N/A')}) -> Rejected: {reasons}")
                    cand_block = "\n".join(cands_summary) if cands_summary else "; ".join(eval_res.get("rejection_reasons", []))
                    summary = (
                        f"**TASK RESULT: FAILED / NOT SATISFIED**\n\n"
                        f"- **Task Constraints**: {self.constraints.summary()}\n"
                        f"- **Rejection Reasons**: {cand_block}\n"
                        f"- **Outcome**: Required task constraints were not satisfied by candidate."
                    )
                self.log(f"TASK SUMMARY:\n{summary}")
            elif self.memory.extracted_data.get("status") == "NO_MATCH":
                summary = "**TASK RESULT: NO MATCHING PRODUCT FOUND**"
                self.log(f"TASK SUMMARY:\n{summary}")
            elif self.task_plan and self.task_plan.intent == "ranked_search":
                prod_name = self.memory.extracted_data.get("product_name") or (self.evaluated_candidate_details[0].get("name") if self.evaluated_candidate_details else safe_page_title(page))
                p_val = self.memory.extracted_data.get("price", "N/A")
                r_val = self.memory.extracted_data.get("rating", "N/A")
                status_title = "SUCCESS" if is_success else final_state_str
                summary = (
                    f"**TASK RESULT: {status_title}**\n\n"
                    f"- **Product Found**: {prod_name}\n"
                    f"- **Price**: {p_val}\n"
                    f"- **Rating**: {r_val}\n"
                    f"- **URL**: {safe_page_url(page)}\n"
                    f"- **Ranking Criteria**: {getattr(self.task_plan, 'ranking_field', 'rating')} ({getattr(self.task_plan, 'ranking_order', 'desc')})\n"
                    f"- **Verification**: {ver_result.get('reason', '')}"
                )
                self.log(f"TASK SUMMARY:\n{summary}")
            elif self.task_plan and getattr(self.task_plan, "procedural_requirements", None):
                proc_lines = []
                for idx, pr in enumerate(self.task_plan.procedural_requirements):
                    if idx < self.memory.procedure_index:
                        proc_lines.append(f"- [x] {pr}")
                    else:
                        proc_lines.append(f"- [ ] {pr}")
                proc_checklist = "\n".join(proc_lines)
                status_title = "SUCCESS" if is_success else final_state_str
                summary = (
                    f"**TASK RESULT: {status_title}**\n\n"
                    f"- **Procedural Execution ({self.memory.procedure_index}/{len(self.task_plan.procedural_requirements)} completed)**:\n{proc_checklist}\n"
                    f"- **Target Page**: {self.task_plan.target or 'N/A'}\n"
                    f"- **Current Page**: {safe_page_title(page)} ({safe_page_url(page)})\n"
                    f"- **Verification**: {ver_result.get('reason', '')}"
                )
                if self.memory.extracted_data:
                    data_lines = [f"  - **{k.replace('_', ' ').title()}**: {v}" for k, v in self.memory.extracted_data.items() if k != "status"]
                    if data_lines:
                        summary += "\n- **Extracted Information**:\n" + "\n".join(data_lines)
                self.log(f"TASK SUMMARY:\n{summary}")
            elif final_state_str in ("INCOMPLETE", "FAILED"):
                summary = (
                    f"**TASK RESULT: {final_state_str}**\n\n"
                    f"- **Target Page**: {self.task_plan.target if self.task_plan else 'N/A'}\n"
                    f"- **Current Page**: {safe_page_title(page)} ({safe_page_url(page)})\n"
                    f"- **Verification Reason**: {ver_result.get('reason', 'Task criteria not satisfied')}"
                )
                self.log(f"TASK SUMMARY:\n{summary}")
            else:
                try:
                    summary = summarize_task_result(
                        task,
                        page,
                        final_screenshot,
                        extracted_result=self.memory.extracted_data,
                    )
                    self.log(f"TASK SUMMARY:\n{summary}")
                except Exception as exc:
                    if self.memory.extracted_data:
                        lines = [f"- **{k.replace('_', ' ').title()}**: {v}" for k, v in self.memory.extracted_data.items()]
                        summary = "\n".join(lines)
                    else:
                        summary = "Task concluded."
                    logger.debug("Summary generation fallback: %s", exc)

            if final_state_str == "NO_MATCH":
                self.set_state(AgentState.COMPLETED)
                self.log("TASK COMPLETED: NO MATCHING PRODUCT FOUND (REPORTED HONESTLY).")
            elif is_success:
                self.set_state(AgentState.COMPLETED)
                self.log("TASK COMPLETED SUCCESSFULLY.")
            elif final_state_str == "FAILED":
                self.set_state(AgentState.FAILED)
                self.log("TASK FAILED: Required procedural steps or task criteria could not be satisfied.")
            elif final_state_str == "INCOMPLETE":
                self.set_state(AgentState.FAILED)
                self.log("TASK INCOMPLETE: Required target page or requested information criteria were not satisfied.")
            else:
                self.set_state(AgentState.FAILED)
                self.log("TASK INCOMPLETE / FAILED: Required task criteria or constraints were not satisfied.")

            return {
                "success": is_success,
                "state": final_state_str,
                "verified": is_success,
                "summary": summary,
                "result": self.memory.extracted_data,
                "url": safe_page_url(page),
                "title": safe_page_title(page),
                "steps": self.memory.step_count,
                "history": [r.to_dict() for r in self.memory.action_history],
                "evaluated_candidates": self.evaluated_candidate_details,
            }

        except Exception as exc:
            self.set_state(AgentState.FAILED)
            self.log(f"Agent encountered an unhandled error: {exc}")
            logger.exception("Agent error: %s", exc)
            return {"success": False, "error": str(exc)}
        finally:
            self.controller.close()


def main() -> int:
    """CLI entry point for running browser agent."""
    setup_logging()
    logger.info("Initializing Browser Agent CLI...")

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = input("What should I do? > ")

    if not task.strip():
        logger.error("No task supplied.")
        return 1

    agent = BrowserAgent()
    result = agent.run(task)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
