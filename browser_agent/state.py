"""
State definitions, data models, and memory structures for the Browser Agent.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentState(str, Enum):
    """Lifecycle states of the browser agent."""
    IDLE = "IDLE"
    INITIALIZING = "INITIALIZING"
    OBSERVING = "OBSERVING"
    PERCEIVING = "PERCEIVING"
    THINKING = "THINKING"
    ACTING = "ACTING"
    VERIFYING = "VERIFYING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass
class ElementInfo:
    """Structured perception representation of an interactive or visible element."""
    id: int
    tag: str
    text: str
    element_type: str = ""
    role: str = ""
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, width, height
    center: tuple[int, int] = (0, 0)  # cx, cy
    attributes: dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    selector: str = ""
    accessible_name: str = ""
    label_text: str = ""
    checked: bool | None = None
    disabled: bool = False
    required: bool = False
    value: str = ""
    aria_expanded: bool | None = None
    aria_haspopup: str = ""
    aria_selected: bool | None = None
    aria_invalid: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tag": self.tag,
            "text": self.text,
            "type": self.element_type,
            "role": self.role,
            "bbox": list(self.bbox),
            "center": list(self.center),
            "attributes": self.attributes,
            "confidence": self.confidence,
            "accessible_name": self.accessible_name,
            "label_text": self.label_text,
            "checked": self.checked,
            "disabled": self.disabled,
            "required": self.required,
            "value": self.value,
            "aria_expanded": self.aria_expanded,
            "aria_haspopup": self.aria_haspopup,
            "aria_selected": self.aria_selected,
            "aria_invalid": self.aria_invalid,
        }

    def summary(self) -> str:
        """Compact string representation for prompts and UI."""
        parts = [f"[{self.id}] {self.tag}"]
        if self.element_type:
            parts.append(f"type='{self.element_type}'")
        if self.role:
            parts.append(f"role='{self.role}'")
        if self.accessible_name and self.accessible_name != self.text:
            parts.append(f"accessible_name='{self.accessible_name[:40]}'")
        if self.label_text and self.label_text != self.text:
            parts.append(f"label='{self.label_text[:40]}'")
        if self.value:
            parts.append(f"val='{self.value[:30]}'")
        if self.checked is not None:
            parts.append(f"checked={self.checked}")
        if self.disabled:
            parts.append("disabled=True")
        if self.aria_expanded is not None:
            parts.append(f"expanded={self.aria_expanded}")
        if self.text:
            clean_text = self.text.replace("\n", " ").strip()
            if len(clean_text) > 60:
                clean_text = clean_text[:57] + "..."
            parts.append(f"text='{clean_text}'")
        elif self.attributes.get("placeholder"):
            parts.append(f"placeholder='{self.attributes['placeholder']}'")
        elif self.attributes.get("aria-label"):
            parts.append(f"aria-label='{self.attributes['aria-label']}'")
        elif self.attributes.get("name"):
            parts.append(f"name='{self.attributes['name']}'")
        return " | ".join(parts)


@dataclass
class TabInfo:
    """Representation of an open browser tab / page."""
    page_id: str
    url: str
    title: str
    opened_from: str | None = None
    current_state: str = "active"  # "active", "background", "closed"
    task_relevance: float = 1.0
    is_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "url": self.url,
            "title": self.title,
            "opened_from": self.opened_from,
            "current_state": self.current_state,
            "task_relevance": self.task_relevance,
            "is_active": self.is_active,
        }



@dataclass
class ActionRecord:
    """Record of an executed action and its verification."""
    step: int
    action: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    success: bool = False
    verified: bool = False
    verification_reason: str = ""
    state_change: bool = False
    reasoning: str = ""
    confidence: float = 1.0
    url_before: str = ""
    url_after: str = ""
    title_before: str = ""
    title_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "action": self.action,
            "timestamp": self.timestamp,
            "success": self.success,
            "verified": self.verified,
            "verification_reason": self.verification_reason,
            "state_change": self.state_change,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "url_before": self.url_before,
            "url_after": self.url_after,
            "title_before": self.title_before,
            "title_after": self.title_after,
        }

    def summary(self) -> str:
        act_str = str(self.action)
        status = "succeeded" if self.success else "failed"
        ver = f", verified: {self.verified}" if self.verified else ""
        if self.verification_reason:
            ver += f" ({self.verification_reason})"
        return f"Step {self.step}: {act_str} -> {status}{ver}"


@dataclass
class ScrollState:
    """Tracks page scroll position, page dimensions, and boundaries."""
    current_y: int = 0
    max_scroll_y: int = 0
    viewport_height: int = 0
    visited_positions: set[int] = field(default_factory=set)
    reached_top: bool = True
    reached_bottom: bool = False
    scroll_direction: str = "down"
    scroll_count: int = 0
    consecutive_no_scroll_changes: int = 0

    def update(self, scroll_y: int, max_y: int, vp_height: int) -> bool:
        prev_y = self.current_y
        self.current_y = scroll_y
        self.max_scroll_y = max(self.max_scroll_y, max_y)
        self.viewport_height = vp_height
        self.visited_positions.add(scroll_y)
        self.reached_top = scroll_y <= 10
        self.reached_bottom = (scroll_y + vp_height >= max_y - 25) if max_y > 0 else False
        self.scroll_count += 1
        changed = abs(scroll_y - prev_y) > 15
        if not changed:
            self.consecutive_no_scroll_changes += 1
        else:
            self.consecutive_no_scroll_changes = 0
        return changed


@dataclass
class ExplorationState:
    """Tracks exploration stages, targets, and visited entities."""
    page_inspected: bool = False
    target_page_reached: bool = False
    search_performed: bool = False
    current_stage: str = "navigating"  # "navigating", "searching", "selecting_result", "inspecting_target", "exploring_content", "verifying"
    unproductive_actions: int = 0


@dataclass
class PageState:
    """Snapshot of the browser page state."""
    url: str
    title: str
    screenshot_path: str = ""
    annotated_screenshot_path: str = ""
    dom_hash: str = ""
    visual_hash: str = ""
    elements: list[ElementInfo] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentMemory:
    """Short-term and working memory for the browser agent."""
    task: str = ""
    normalized_query: str = ""
    start_url: str = ""
    current_url: str = ""
    current_title: str = ""
    step_count: int = 0
    max_steps: int = 10
    action_history: list[ActionRecord] = field(default_factory=list)
    recent_page_states: list[PageState] = field(default_factory=list)
    consecutive_failed_actions: int = 0
    identical_action_count: int = 0
    extracted_data: dict[str, Any] = field(default_factory=dict)
    extracted_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    constraints: Any = None
    task_plan: Any = None
    procedure_index: int = 0
    completed_procedures: list[str] = field(default_factory=list)
    completed_procedures_history: list[dict[str, Any]] = field(default_factory=list)
    failed_procedures: list[str] = field(default_factory=list)
    scroll_state: ScrollState = field(default_factory=ScrollState)
    exploration_state: ExplorationState = field(default_factory=ExplorationState)
    visited_urls: set[str] = field(default_factory=set)
    visited_titles: set[str] = field(default_factory=set)
    last_reasoning: str = ""
    last_confidence: float = 1.0
    tab_registry: list[TabInfo] = field(default_factory=list)
    active_tab_id: str = ""
    candidate_history: list[dict[str, Any]] = field(default_factory=list)
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    completion_evidence: dict[str, Any] = field(default_factory=dict)
    failure_evidence: list[str] = field(default_factory=list)
    download_records: list[dict[str, Any]] = field(default_factory=list)
    auth_required: bool = False
    auth_details: dict[str, Any] = field(default_factory=dict)

    @property
    def current_procedure(self) -> str | None:
        if not self.task_plan or not getattr(self.task_plan, "procedural_requirements", None):
            return None
        reqs = self.task_plan.procedural_requirements
        if 0 <= self.procedure_index < len(reqs):
            return reqs[self.procedure_index]
        return None

    @property
    def total_procedures(self) -> int:
        if not self.task_plan or not getattr(self.task_plan, "procedural_requirements", None):
            return 0
        return len(self.task_plan.procedural_requirements)

    def check_and_advance_open_procedure(self, page: Any) -> bool:
        """Check if the current procedure is an open/visit requirement satisfied by current page."""
        proc = self.current_procedure
        if not proc:
            return False
        proc_lower = proc.lower()

        # 1. Platform open/search, e.g. "open/search Youtube"
        if any(verb in proc_lower for verb in ["open/search", "open ", "visit ", "navigate to "]):
            curr_url = getattr(page, "url", "").lower()
            curr_title = page.title().lower() if callable(getattr(page, "title", None)) else str(getattr(page, "title", "")).lower()

            # If opening platform itself, e.g. "open/search Youtube"
            for plat in ["youtube", "wikipedia", "flipkart", "amazon", "duckduckgo", "google", "reddit", "github"]:
                if plat in proc_lower and plat in curr_url:
                    self._mark_procedure_completed(proc, page, f"Platform '{plat}' reached.")
                    return True

            # If opening target content or first relevant video
            if any(term in proc_lower for term in ["video", "result", "song", "article", "item", "link", "page"]):
                is_sat, reason = self.is_target_page_satisfied(page)
                if is_sat:
                    self._mark_procedure_completed(proc, page, reason)
                    return True

            # General target page check
            if page is not None and self.is_target_page_satisfied(page)[0]:
                self._mark_procedure_completed(proc, page, f"Target page reached for '{proc}'.")
                return True

        return False

    def _mark_procedure_completed(self, proc: str, page: Any, reason: str = "") -> None:
        """Helper to mark procedure completed and record in history."""
        self.completed_procedures.append(proc)
        self.completed_procedures_history.append({
            "index": self.procedure_index,
            "procedure": proc,
            "reason": reason,
            "page_url": getattr(page, "url", ""),
            "page_title": page.title() if callable(getattr(page, "title", None)) else str(getattr(page, "title", "")),
        })
        self.procedure_index += 1


    def add_action(self, record: ActionRecord) -> None:
        self.action_history.append(record)
        if not record.success or (not record.verified and not record.state_change):
            self.consecutive_failed_actions += 1
        else:
            self.consecutive_failed_actions = 0

    def get_recent_history_summary(self, limit: int = 6) -> list[str]:
        return [rec.summary() for rec in self.action_history[-limit:]]

    def has_repeated_last_action(self, new_action: dict[str, Any]) -> bool:
        if not self.action_history:
            return False
        last = self.action_history[-1].action
        if last.get("action") != new_action.get("action"):
            return False
        if last.get("action") == "click":
            return last.get("element_id") == new_action.get("element_id")
        if last.get("action") == "type":
            return last.get("element_id") == new_action.get("element_id") and last.get("text") == new_action.get("text")
        if last.get("action") == "navigate":
            return last.get("url") == new_action.get("url")
        return False

    def update_extracted_data(self, data: dict[str, Any]) -> None:
        placeholder_values = {
            "value visible on screen", "...", "none", "unknown", "n/a", "null", "", "undefined",
            "product name", "$title", "$search_term", "<value from page/screenshot>"
        }
        for k, v in data.items():
            if v is None:
                continue
            v_str = str(v).strip()
            if not v_str or v_str.lower() in placeholder_values:
                # Do not overwrite if we already have a valid value
                if k in self.extracted_data and self.extracted_data[k]:
                    continue
            self.extracted_data[k] = v

    def is_target_page_satisfied(self, page: Any) -> tuple[bool, str]:
        """
        Verify whether current page satisfies the task's required target entity/article/website.
        Prevents wrong-but-semantically-related pages (e.g. 'Languages of India' vs 'India')
        from falsely satisfying task requirements.
        """
        if page is None:
            return False, "No page provided to check target."

        curr_url = getattr(page, "url", "").lower()
        curr_title = ""
        try:
            curr_title = page.title().lower() if callable(getattr(page, "title", None)) else str(getattr(page, "title", "")).lower()
        except Exception:
            curr_title = ""

        # Search engine pages are never the final target
        if any(se in curr_url for se in ["duckduckgo.com", "google.com", "bing.com", "yahoo.com"]) and (
            "search" in curr_url or "?q=" in curr_url or "&q=" in curr_url or curr_url.rstrip("/").endswith((".com", ".org", ".net"))
        ):
            return False, "Currently on search engine page, not target."

        from urllib.parse import urlparse
        try:
            parsed = urlparse(curr_url)
            path = parsed.path.strip("/").lower()
        except Exception:
            path = ""

        is_portal_entry = (
            path in ("", "wiki/main_page", "index.html", "index.php")
            or "portal:" in curr_title.lower()
            or "portal:" in curr_url
            or curr_url.rstrip("/").lower() in {
                "https://www.wikipedia.org", "http://www.wikipedia.org",
                "https://wikipedia.org", "http://wikipedia.org",
                "https://en.wikipedia.org", "http://en.wikipedia.org",
                "https://www.flipkart.com", "https://flipkart.com",
                "https://www.amazon.in", "https://amazon.in",
                "https://www.amazon.com", "https://amazon.com",
            }
        )

        if not self.task_plan or not self.task_plan.target:
            if is_portal_entry and self.task_plan and (self.task_plan.requested_information or self.task_plan.destination):
                return False, "Currently on platform entry portal, content target not yet reached."
            return True, "No specific target required."

        if is_portal_entry:
            return False, f"Currently on platform entry portal '{curr_url}', expected target '{self.task_plan.target}'."

        # Search results pages are NEVER the target article/page
        is_search_results = (
            any(seg in curr_url for seg in ["/search", "?q=", "&q=", "/w/index.php?search=", "special:search", "/results", "search_query="])
            or "search results" in curr_title.lower()
        )
        if is_search_results:
            return False, f"Currently on search results page '{curr_title}', expected target '{self.task_plan.target}'."

        target = self.task_plan.target.lower().strip()
        target_type = getattr(self.task_plan, "target_type", "page").lower()

        # Extract main h1 heading if available
        h1 = ""
        if hasattr(page, "evaluate"):
            try:
                h1 = str(page.evaluate("() => document.querySelector('h1') ? document.querySelector('h1').innerText : ''")).strip().lower()
            except Exception:
                h1 = ""

        if h1 == "search results":
            return False, f"Current page is search results, expected target '{self.task_plan.target}'."

        import re
        target_words = [w for w in re.findall(r"\w+", target) if w not in {"the", "a", "an", "article", "page", "website", "site", "doc", "docs", "documentation", "official", "video", "song", "first", "relevant"}]
        if not target_words:
            target_words = [w for w in re.findall(r"\w+", target) if w not in {"the", "a", "an"}]

        # CASE 1: Article / Knowledge base (e.g. Wikipedia)
        if target_type == "article" or "wiki" in curr_url:
            title_entity = curr_title.split("-")[0].split("–")[0].split("|")[0].strip()
            title_words = [w for w in re.findall(r"\w+", title_entity)]
            h1_words = [w for w in re.findall(r"\w+", h1)]

            subtopic_words = {
                "languages", "history", "geography", "economy", "culture", "politics",
                "demographics", "music", "cinema", "government", "transport", "tourism",
                "wildlife", "climate", "education", "religion", "outline", "portal"
            }

            if h1:
                if any(pw in h1_words and pw not in target_words for pw in subtopic_words):
                    return False, f"Current article is specialized sub-topic '{h1}', expected primary article '{target}'."
                if h1_words == target_words:
                    return True, f"Article heading '{h1}' exactly matches target '{target}'."
                if " ".join(target_words) in h1:
                    return True, f"Article heading '{h1}' contains target '{target}'."
                return False, f"Current article heading '{h1}' does not match target '{target}'."

            if any(pw in title_words and pw not in target_words for pw in subtopic_words):
                return False, f"Current page title is specialized sub-topic '{curr_title}', expected primary article '{target}'."

            if title_words == target_words or " ".join(target_words) == title_entity:
                return True, f"Page title entity '{title_entity}' matches target '{target}'."
            return False, f"Page title '{curr_title}' does not match target article '{target}'."

        # CASE 2: Documentation / Website (e.g. Python documentation)
        if target_type in {"website", "documentation", "docs"}:
            matches_domain = any(tw in curr_url for tw in target_words)
            matches_title = any(tw in curr_title for tw in target_words)
            if matches_domain or matches_title:
                return True, f"Current page '{curr_title}' ({curr_url}) matches target '{target}'."
            return False, f"Current page '{curr_title}' does not match target '{target}'."

        # CASE 3: Video / Media / Content detail page
        is_video_content = any(seg in curr_url for seg in ["/watch", "watch?v=", "/video/", "/track/"]) or target_type == "video"
        if is_video_content:
            query_words = [
                w for w in re.findall(r"\w+", (self.task_plan.search_query or "").lower())
                if w not in {"the", "a", "an", "first", "relevant", "video", "song", "track", "tutorial"} and len(w) > 2
            ]
            check_words = query_words or target_words
            if check_words:
                match_count = sum(1 for w in check_words if w in curr_title or w in h1)
                if match_count >= max(1, len(check_words) // 2):
                    return True, f"Video detail page '{curr_title}' matches query/target words."
            if any(seg in curr_url for seg in ["/watch", "watch?v="]) and not is_search_results:
                return True, f"Video watch page reached: '{curr_title}'."

        # CASE 4: General target matching
        if target_words and all(tw in curr_title or tw in curr_url or tw in h1 for tw in target_words):
            return True, f"Current page matches target '{target}'."

        return False, f"Current page '{curr_title}' does not match target '{target}'."


    def is_information_satisfied(self, task: str = "", page: Any = None, constraints: Any = None) -> bool:
        """
        Check if all requested information items for the task have been grounded and satisfied.
        For constrained searches, satisfaction requires:
        1. All requested metadata fields are non-empty and grounded.
        2. Every constraint evaluates TRUE with grounded evidence.
        3. Missing evidence is strictly treated as unsatisfied.
        """
        # Handle TaskPlan passed as task or page
        if hasattr(task, "raw_task") and not isinstance(task, str):
            self.task_plan = task
            task = task.raw_task
        if hasattr(page, "raw_task") and not hasattr(page, "url"):
            self.task_plan = page
            page = None

        effective_constraints = constraints or self.constraints

        # If task concluded with honest NO_MATCH, it is satisfied as an honest completion
        if self.extracted_data.get("status") == "NO_MATCH":
            return True

        # Special skill intents satisfaction
        plan = self.task_plan
        intent_val = str(getattr(plan, "intent", "") or "").lower()
        task_type_val = getattr(plan, "task_type", None)
        if hasattr(task_type_val, "value"):
            task_type_val = task_type_val.value
        task_type_val = str(task_type_val or "").lower()
        all_intents = {intent_val, task_type_val}

        if "form_filling" in all_intents and (self.extracted_data.get("form_submitted") or self.extracted_data.get("form_filled") or self.completion_evidence.get("form_filled")):
            return True
        if "download" in all_intents and (self.download_records or self.extracted_data.get("downloaded_file") or self.completion_evidence.get("downloaded")):
            return True
        if "upload" in all_intents and (self.extracted_data.get("uploaded") or self.completion_evidence.get("uploaded")):
            return True
        if "comparison" in all_intents and (self.extracted_data.get("comparison") or self.completion_evidence.get("comparison_ready")):
            return True
        if "table_understanding" in all_intents and (self.extracted_data.get("table_data") or self.completion_evidence.get("table_ready")):
            return True

        # Check target page satisfaction if task has a required target or navigation requirement
        if self.task_plan and (self.task_plan.navigation_requirement or self.task_plan.target):
            if page is not None:
                matched, reason = self.is_target_page_satisfied(page)
                if not matched:
                    return False

        # If navigation-only or media_interaction intent and target page is satisfied, no further info needed
        if self.task_plan and self.task_plan.intent in ("navigation", "media_interaction"):
            if page is not None and self.is_target_page_satisfied(page)[0]:
                return True

        task_text = task.raw_task if hasattr(task, "raw_task") else (task or getattr(self.task_plan, "raw_task", None) or self.task)
        if not task_text:
            return bool(self.extracted_data)

        lower = str(task_text).lower()
        info_triggers = [
            "tell me", "what is", "find the", "check the", "get the",
            "give me", "show me", "exact page heading", "page title", "page heading",
            "product name", "price", "rating", "find a", "find "
        ]
        is_info_task = any(t in lower for t in info_triggers)

        # If page is still on search engine root/results while search intent exists, not satisfied
        if page is not None:
            curr_url = getattr(page, "url", "").lower()
            is_search_engine = any(se in curr_url for se in ["duckduckgo.com", "google.com", "bing.com", "yahoo.com"])
            has_search_intent = bool(self.normalized_query and self.normalized_query != self.task)
            if is_search_engine and has_search_intent:
                return False

            # If task is an e-commerce / product finding task, must be on an actual product detail page
            is_product_task = (
                any(kw in lower for kw in ["product", "laptop bag", "headphone", "shoe", "item", "buy", "price and rating"])
                or (effective_constraints and effective_constraints.has_constraints())
            )
            if is_product_task:
                is_product_page = any(seg in curr_url for seg in ["/p/", "/dp/", "/product/", "/item/"])
                if not is_product_page:
                    return False

        reqs = []
        if self.task_plan and getattr(self.task_plan, "requested_information", None):
            for info_item in self.task_plan.requested_information:
                item_lower = info_item.lower()
                if "heading" in item_lower or "header" in item_lower:
                    reqs.append("heading")
                elif "title" in item_lower and "product" not in item_lower:
                    reqs.append("title")
                elif "url" in item_lower:
                    reqs.append("url")
                elif "population" in item_lower:
                    reqs.append("population")
                elif "capital" in item_lower:
                    reqs.append("capital")
                elif "language" in item_lower:
                    reqs.append("language")
                elif "price" in item_lower:
                    reqs.append("price")
                elif "rating" in item_lower:
                    reqs.append("rating")
                else:
                    reqs.append(item_lower)
        else:
            if "heading" in lower or "header" in lower:
                reqs.append("heading")
            if "page title" in lower or "title of the page" in lower or ("title" in lower and "product" not in lower):
                reqs.append("title")
            if "url" in lower or ("link" in lower and not re.search(r"\b(?:click|press|select|open|follow)\s+(?:on\s+)?(?:a\s+|the\s+)?link\b", lower)):
                reqs.append("url")
        if "version" in lower:
            reqs.append("version")
        if "price" in lower or (effective_constraints and (effective_constraints.max_price is not None or effective_constraints.min_price is not None)):
            reqs.append("price")
        if "rating" in lower or (effective_constraints and (effective_constraints.exact_rating is not None or effective_constraints.min_rating is not None)):
            reqs.append("rating")
        if ("name" in lower and ("product" in lower or "item" in lower or "tell me its name" in lower)) or "product name" in lower:
            reqs.append("name")
        if "population" in lower:
            reqs.append("population")
        if "capital" in lower:
            reqs.append("capital")
        if "official language" in lower or "language" in lower:
            reqs.append("language")

        if not reqs and not (effective_constraints and effective_constraints.has_constraints()):
            return is_info_task and len(self.extracted_data) > 0

        # Check if all identified reqs are present with non-placeholder values in extracted_data
        placeholder_values = {
            "value visible on screen", "...", "none", "unknown", "n/a", "null", "", "undefined",
            "product name", "$title", "$search_term", "<value from page/screenshot>"
        }
        for req in reqs:
            found = False
            for k, v in self.extracted_data.items():
                k_lower = k.lower()
                # Specific matching to avoid matching 'page_title' as 'name'
                match_key = False
                if req == "heading" and ("heading" in k_lower or "header" in k_lower):
                    match_key = True
                elif req == "title" and ("title" in k_lower and "product" not in k_lower):
                    match_key = True
                elif req == "url" and ("url" in k_lower or "link" in k_lower):
                    match_key = True
                elif req == "version" and "version" in k_lower:
                    match_key = True
                elif req == "price" and ("price" in k_lower or "cost" in k_lower):
                    match_key = True
                elif req == "rating" and ("rating" in k_lower or "star" in k_lower or "score" in k_lower):
                    match_key = True
                elif req == "name" and ("name" in k_lower or "product" in k_lower or "item" in k_lower):
                    match_key = True
                elif req == "population" and "population" in k_lower:
                    match_key = True
                elif req == "capital" and "capital" in k_lower:
                    match_key = True
                elif req == "language" and ("language" in k_lower or "lang" in k_lower):
                    match_key = True

                if match_key:
                    v_str = str(v).strip()
                    if v_str and v_str.lower() not in placeholder_values and len(v_str) > 1:
                        found = True
                        break
            if not found:
                return False

        # Constraint evaluation check
        if effective_constraints and effective_constraints.has_constraints():
            from browser_agent.constraints import evaluate_candidate
            page_text = ""
            if page is not None and hasattr(page, "evaluate"):
                try:
                    page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception:
                    page_text = ""
            eval_res = evaluate_candidate(self.extracted_data, page_text, effective_constraints)
            if not eval_res["satisfied"]:
                return False

        return True

    def can_advance_procedure(
        self,
        page: Any,
        action: dict[str, Any],
        verification: Any,
    ) -> tuple[bool, str]:
        """
        Validate whether the verified action satisfies the current procedure's postcondition.
        Returns (can_advance: bool, reason: str).
        """
        proc = self.current_procedure
        if not proc:
            return False, "No active procedure."

        proc_lower = proc.lower()
        act_type = str(action.get("action", "")).lower()
        verified = getattr(verification, "verified", False)
        state_changed = getattr(verification, "state_changed", False)

        # 1. Open / visit / navigate
        if any(verb in proc_lower for verb in ["open", "visit", "navigate to"]):
            if page is not None and self.is_target_page_satisfied(page)[0]:
                return True, f"Target page reached for '{proc}'."
            return False, f"Page does not satisfy target page for '{proc}'."

        # 2. Click link or button
        if any(verb in proc_lower for verb in ["click", "press", "select"]):
            if act_type != "click":
                return False, f"Expected action 'click' for procedure '{proc}', got '{act_type}'."
            if not verified:
                return False, f"Click action was not verified for '{proc}'."

            m = re.search(r"\b(?:called|titled|named)\s+[\"']?([^\"'\n\r]+)[\"']?", proc, re.I)
            target_name = m.group(1).strip().lower() if m else re.sub(r"^(?:click|press|select)\s+(?:on\s+)?(?:the\s+|a\s+)?(?:link\s+|button\s+)?", "", proc, flags=re.I).strip().lower()
            target_name = target_name.strip("\"'")

            act_target = str(action.get("target") or action.get("text") or action.get("reasoning") or "").lower()
            curr_url = getattr(page, "url", "").lower()
            curr_title = page.title().lower() if callable(getattr(page, "title", None)) else ""

            target_words = [w for w in re.findall(r"\w+", target_name) if len(w) > 2]
            target_matched = (
                target_name in act_target
                or (target_words and all(w in act_target for w in target_words))
                or (target_words and all(w in curr_url or w in curr_title for w in target_words))
            )

            if not target_matched:
                return False, f"Clicked element/target did not match procedural requirement '{target_name}'."

            # Postcondition: click must have produced a state change or navigation
            details = getattr(verification, "details", {}) or {}
            has_navigated = details.get("url_changed", False) or details.get("navigated", False) or state_changed
            if not has_navigated and not state_changed:
                return False, f"Click on '{target_name}' produced no state change or navigation."

            return True, f"Successfully clicked and navigated to '{target_name}'."

        # 3. Go back / return
        if any(v in proc_lower for v in ["go back", "navigate back", "return"]):
            if act_type != "go_back":
                return False, f"Expected action 'go_back' for procedure '{proc}', got '{act_type}'."
            if not verified:
                return False, f"go_back action was not verified for '{proc}'."

            # Requirement 5: go_back must verify that the expected prior target page was actually reached before advancing.
            dest_match = re.search(r"(?:to|into)\s+(?:the\s+)?([a-zA-Z0-9\s\-_]+?)(?:\s+article|\s+page|\s+documentation|$)", proc, re.I)
            expected_dest = dest_match.group(1).strip().lower() if dest_match else ""

            if expected_dest:
                if self.task_plan and self.task_plan.target and expected_dest in self.task_plan.target.lower():
                    is_target, reason = self.is_target_page_satisfied(page)
                    if not is_target:
                        return False, f"go_back did not return to expected target page '{expected_dest}': {reason}"
                else:
                    curr_title = page.title().lower() if callable(getattr(page, "title", None)) else ""
                    curr_url = getattr(page, "url", "").lower()
                    if expected_dest not in curr_title and expected_dest not in curr_url:
                        return False, f"go_back did not return to expected destination '{expected_dest}'."
            elif self.task_plan and self.task_plan.target:
                is_target, reason = self.is_target_page_satisfied(page)
                if not is_target:
                    return False, f"go_back did not return to target page '{self.task_plan.target}': {reason}"

            return True, f"Successfully executed go_back to expected destination for '{proc}'."

        # 4. Scroll
        if "scroll" in proc_lower:
            if act_type == "scroll" and verified:
                return True, f"Successfully executed scroll for '{proc}'."
            return False, f"Expected verified scroll for '{proc}'."

        # 5. Search for query
        if any(term in proc_lower for term in ["search for", "search/find"]):
            curr_url = getattr(page, "url", "").lower()
            is_search_res = any(s in curr_url for s in ["/results", "search_query=", "?q=", "&q=", "/search"])
            if (act_type in ("type", "press_key") and verified) or is_search_res:
                return True, f"Search executed for '{proc}'."
            return False, f"Expected search action for '{proc}'."

        # 6. Play media / start playback
        if any(term in proc_lower for term in ["play video", "play song", "start playback"]):
            if act_type in ("play", "play_media", "start_playback", "click") and verified:
                return True, f"Playback initiated for '{proc}'."
            if page is not None and hasattr(page, "evaluate"):
                try:
                    is_p = page.evaluate("() => Array.from(document.querySelectorAll('video, audio')).some(m => !m.paused && !m.ended)")
                    if is_p:
                        return True, f"Media is playing for '{proc}'."
                except Exception:
                    pass
            return False, f"Playback not verified for '{proc}'."

        # 7. Verify playback
        if "verify playback" in proc_lower:
            details = getattr(verification, "details", {}) or {}
            if details.get("isPlaying"):
                return True, f"Media playback verified active for '{proc}'."
            if page is not None and hasattr(page, "evaluate"):
                try:
                    is_p = page.evaluate("""() => {
                        const m = Array.from(document.querySelectorAll('video, audio'));
                        const isPlaying = m.some(v => !v.paused && !v.ended);
                        const pauseBtn = document.querySelector('button[aria-label*="Pause" i], [aria-label*="Pause video" i]');
                        return isPlaying || !!pauseBtn;
                    }""")
                    if is_p:
                        return True, f"Media playback confirmed active for '{proc}'."
                except Exception:
                    pass
            if verified and (act_type in ("play", "play_media", "wait") or state_changed):
                return True, f"Playback state verified for '{proc}'."
            return False, f"Active media playback not observed for '{proc}'."

        # 8. Wait for completion / video ends
        if any(term in proc_lower for term in ["video completion", "video ends", "after it ends"]):
            if page is not None and hasattr(page, "evaluate"):
                try:
                    ended = page.evaluate("() => Array.from(document.querySelectorAll('video, audio')).some(m => m.ended)")
                    if ended:
                        return True, f"Video reached end for '{proc}'."
                except Exception:
                    pass
            if act_type == "wait" and verified:
                return True, f"Observed playback completion for '{proc}'."
            return False, f"Video completion not yet reached for '{proc}'."

        if verified and state_changed:
            return True, f"Executed verified action for '{proc}'."

        return False, f"Action not verified for procedure '{proc}'."

    def advance_procedure(
        self,
        page: Any,
        action: dict[str, Any],
        verification: Any,
    ) -> bool:
        """
        Advance procedure_index by exactly one if postcondition is verified.
        Returns True if advanced, False otherwise.
        """
        can_adv, reason = self.can_advance_procedure(page, action, verification)
        if can_adv:
            proc = self.current_procedure
            if proc:
                self.completed_procedures.append(proc)
                self.completed_procedures_history.append({
                    "index": self.procedure_index,
                    "procedure": proc,
                    "action": action,
                    "reason": reason,
                    "page_url": getattr(page, "url", ""),
                    "page_title": page.title() if callable(getattr(page, "title", None)) else str(getattr(page, "title", "")),
                })
            self.procedure_index += 1

            # Multi-stage query update: If next procedure is "search for <next_query>",
            # update normalized_query and task_plan to <next_query>!
            next_proc = self.current_procedure
            if next_proc:
                next_search_m = re.search(r"(?:search\s+for|search/find|play|open)\s+(.+)$", next_proc, re.I)
                if next_search_m:
                    next_q = next_search_m.group(1).strip()
                    if next_q.lower() not in ("video", "the video", "it", "song", "audio", "first relevant video", "first video"):
                        self.normalized_query = next_q
                        if self.task_plan:
                            self.task_plan.search_query = next_q
                            self.task_plan.target = next_q
            return True
        return False


    def is_procedure_satisfied(self, page: Any = None) -> tuple[bool, str]:
        """
        Check whether all procedural requirements in the task plan have been completed in order.
        Returns (satisfied, reason).
        """
        if not self.task_plan or not getattr(self.task_plan, "procedural_requirements", None):
            return True, "No procedural requirements specified."

        if getattr(self, "failed_procedures", None):
            failed_str = ", ".join(self.failed_procedures)
            return False, f"Procedural requirement failed: {failed_str}"

        # If current procedure is an open/visit requirement, check if satisfied on current page
        if page is not None and self.current_procedure:
            self.check_and_advance_open_procedure(page)

        total = len(self.task_plan.procedural_requirements)
        if self.procedure_index >= total:
            return True, f"All {total} procedural requirements completed successfully."

        curr = self.current_procedure
        return False, f"Procedural requirements remaining ({self.procedure_index}/{total} completed): pending '{curr}'"

    def is_task_satisfied(
        self,
        page: Any = None,
        task: str | None = None,
        effective_constraints: Any = None,
    ) -> tuple[bool, str]:
        """
        Comprehensive task satisfaction check distinguishing:
        1. target_satisfied (correct page reached)
        2. procedure_satisfied (all intermediate actions completed)
        3. information_satisfied (requested factual fields extracted)
        4. constraints_satisfied (for product / e-commerce tasks)
        """
        # If task concluded with honest NO_MATCH, it is satisfied as an honest completion
        if self.extracted_data.get("status") == "NO_MATCH":
            return True, "Honest NO_MATCH reported."

        # 1. Target page satisfaction (if required)
        if self.task_plan and (self.task_plan.navigation_requirement or self.task_plan.target):
            if page is not None:
                matched, reason = self.is_target_page_satisfied(page)
                if not matched:
                    return False, f"Target page not satisfied: {reason}"

        # 2. Procedure satisfaction (if procedural requirements exist)
        proc_sat, proc_reason = self.is_procedure_satisfied(page)
        if not proc_sat:
            return False, f"Procedure not satisfied: {proc_reason}"

        # 3. Information satisfaction
        info_sat = self.is_information_satisfied(task=task or "", page=page, constraints=effective_constraints)
        if not info_sat:
            return False, "Requested information not fully satisfied."

        return True, "All task requirements (target, procedure, information) satisfied."
