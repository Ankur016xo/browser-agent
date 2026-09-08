"""
Task Planning and Goal State Engine.
Parses natural language instructions into structured, goal-first TaskPlan models
preserving destination, target entity/page, search query, intent, procedural requirements,
and completion conditions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from browser_agent.logging import get_logger

logger = get_logger(__name__)

KNOWN_PLATFORMS = {
    "wikipedia": "https://www.wikipedia.org",
    "duckduckgo": "https://duckduckgo.com",
    "google": "https://www.google.com",
    "bing": "https://www.bing.com",
    "flipkart": "https://www.flipkart.com",
    "amazon": "https://www.amazon.in",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
    "yahoo": "https://www.yahoo.com",
    "youtube": "https://www.youtube.com",
    "ebay": "https://www.ebay.com",
    "walmart": "https://www.walmart.com",
}

from enum import Enum


class TaskType(str, Enum):
    """12 Comprehensive browser agent task types."""
    NAVIGATION = "navigation"
    INFORMATION_RETRIEVAL = "information_extraction"
    SEARCH = "search"
    FORM_FILLING = "form_filling"
    FILTERING = "filtering"
    COMPARISON = "comparison"
    MEDIA_INTERACTION = "media_interaction"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    MULTI_PAGE = "multi_page"
    MULTI_STAGE = "multi_stage"
    MIXED = "mixed"


@dataclass
class TaskPlan:
    """
    Structured, goal-first representation of a user's instruction.
    Separates the search query from the destination, target page,
    procedural requirements, and information to extract.
    """
    raw_task: str
    destination: str = ""
    destination_url: str | None = None
    target: str = ""
    target_type: str = "page"  # "page", "article", "website", "product", "person"
    search_query: str = ""
    intent: str = "navigation"  # "navigation", "information_extraction", "product_search", "ranked_search", "form_filling", "comparison", "media_interaction"
    task_type: TaskType | str = TaskType.NAVIGATION
    requested_information: list[str] = field(default_factory=list)
    navigation_requirement: str = ""
    procedural_requirements: list[str] = field(default_factory=list)
    completion_conditions: list[str] = field(default_factory=list)
    ranking_field: str | None = None
    ranking_order: str = "desc"
    form_fields: dict[str, Any] = field(default_factory=dict)
    comparison_fields: list[str] = field(default_factory=list)
    comparison_count: int = 0
    target_date: str = ""
    table_query: str = ""
    # New fields for regression fix
    quantity: int = 1
    constraints: list[dict[str, Any]] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"destination='{self.destination}'",
            f"target='{self.target}'",
            f"query='{self.search_query}'",
            f"intent='{self.intent}'",
            f"type='{self.task_type}'",
        ]
        if self.navigation_requirement:
            parts.append(f"nav_req='{self.navigation_requirement}'")
        if self.requested_information:
            parts.append(f"info={self.requested_information}")
        if self.form_fields:
            parts.append(f"form_fields={list(self.form_fields.keys())}")
        if self.comparison_fields:
            parts.append(f"compare={self.comparison_fields}")
        if self.ranking_field:
            parts.append(f"ranking={self.ranking_field} {self.ranking_order}")
        return ", ".join(parts)


GENERIC_TARGETS = {
    "product", "suitable product", "relevant product", "most relevant product",
    "item", "a product", "the product", "first product", "result", "search result",
    "link", "first link", "website", "page",
    "video", "a video", "the video", "first video", "first relevant video", "relevant video",
    "song", "a song", "the song", "first song", "first relevant song", "relevant song",
    "track", "a track", "the track", "first track",
}


def parse_task_plan(task: str) -> TaskPlan:
    """
    Parse a user instruction into a structured TaskPlan.
    Distinguishes:
    1. DESTINATION (e.g. Wikipedia, DuckDuckGo, direct URL)
    2. TARGET PAGE / ENTITY (e.g. "India", "official Python documentation website")
    3. SEARCH QUERY (what to type in search boxes - e.g. "India", NOT "capital of India")
    4. REQUESTED INFORMATION (what to extract - e.g. "capital", "population")
    5. PROCEDURAL / NAVIGATION REQUIREMENTS (e.g. "open the India article")
    6. SUCCESS CONDITIONS
    """
    clean_task = task.strip()
    if not clean_task:
        return TaskPlan(raw_task="")

    lower = clean_task.lower()

    # 1. DESTINATION EXTRACTION
    destination = ""
    destination_url = None

    url_match = re.search(r"https?://[^\s,;]+", clean_task)
    if url_match:
        destination_url = url_match.group(0)
        destination = destination_url
    else:
        for plat, default_url in KNOWN_PLATFORMS.items():
            if re.search(rf"\b{plat}\b", clean_task, re.IGNORECASE):
                destination = plat.lower()
                destination_url = default_url
                break

    # 2. RANKED SEARCH & PRODUCT SEARCH DETECTION
    is_ranked = bool(re.search(
        r"\b(?:highest\s+rated|highest\s+ratings?|best\s+ratings?|best\s+rated|top\s+rated|highest\s+scoring|cheapest|lowest\s+price|most\s+expensive)\b",
        lower
    ))
    ranking_field = None
    ranking_order = "desc"
    if is_ranked:
        if re.search(r"\b(?:cheapest|lowest\s+price)\b", lower):
            ranking_field = "price"
            ranking_order = "asc"
        else:
            ranking_field = "rating"
            ranking_order = "desc"

    is_product = is_ranked or any(
        kw in lower
        for kw in ["product", "laptop bag", "bag", "bags", "shoe", "shoes", "headphone", "headphones", "earbuds", "laptop", "laptops", "buy", "under ₹", "under $", "price <"]
    )

    # 3. ENTITY & INFORMATION EXTRACTION FOR NON-PRODUCT TASKS
    target = ""
    target_type = "page"
    navigation_req = ""
    requested_info: list[str] = []
    quantity = 1
    constraints: list[dict[str, Any]] = []
    output_fields: list[str] = []

    qty_m = re.search(r"\b(\d+)\s+(?:units?|items?)\b", lower)
    if qty_m:
        quantity = int(qty_m.group(1))
    else:
        # Handle word numbers (e.g., three, five)
        word_numbers = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
        for word, num in word_numbers.items():
            if re.search(r"\\b"+word+r"\\b", lower):
                quantity = num
                break

    price_m = re.search(r"(?:under|below|less\s+than)\s+[\$₹]?([\d,]+)", lower)
    if price_m:
        constraints.append({"field": "price", "op": "<", "value": int(price_m.group(1).replace(",", ""))})
    # Rating constraint detection (e.g., rating above 4)
    rating_m = re.search(r"rating\s+(?:above|greater\s+than|over)\s+([\d\.]+)", lower)
    if rating_m:
        constraints.append({"field": "rating", "op": ">", "value": float(rating_m.group(1))})

    if "name" in lower:
        output_fields.append("name")
    if "price" in lower:
        output_fields.append("price")
    if "rating" in lower:
        output_fields.append("rating")
    if "url" in lower:
        output_fields.append("url")
    # Known metadata extraction triggers
    if "official language" in lower:
        requested_info.append("official language")
    elif "language" in lower and ("what is the language" in lower or "find the language" in lower or "find language" in lower or "official language" in lower):
        requested_info.append("language")

    if "capital" in lower and ("capital of" in lower or "what is the capital" in lower or "find the capital" in lower or "its capital" in lower):
        requested_info.append("capital")
    if "population" in lower and ("population of" in lower or "what is the population" in lower or "find the population" in lower or "its population" in lower):
        requested_info.append("population")
    if "birth date" in lower or "date of birth" in lower or "born" in lower:
        requested_info.append("birth date")

    if "heading" in lower or "header" in lower:
        requested_info.append("heading")
    if "page title" in lower or "title of the page" in lower:
        requested_info.append("page title")
    elif "title" in lower and "product" not in lower:
        requested_info.append("title")
        # Recognize various synonyms for price and map to canonical 'price'
        if any(word in lower for word in ["price", "prize", "cost", "amount", "product price", "current price"]):
            requested_info.append("price")
    if "rating" in lower:
        requested_info.append("rating")
    if "product name" in lower or "name of the product" in lower:
        requested_info.append("product_name")

    if not is_product:
        # Pattern A: "find (the|his|her|its)? <info> of/for/in <target>"
        # e.g. "find the capital of India", "find the population of India", "What is the capital of France?"
        m_of = re.search(
            r"\b(?:find|what\s+is|get|check|extract|tell\s+me)\s+(?:the\s+|its\s+|his\s+|her\s+)?([a-zA-Z\s]+?)\s+(?:of|for|in)\s+([a-zA-Z0-9\s\.\-_]+?)(?:\s+(?:according\s+to|on|in|from|via)\s+[a-zA-Z0-9\.\-_]+)?(?:[,\.;\?!]|\s+and\s+|$)",
            clean_task,
            re.IGNORECASE,
        )
        if m_of:
            cand_info = m_of.group(1).strip()
            cand_target = m_of.group(2).strip()
            cand_target = re.sub(r"^(?:the|a|an)\s+", "", cand_target, flags=re.I).strip()
            cand_target = re.sub(r"\s+(?:article|page|website|site)$", "", cand_target, flags=re.I).strip()
            if cand_target and cand_target.lower() not in KNOWN_PLATFORMS:
                target = cand_target
                target_type = "article" if destination == "wikipedia" else "page"
            if cand_info:
                info_clean = re.sub(r"\s+(?:city|number|data)$", "", cand_info, flags=re.I).strip().lower()
                if info_clean not in [x.lower() for x in requested_info]:
                    requested_info.append(info_clean)

        # Pattern B: "find <target>'s <info>"
        # e.g. "Find India's capital on Wikipedia.", "What is India's population on Wikipedia?"
        if not target:
            m_poss = re.search(
                r"\b(?:find|what\s+is|get|check|extract|tell\s+me)\s+([a-zA-Z0-9\s\.\-_]+?)'s\s+([a-zA-Z\s]+?)(?:\s+(?:according\s+to|on|in|from|via)\s+[a-zA-Z0-9\.\-_]+)?(?:[,\.;\?!]|\s+and\s+|$)",
                clean_task,
                re.IGNORECASE,
            )
            if m_poss:
                cand_target = m_poss.group(1).strip()
                cand_info = m_poss.group(2).strip()
                if cand_target.lower() not in KNOWN_PLATFORMS:
                    target = cand_target
                    target_type = "article" if destination == "wikipedia" else "page"
                if cand_info:
                    info_clean = re.sub(r"\s+(?:city|number|data)$", "", cand_info, flags=re.I).strip().lower()
                    if info_clean not in [x.lower() for x in requested_info]:
                        requested_info.append(info_clean)

        # Pattern C: "Search <dest>? for <target> and find (his|her|its|the)? <info>"
        # e.g. "Search Wikipedia for India and tell me its capital.", "Look up India on Wikipedia and report its capital."
        if not target:
            m_search_info = re.search(
                r"\b(?:search\s+(?:(?:on|in|using|with|via)\s+)?(?:[a-zA-Z0-9\.\-_]+\s+)?(?:for\s+)|look\s*up\s+)([a-zA-Z0-9\s\.\-_]+?)(?:\s+(?:on|in|via)\s+[a-zA-Z0-9\.\-_]+)?\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?:find|tell\s+me|report|get|check)\s+(?:his|her|its|the)?\s*([a-zA-Z\s]+?)(?:[,\.;\?!]|$)",
                clean_task,
                re.IGNORECASE,
            )
            if m_search_info:
                cand_target = m_search_info.group(1).strip()
                cand_info = m_search_info.group(2).strip()
                cand_target = re.sub(r"^(?:the|a|an)\s+", "", cand_target, flags=re.I).strip()
                if cand_target.lower() not in KNOWN_PLATFORMS:
                    target = cand_target
                    target_type = "article" if destination == "wikipedia" else "page"
                if cand_info:
                    info_clean = re.sub(r"\s+(?:city|number|data)$", "", cand_info, flags=re.I).strip().lower()
                    if info_clean not in [x.lower() for x in requested_info]:
                        requested_info.append(info_clean)

        # Pattern D: "open/visit (the)? <target> (article|page)? and find (his|her|its|the)? <info>"
        # e.g. "Go to Wikipedia, open India, and find its capital."
        if not target:
            m_open_info = re.search(
                r"\b(?:open|visit|navigate\s+to)\s+(?:the\s+)?([a-zA-Z0-9\s\.\-_]+?)(?:\s+(?:article|page|website|site))?\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?:find|tell\s+me|get|report|check)\s+(?:his|her|its|the)?\s*([a-zA-Z\s]+?)(?:[,\.;\?!]|$)",
                clean_task,
                re.IGNORECASE,
            )
            if m_open_info:
                cand_target = m_open_info.group(1).strip()
                cand_info = m_open_info.group(2).strip()
                cand_target = re.sub(r"^(?:the|a|an)\s+", "", cand_target, flags=re.I).strip()
                if cand_target.lower() not in KNOWN_PLATFORMS:
                    target = cand_target
                    target_type = "article" if destination == "wikipedia" else "page"
                    navigation_req = f"open the {target} article" if destination == "wikipedia" else f"open {target}"
                if cand_info:
                    info_clean = re.sub(r"\s+(?:city|number|data)$", "", cand_info, flags=re.I).strip().lower()
                    if info_clean not in [x.lower() for x in requested_info]:
                        requested_info.append(info_clean)

        # Pattern E: "open/visit the <target> (article|page|website|site|portal)"
        if not target:
            open_match = re.search(
                r"\b(?:open|visit|navigate\s+to)\s+(?:the\s+)?([a-zA-Z0-9\s\.\-_]+?)(?:[,\.;]|\s+and\s+|$)",
                clean_task,
                re.IGNORECASE,
            )
            if open_match:
                full_target = open_match.group(1).strip()
                type_match = re.search(r"\s+(website|site|portal|page|article)$", full_target, re.IGNORECASE)
                if type_match:
                    target_type = type_match.group(1).lower()
                    base_target = full_target[:type_match.start()].strip()
                    target = base_target if base_target else full_target
                else:
                    target = full_target
                if target.lower() in KNOWN_PLATFORMS:
                    target = ""
                else:
                    navigation_req = f"open the {full_target}".strip()

    # Clean target
    target = re.sub(r"^(?:the|a|an)\s+", "", target, flags=re.IGNORECASE).strip()
    if target.lower() in GENERIC_TARGETS:
        target = ""
        navigation_req = ""

    # 4. PROCEDURAL CLAUSES EXTRACTION & MULTI-STAGE TEMPORAL PARSING
    procedural_requirements: list[str] = []
    is_media_task = bool(re.search(
        r"\b(?:play\s+it|play\s+video|play\s+song|play\s+[a-zA-Z0-9\-_]+|start\s+playback|video\s+ends|after\s+it\s+ends)\b",
        lower
    ))
    has_temporal = bool(re.search(
        r"\b(?:after\s+(?:the\s+)?(?:video|audio|song|track|it)\s+(?:ends|finishes|completes)|when\s+(?:the\s+)?(?:video|audio|song|track|it)\s+(?:ends|finishes))\b",
        lower
    ))

    if is_media_task or has_temporal:
        procedural_requirements = _parse_media_procedural_requirements(clean_task, destination)
    else:
        raw_clauses = re.split(r",\s*(?:(?:and\s+then|then|and)\s+)?|\s*;\s*|\s+(?:and\s+then|then|and)\s+", clean_task)
        for clause in raw_clauses:
            clause_str = re.sub(r"^(?:and\s+then|then|and)\s+", "", clause.strip(), flags=re.IGNORECASE).strip().rstrip(".;,")
            clause_lower = clause_str.lower()
            if not clause_str:
                continue
            # Detect output requirement clauses and extract fields instead of treating as procedural steps
            if re.search(r"\breturn\b", clause_lower):
                # Extract desired output fields (name, price, rating, url, title)
                for field in ["name", "price", "rating", "url", "title"]:
                    if field in clause_lower and field not in output_fields:
                        output_fields.append(field)
                # Do not add to procedural requirements
                continue
            if re.match(r"^(?:open|visit|navigate\s+to)\b", clause_lower):
                cand = re.sub(r"^(?:open|visit|navigate\s+to)\s+(?:the\s+)?", "", clause_str, flags=re.I).strip()
                if cand.lower() not in KNOWN_PLATFORMS:
                    procedural_requirements.append(clause_str)
            elif re.match(r"^(?:click|press|select)\b", clause_lower):
                procedural_requirements.append(clause_str)
            elif re.match(r"^(?:go\s+back|navigate\s+back|return)\b", clause_lower):
                procedural_requirements.append(clause_str)
            elif re.match(r"^(?:scroll\s+(?:down|up))\b", clause_lower):
                procedural_requirements.append(clause_str)

        if not navigation_req:
            open_pr = next((pr for pr in procedural_requirements if re.match(r"^(?:open|visit|navigate\s+to)\b", pr.lower())), None)
            if open_pr:
                navigation_req = open_pr
            elif target:
                navigation_req = f"open the {target} article" if destination == "wikipedia" else f"open {target}"

        if navigation_req and not any(navigation_req.lower() == pr.lower() for pr in procedural_requirements):
            procedural_requirements.insert(0, navigation_req)

    # Explicit search for
    explicit_search_for: str | None = None
    known_platforms_pat = "|".join(re.escape(k) for k in KNOWN_PLATFORMS.keys())
    search_for_match = re.search(
        rf"\b(?:search\s+(?:(?:on|in|using|with|via)\s+)?(?:(?:{known_platforms_pat})\s+)?(?:for\s+)|look\s*up\s+)(.+?)(?:[,\.;\?!]|\s+and\s+|$)",
        clean_task,
        re.IGNORECASE,
    )
    if search_for_match:
        explicit_search_for = search_for_match.group(1).strip()
        explicit_search_for = re.sub(rf"\s+(?:on|in|via|from|at)\s+(?:{known_platforms_pat})$", "", explicit_search_for, flags=re.IGNORECASE).strip()
        explicit_search_for = re.sub(r"^(?:the|a|an)\s+", "", explicit_search_for, flags=re.IGNORECASE).strip()
        explicit_search_for = re.sub(r"\s+(?:under|below|above|less\s+than|more\s+than|priced\s+at)\s+.*$", "", explicit_search_for, flags=re.IGNORECASE).strip()
        explicit_search_for = re.sub(r"\s+with\s+(?:the\s+)?(?:best|highest|top|good)\s+rating.*$", "", explicit_search_for, flags=re.IGNORECASE).strip()
        explicit_search_for = re.sub(r"^(?:me\s+)?(?:(?:a|an|the|some)\s+)?(?:(?:cheapest|best|top|affordable|expensive|lowest\s+price|highest\s+rated|popular|most\s+relevant|official)\s+)?", "", explicit_search_for, flags=re.IGNORECASE).strip()
    elif is_media_task and not target:
        # Check for play <target>
        play_m = re.search(r"\bplay\s+([a-zA-Z0-9\s\-_]+?)(?:,\s*|\s+(?:after|when|and\s+then|then|and)\s+|$)", clean_task, re.I)
        if play_m:
            cand_play = play_m.group(1).strip()
            if cand_play.lower() not in GENERIC_TARGETS:
                explicit_search_for = cand_play
                target = cand_play

    if explicit_search_for and not target:
        target = explicit_search_for

    # Determine intent and TaskType
    is_form_task = bool(re.search(r"\b(?:fill(?:\s+out)?\s+(?:the\s+)?(?:\w+\s+)?form|enter\s+into\s+(?:the\s+)?(?:\w+\s+)?(?:form|input)|submit\s+(?:the\s+)?(?:\w+\s+)?form|type\s+.+and\s+check\b)\b", lower))
    form_fields: dict[str, Any] = {}
    if is_form_task:
        field_matches = re.findall(r"\b([a-zA-Z0-9_-]+)\s+(?:as|to|=|is|with|:)\s+([^\s,;]+)", clean_task)
        for fk, fv in field_matches:
            if fk.lower() not in ("form", "and", "the", "a", "into"):
                form_fields[fk] = fv
        if not form_fields:
            pairs = re.findall(r"\b([a-zA-Z0-9_-]+)\s*[:=]\s*([^\s,;]+)", clean_task)
            for fk, fv in pairs:
                form_fields[fk] = fv

    is_comparison_task = bool(re.search(r"\b(?:compare|comparison|compare\s+(?:the\s+)?first\s+\d+|versus|vs)\b", lower))
    comparison_fields: list[str] = []
    comparison_count = 2
    if is_comparison_task:
        count_m = re.search(r"\b(?:first|top)\s+(\d+)\b", lower)
        if count_m:
            comparison_count = int(count_m.group(1))
        if "price" in lower:
            comparison_fields.append("price")
        if "rating" in lower or "score" in lower:
            comparison_fields.append("rating")
        if "title" in lower or "name" in lower:
            comparison_fields.append("title")
        if not comparison_fields:
            comparison_fields = ["title", "price", "rating"]

    is_download_task = bool(re.search(r"\b(?:download\s+(?:the\s+)?[\w\s]{0,35}?(?:file|pdf|report|document|csv|image|video|it)|save\s+(?:as\s+)?[\w\s]{0,35}?(?:file|pdf))\b", lower))
    is_upload_task = bool(re.search(r"\b(?:upload\s+(?:the\s+)?[\w\s]{0,35}?(?:file|document|image|attachment|receipt|photo|pdf)|attach\s+(?:file|document))\b", lower))
    is_table_task = bool(re.search(r"\b(?:extract\s+(?:the\s+)?table|table\s+data|data\s+from\s+(?:the\s+)?table)\b", lower))
    is_filter_task = bool(re.search(r"\b(?:filter\s+by|sort\s+by|apply\s+filter)\b", lower))

    target_date = ""
    date_m = re.search(r"\b(?:date(?:\s+to)?\s+)?(\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b", clean_task, re.I)
    if date_m:
        target_date = date_m.group(1)

    if is_form_task:
        intent = "form_filling"
        task_type = TaskType.FORM_FILLING
    elif is_comparison_task:
        intent = "comparison"
        task_type = TaskType.COMPARISON
    elif is_download_task:
        intent = "download"
        task_type = TaskType.DOWNLOAD
    elif is_upload_task:
        intent = "upload"
        task_type = TaskType.UPLOAD
    elif is_table_task:
        intent = "table_understanding"
        task_type = TaskType.INFORMATION_RETRIEVAL
    elif is_filter_task:
        intent = "filtering"
        task_type = TaskType.FILTERING
    elif is_ranked:
        intent = "ranked_search"
        task_type = TaskType.SEARCH
        target_type = "product"
        target = target or "product"
    elif is_product:
        intent = "product_search"
        task_type = TaskType.SEARCH
        target_type = "product"
        target = target or "product"
    elif is_media_task:
        intent = "media_interaction"
        task_type = TaskType.MEDIA_INTERACTION
        target_type = "video"
    elif requested_info:
        intent = "information_extraction"
        task_type = TaskType.INFORMATION_RETRIEVAL
    elif navigation_req or target:
        intent = "navigation"
        task_type = TaskType.NAVIGATION
    else:
        intent = "search"
        task_type = TaskType.SEARCH

    # 5. SEARCH QUERY SEPARATION (CRITICAL FIX)
    search_query = ""
    if is_product or is_ranked:
        prod_cat_match = re.search(
            r"\b(?:find|search\s+(?:(?:for|on|in|using|with|via)\s+[a-z0-9\.\-_]+\s+)*(?:for\s+)?|buy|look\s*up)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?(?:cheapest|best|top|affordable|expensive|lowest\s+price|highest\s+rated|popular|most\s+relevant|official)?\s*([a-z0-9\s\-_]+?)(?:\s+under|\s+below|\s+above|\s+with|\s+priced|\s+having|\s+rated|[,\.;]|$)",
            clean_task,
            re.IGNORECASE,
        )
        if prod_cat_match:
            cand_cat = prod_cat_match.group(1).strip()
            cand_cat = re.sub(r"^(?:the|a|an)\s+", "", cand_cat, flags=re.IGNORECASE).strip()
            if cand_cat and cand_cat.lower() not in GENERIC_TARGETS:
                search_query = cand_cat
        if not search_query and explicit_search_for:
            search_query = explicit_search_for
        if not search_query:
            search_query = target or clean_task
    elif explicit_search_for:
        search_query = explicit_search_for
    elif intent in ("information_extraction", "table_understanding"):
        if target:
            search_query = target
        else:
            search_query = clean_task
    elif target:
        search_query = target
    else:
        search_query = clean_task

    # Clean query
    search_query = re.sub(r"^(?:the|a|an)\s+", "", search_query, flags=re.IGNORECASE).strip()
    clean_q = re.sub(r"\s+(?:article|page|website|site)$", "", search_query, flags=re.IGNORECASE).strip()
    if clean_q:
        search_query = clean_q
    # Remove leading quantity words or digits (e.g., 'three', '5')
    quantity_pattern = r"^(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    search_query = re.sub(quantity_pattern, "", search_query, flags=re.IGNORECASE).strip()

    # Completion conditions
    completion_conditions = []
    if navigation_req:
        completion_conditions.append(f"Target reached: {target}")
    for pr in procedural_requirements:
        completion_conditions.append(f"Procedure satisfied: {pr}")
    if requested_info:
        completion_conditions.append(f"Information extracted: {', '.join(requested_info)}")
    if is_product or is_ranked:
        completion_conditions.append("Product matching constraints found or honest NO_MATCH reported")
    if is_form_task:
        completion_conditions.append("Form inputs completed and submitted")
    if is_comparison_task:
        completion_conditions.append("Structured comparison completed")
    if is_download_task:
        completion_conditions.append("File downloaded successfully")

    # Normalize price synonyms to canonical 'price'
    price_synonyms = {"prize", "cost", "amount", "product price", "current price"}
    normalized_info = []
    for info in requested_info:
        if info.lower() in price_synonyms:
            normalized_info.append("price")
        else:
            normalized_info.append(info)
    # Deduplicate while preserving order
    seen = set()
    requested_info_canonical = []
    for info in normalized_info:
        if info not in seen:
            seen.add(info)
            requested_info_canonical.append(info)
    return TaskPlan(
        raw_task=clean_task,
        destination=destination,
        destination_url=destination_url,
        target=target,
        target_type=target_type,
        search_query=search_query,
        intent=intent,
        task_type=task_type,
        requested_information=requested_info_canonical,
        navigation_requirement=navigation_req,
        procedural_requirements=procedural_requirements,
        completion_conditions=completion_conditions,
        ranking_field=ranking_field,
        ranking_order=ranking_order,
        form_fields=form_fields,
        comparison_fields=comparison_fields,
        comparison_count=comparison_count,
        target_date=target_date,
        table_query=clean_task if is_table_task else "",
        quantity=quantity,
        constraints=constraints,
        output_fields=output_fields
    )


def _parse_media_procedural_requirements(clean_task: str, destination: str = "") -> list[str]:
    """Parse ordered procedures for media playback and temporal sequences."""
    temporal_match = re.search(
        r"(?:(?:^|\s*;\s*|\s*\.\s*|\s*,\s*|\s+)\b(?:after\s+(?:the\s+)?(?:video|audio|song|track|it)\s+(?:ends|finishes|completes)|when\s+(?:the\s+)?(?:video|audio|song|track|it)\s+(?:ends|finishes))\b\s*,?\s*(?:then\s+)?)",
        clean_task,
        re.IGNORECASE
    )

    if temporal_match:
        stage1_text = clean_task[:temporal_match.start()].strip()
        stage2_text = clean_task[temporal_match.end():].strip()

        procs = _extract_single_stage_procs(stage1_text, destination)
        procs.append("wait for video completion")
        procs.extend(_extract_single_stage_procs(stage2_text, destination))
        return procs
    else:
        return _extract_single_stage_procs(clean_task, destination)


def _extract_single_stage_procs(text: str, destination: str = "") -> list[str]:
    stage_procs = []
    text_clean = text.strip().rstrip(".;,")
    lower = text_clean.lower()

    # Check if this stage specifies a destination or platform
    stage_dest = destination
    for plat in KNOWN_PLATFORMS.keys():
        if re.search(rf"\b(?:go\s+to|open|visit|navigate\s+to|search\s+on)\s+{plat}\b", text_clean, re.I):
            stage_dest = plat
            break

    if stage_dest and re.search(rf"\b(?:go\s+to|visit|navigate\s+to)\s+{stage_dest}\b", text_clean, re.I):
        stage_procs.append(f"open/search {stage_dest.title()}")

    # Search clause: "search for X"
    search_m = re.search(r"\bsearch\s+(?:for\s+)(.+?)(?:,\s*|\s+(?:and\s+then|then|and)\s+|$)", text_clean, re.I)
    if search_m:
        query_candidate = search_m.group(1).strip()
        query_candidate = re.sub(r"\s+on\s+[a-z0-9\.\-_]+$", "", query_candidate, flags=re.I).strip()
        stage_procs.append(f"search for {query_candidate}")
    elif re.search(r"\bplay\s+(?!it\b|video\b|song\b|audio\b|track\b|media\b)(.+?)(?:,\s*|\s+(?:and\s+then|then|and)\s+|$|\.)", text_clean, re.I):
        # E.g. "play <media title>" or "Go to YouTube and play <media title>"
        play_m = re.search(r"\bplay\s+(?!it\b|video\b|song\b|audio\b|track\b|media\b)(.+?)(?:,\s*|\s+(?:and\s+then|then|and)\s+|$|\.)", text_clean, re.I)
        play_target = play_m.group(1).strip()
        stage_procs.append(f"search for {play_target}")
        stage_procs.append(f"open {play_target}")
        stage_procs.append("play video")
        stage_procs.append("verify playback")
        return stage_procs

    # Open candidate clause: "open the first relevant video"
    open_m = re.search(r"\b(?:open|visit|navigate\s+to|select)\s+(.+?)(?:,\s*|\s+(?:and\s+then|then|and)\s+|$)", text_clean, re.I)
    if open_m:
        open_candidate = open_m.group(1).strip()
        open_lower = open_candidate.lower()
        if open_lower not in KNOWN_PLATFORMS and not any(open_candidate in p for p in stage_procs):
            stage_procs.append(f"open {open_candidate}")

    # Play clause
    if re.search(r"\b(?:play\s+it|play\s+video|play\s+song|start\s+playback|play)\b", lower):
        if "play video" not in stage_procs:
            stage_procs.append("play video")
        if "verify playback" not in stage_procs:
            stage_procs.append("verify playback")

    return stage_procs
