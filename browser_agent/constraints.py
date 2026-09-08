"""
Constraint extraction, candidate evaluation, and verification engine.
Supports numeric constraints (price, rating), feature requirements (ANC, waterproof, etc.),
and bounded candidate exploration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskConstraints:
    """Structured constraints parsed from user natural-language task."""
    raw_task: str = ""
    category: str = ""
    max_price: float | None = None
    min_price: float | None = None
    min_rating: float | None = None
    exact_rating: float | None = None
    required_features: list[str] = field(default_factory=list)
    logical_operator: str = "AND"
    has_no_match_instruction: bool = False

    def has_constraints(self) -> bool:
        return bool(
            self.max_price is not None
            or self.min_price is not None
            or self.min_rating is not None
            or self.exact_rating is not None
            or self.required_features
            or self.has_no_match_instruction
        )

    def summary(self) -> str:
        parts = []
        if self.category:
            parts.append(f"category='{self.category}'")
        if self.max_price is not None:
            parts.append(f"price < {self.max_price:g}")
        if self.min_price is not None:
            parts.append(f"price > {self.min_price:g}")
        if self.exact_rating is not None:
            parts.append(f"rating == {self.exact_rating:g}")
        elif self.min_rating is not None:
            parts.append(f"rating >= {self.min_rating:.1f}")
        if self.required_features:
            parts.append(f"features={self.required_features}")
        return ", ".join(parts) if parts else "none"


def parse_numeric_price(price_str: Any) -> float | None:
    """Extract numeric float from string like '₹593', 'Rs. 1,299.50', '$29.99', 499."""
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)
    s = str(price_str).replace(",", "").strip()
    match = re.search(r"[\d]+(?:\.\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def parse_numeric_rating(rating_str: Any) -> float | None:
    """Extract numeric float rating from string like '4.1', '5.0', '4.5 out of 5', or '6.0'."""
    if rating_str is None:
        return None
    if isinstance(rating_str, (int, float)):
        val = float(rating_str)
        return val if 0.0 <= val <= 10.0 else None
    s = str(rating_str).strip()
    match = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\b", s)
    if match:
        try:
            val = float(match.group(1))
            return val if 0.0 <= val <= 10.0 else None
        except ValueError:
            return None
    return None


def check_feature_present(feature_name: str, text_corpus: str) -> tuple[bool, str]:
    """
    Check if a required feature is supported in the product text corpus.
    Strictly distinguishes positive mentions from negative mentions and non-matching acronyms.
    """
    corpus_lower = text_corpus.lower()
    feat_lower = feature_name.lower().strip()

    if feat_lower in ("active noise cancellation", "anc"):
        # 1. Negative mentions strictly fail
        neg_patterns = [
            r"\b(?:no\s+anc|without\s+anc|non-anc|no\s+active\s+noise\s+cancellation)\b",
            r"\bactive\s+noise\s+cancellation\s*:\s*(?:no|none|false|absent|not\s+available)\b",
            r"\banc\s*:\s*(?:no|none|false|absent|not\s+available)\b",
        ]
        for np in neg_patterns:
            if re.search(np, corpus_lower):
                return False, "Product explicitly specifies Active Noise Cancellation (ANC) is absent or not supported"

        # 2. Positive true ANC mentions
        pos_patterns = [
            r"\bactive\s+noise\s+cancell(?:ation|ing)\b",
            r"\bhybrid\s+anc\b",
            r"\banc\s*(?:enabled|mode|support|technology|up\s+to|\(?anc\)?)",
            r"\btrue\s+anc\b",
            r"\bwith\s+anc\b",
            r"\bfeatures?\s*(?:hybrid\s+)?active\s+noise\s+cancellation\b",
            r"\bactive\s+noise\s+cancellation\s*:\s*(?:yes|true|present|available)\b",
        ]
        for pp in pos_patterns:
            if re.search(pp, corpus_lower):
                return True, "Active Noise Cancellation explicitly present in product text"

        # 3. ENC vs ANC distinction
        if "environmental noise cancellation" in corpus_lower or re.search(r"\benc\b", corpus_lower):
            return False, "Candidate features Environmental Noise Cancellation (ENC) only, which does not satisfy Active Noise Cancellation (ANC)"

        if "noise reduction" in corpus_lower or "noise cancellation" in corpus_lower or "passive noise" in corpus_lower:
            return False, "Generic noise cancellation/reduction mentioned, but explicit Active Noise Cancellation (ANC) was not established"

        return False, "No evidence of Active Noise Cancellation (ANC) found in product details"

    if feat_lower in corpus_lower:
        return True, f"Feature '{feature_name}' confirmed present in product details"

    return False, f"Feature '{feature_name}' not found in product details (missing evidence)"


def extract_task_constraints(task: str) -> TaskConstraints:
    """
    Parse natural language task into formal TaskConstraints.
    Associates numeric expressions with their semantic constraint (category, price, rating, features).
    """
    task_clean = task.strip()
    lower = task_clean.lower()
    constraints = TaskConstraints(raw_task=task_clean)

    # 1. Check for no-match / honest reporting instruction
    if re.search(r"\b(?:if\s+no\s+|report\s+that\s+no\s+|report\s+honestly|no\s+matching|not\s+found|do\s+not\s+invent|honest|do\s+not\s+relax)\b", lower):
        constraints.has_no_match_instruction = True

    # 2. Extract Category / Search intent
    cat_match = re.search(
        r"\b(?:find|search\s+(?:for)?|look\s*up)\s+(?:a\s+|an\s+|the\s+)?([a-z0-9\s]+?)\s+(?:under|below|above|with|having|priced|at\s+least|less\s+than|for|that|if)\b",
        lower,
    )
    if cat_match:
        cat_candidate = cat_match.group(1).strip()
        if cat_candidate and cat_candidate not in ("me", "suitable product", "product", "item"):
            constraints.category = cat_candidate

    # 3. Extract Rating constraint FIRST to claim rating-associated numbers and operator phrases
    rating_span: tuple[int, int] | None = None

    # Pattern 1: Exact rating ("exact 5.0 rating", "rating exactly 5.0", "exactly 5.0 star")
    m_exact = re.search(
        r"\b(?:exact(?:ly)?\s+([0-9]+(?:\.[0-9]+)?)\s*(?:star|rating|\★)|rating\s+(?:of\s+)?exact(?:ly)?\s+([0-9]+(?:\.[0-9]+)?)|exact(?:ly)?\s+rating\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?))\b",
        lower,
    )
    if m_exact:
        val_str = m_exact.group(1) or m_exact.group(2) or m_exact.group(3)
        val = parse_numeric_rating(val_str)
        if val is not None:
            constraints.exact_rating = val
            constraints.min_rating = val
            rating_span = (m_exact.start(), m_exact.end())

    # Pattern 2: "rating of at least 4.0", "rating at least 4.0", "rating >= 4.0", "rated at least 4.0", "rated above 4.0"
    if constraints.exact_rating is None and constraints.min_rating is None:
        m_at_least = re.search(
            r"\b(?:rating\s+(?:of\s+)?(?:at\s+least|above|over|>=?)|rating\s*>=\s*|rated\s+(?:at\s+least|above|over))\s*([0-9]+(?:\.[0-9]+)?)\b",
            lower,
        )
        if m_at_least:
            val = parse_numeric_rating(m_at_least.group(1))
            if val is not None:
                constraints.min_rating = val
                constraints.exact_rating = None
                rating_span = (m_at_least.start(), m_at_least.end())

    # Pattern 3: "4.0 rating or higher", "4.0 star or higher", "rating of 4.5 or higher", "4.0+ star rating"
    if constraints.exact_rating is None and constraints.min_rating is None:
        m_or_higher = re.search(
            r"\b(?:rating\s+(?:of\s+)?)?([0-9]+(?:\.[0-9]+)?)\s*(?:star|rating|\★)?\s*(?:or\s+(?:higher|above|more)|\+)\b",
            lower,
        )
        if m_or_higher:
            val = parse_numeric_rating(m_or_higher.group(1))
            if val is not None:
                constraints.min_rating = val
                constraints.exact_rating = None
                rating_span = (m_or_higher.start(), m_or_higher.end())

    # Pattern 4: "above 4.0 star", "greater than 4.0 rating", "at least 4.0 star", "minimum 4.0 rating"
    if constraints.exact_rating is None and constraints.min_rating is None:
        m_above_star = re.search(
            r"\b(?:above|greater\s+than|over|at\s+least|minimum)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:star|rating|\★)\b",
            lower,
        )
        if m_above_star:
            val = parse_numeric_rating(m_above_star.group(1))
            if val is not None:
                constraints.min_rating = val
                constraints.exact_rating = None
                rating_span = (m_above_star.start(), m_above_star.end())

    # Pattern 5: "with a 5.0 rating", "5.0 rating", "4.5 star rating", "rated 4.8"
    if constraints.exact_rating is None and constraints.min_rating is None:
        m_std = re.search(
            r"\b(?:has\s+a\s+|with\s+a\s+|rated\s+|rating\s+(?:of|:)\s*)?([0-9]+(?:\.[0-9]+)?)\s*(?:star|rating|\★)\b",
            lower,
        )
        if m_std:
            val = parse_numeric_rating(m_std.group(1))
            if val is not None:
                if val == 5.0:
                    constraints.exact_rating = 5.0
                    constraints.min_rating = 5.0
                else:
                    constraints.min_rating = val
                    constraints.exact_rating = None
                rating_span = (m_std.start(), m_std.end())

    # Pattern 6: "rating of 4.0", "rating: 4.0", "rating 4.0"
    if constraints.exact_rating is None and constraints.min_rating is None:
        m_of = re.search(
            r"\brating\s*(?:of|:|is|at)?\s*([0-9]+(?:\.[0-9]+)?)\b",
            lower,
        )
        if m_of:
            val = parse_numeric_rating(m_of.group(1))
            if val is not None:
                if val == 5.0:
                    constraints.exact_rating = 5.0
                    constraints.min_rating = 5.0
                else:
                    constraints.min_rating = val
                    constraints.exact_rating = None
                rating_span = (m_of.start(), m_of.end())

    # Helper function to check if a match range overlaps with the rating span
    def overlaps_rating(start: int, end: int) -> bool:
        if not rating_span:
            return False
        return not (end <= rating_span[0] or start >= rating_span[1])

    # 4. Extract Max Price
    # Currency symbols: ₹, $, Rs, INR, €, £, unicode \u20b9, mojibake \u00e2\u201a\u00b9
    curr_sym = r"(?:₹|\$|Rs\.?|INR|€|£|\u20b9|\u00e2\u201a\u00b9)"

    # 4a. Explicit currency symbol with max bounds (e.g. 'under ₹2000', 'below $50', 'under 2000 INR')
    max_curr_match = re.search(
        rf"\b(?:under|below|less\s+than|cheaper\s+than|max(?:imum)?)\s*(?:{curr_sym}\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*{curr_sym})",
        lower,
    )
    if max_curr_match:
        val_str = max_curr_match.group(1) or max_curr_match.group(2)
        val = parse_numeric_price(val_str)
        if val is not None and not overlaps_rating(max_curr_match.start(), max_curr_match.end()):
            constraints.max_price = val

    # 4b. Explicit price word with synonyms (e.g. 'price under 2000', 'prize below 500', 'amount under 1000', 'product price under 1500')
    if constraints.max_price is None:
        max_word_match = re.search(
            r"\b(?:price|prize|cost|amount|product\s+price|current\s+price)\s*(?:is\s+|of\s+|at\s+)?(?:under|below|less\s+than|\<=?)\s*(?:[^\d\s]+\s*)?([\d,]+(?:\.\d+)?)",
            lower,
        )
        if max_word_match:
            val = parse_numeric_price(max_word_match.group(1))
            if val is not None and not overlaps_rating(max_word_match.start(), max_word_match.end()):
                constraints.max_price = val

    # 4c. Fallback for bare 'under <num>' when NOT overlapping rating
    if constraints.max_price is None:
        max_bare_match = re.search(
            r"\b(?:under|below|less\s+than|cheaper\s+than)\s+([\d,]+(?:\.\d+)?)\b",
            lower,
        )
        if max_bare_match and not overlaps_rating(max_bare_match.start(), max_bare_match.end()):
            val = parse_numeric_price(max_bare_match.group(1))
            if val is not None:
                constraints.max_price = val

    # 5. Extract Min Price
    # Requires explicit currency symbol or price keyword to avoid grabbing rating numbers
    min_curr_match = re.search(
        rf"\b(?:above|more\s+than|at\s+least|min(?:imum)?|greater\s+than|>=?)\s*(?:{curr_sym}\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*{curr_sym})",
        lower,
    )
    if min_curr_match:
        val_str = min_curr_match.group(1) or min_curr_match.group(2)
        val = parse_numeric_price(val_str)
        if val is not None and not overlaps_rating(min_curr_match.start(), min_curr_match.end()):
            constraints.min_price = val

    if constraints.min_price is None:
        min_word_match = re.search(
            r"\b(?:price|prize|cost|amount|product\s+price|current\s+price)\s*(?:is\s+|of\s+|at\s+)?(?:above|more\s+than|at\s+least|min(?:imum)?|greater\s+than|>=?)\s*(?:[^\d\s]+\s*)?([\d,]+(?:\.\d+)?)",
            lower,
        )
        if min_word_match:
            val = parse_numeric_price(min_word_match.group(1))
            if val is not None and not overlaps_rating(min_word_match.start(), min_word_match.end()):
                constraints.min_price = val

    # 6. Extract Feature constraints
    if "active noise cancellation" in lower or "active noise cancelling" in lower or re.search(r"\banc\b", lower):
        constraints.required_features.append("active noise cancellation")
    if "waterproof" in lower:
        constraints.required_features.append("waterproof")
    if "rain cover" in lower:
        constraints.required_features.append("rain cover")

    return constraints


def evaluate_candidate(
    candidate: dict[str, Any],
    page_text: str,
    constraints: TaskConstraints,
) -> dict[str, Any]:
    """
    Evaluate candidate product metadata and grounded page text against TaskConstraints.
    Returns structured evaluation results:
        {
            "satisfied": bool,
            "status": "ACCEPTED" | "REJECTED",
            "checks": dict[str, dict[str, Any]],
            "rejection_reasons": list[str]
        }
    Missing evidence is strictly treated as unsatisfied.
    """
    if not constraints.has_constraints():
        return {
            "satisfied": True,
            "status": "ACCEPTED",
            "checks": {},
            "rejection_reasons": [],
        }

    checks: dict[str, dict[str, Any]] = {}
    rejection_reasons: list[str] = []
    satisfied = True

    # Combine text corpus for feature search
    text_corpus = (
        f"{candidate.get('product_name', '')} "
        f"{candidate.get('title', '')} "
        f"{page_text} "
        f"{str(candidate.get('specifications', ''))} "
        f"{str(candidate.get('highlights', ''))}"
    )

    # 1. Category check
    if constraints.category:
        cand_cat = str(candidate.get("category", "")).lower()
        cand_name = str(candidate.get("product_name") or candidate.get("title") or "").lower()

        # If candidate explicitly provides a category, it must match
        if cand_cat:
            cat_words = [w for w in constraints.category.lower().split() if len(w) > 2]
            cat_match = any(w in cand_cat for w in cat_words)
            checks["category"] = {
                "required": constraints.category,
                "actual": candidate.get("category"),
                "passed": cat_match,
            }
            if not cat_match:
                satisfied = False
                rejection_reasons.append(f"Candidate category '{cand_cat}' does not match required '{constraints.category}'")
        else:
            # Check for cross-category contradiction (e.g. laptop bag when searching headphones)
            contradictions = {
                "headphones": {"bag", "backpack", "shoe", "shoes", "shirt", "pant", "phone", "watch", "laptop"},
                "wireless headphones": {"bag", "backpack", "shoe", "shoes", "shirt", "pant", "phone", "watch", "laptop"},
                "laptop bag": {"headphone", "headphones", "earbud", "earbuds", "shoe", "shoes", "phone", "watch"},
                "shoes": {"headphone", "headphones", "bag", "backpack", "phone", "laptop"},
            }
            cand_words = set(re.findall(r"\b[a-z]{3,}\b", cand_name))
            contradicting_words: set[str] = set()
            for cat_key, bad_words in contradictions.items():
                if cat_key in constraints.category.lower():
                    contradicting_words = bad_words
                    break

            is_contradiction = False
            if "headphone" in constraints.category.lower():
                has_audio_term = any(syn in cand_name for syn in ["headphone", "earphone", "earbud", "headset", "tws", "audio", "anc", "sound", "beat", "bass", "airpod", "pro"])
                if cand_words.intersection(contradicting_words) and not has_audio_term:
                    is_contradiction = True
            elif "bag" in constraints.category.lower():
                has_bag_term = any(syn in cand_name for syn in ["bag", "backpack", "sleeve", "case", "pack", "briefcase"])
                if cand_words.intersection(contradicting_words) and not has_bag_term:
                    is_contradiction = True

            if is_contradiction:
                satisfied = False
                checks["category"] = {
                    "required": constraints.category,
                    "actual": candidate.get("product_name") or candidate.get("title"),
                    "passed": False,
                }
                rejection_reasons.append(f"Candidate '{cand_name}' contradicts required category '{constraints.category}'")
            else:
                checks["category"] = {
                    "required": constraints.category,
                    "actual": candidate.get("product_name") or candidate.get("title"),
                    "passed": True,
                }

    # 2. Price check
    if constraints.max_price is not None or constraints.min_price is not None:
        raw_price = candidate.get("price")
        actual_price = parse_numeric_price(raw_price)

        price_passed = True
        price_reason = ""

        if actual_price is None:
            price_passed = False
            price_reason = "Price not found or missing from product page (missing evidence)"
        else:
            if constraints.max_price is not None and actual_price > constraints.max_price:
                price_passed = False
                price_reason = f"Actual price ₹{actual_price:g} exceeds required maximum ₹{constraints.max_price:g}"
            if constraints.min_price is not None and actual_price < constraints.min_price:
                price_passed = False
                price_reason = f"Actual price ₹{actual_price:g} is below required minimum ₹{constraints.min_price:g}"

        checks["price"] = {
            "required": f"< {constraints.max_price}" if constraints.max_price is not None else f"> {constraints.min_price}",
            "actual": actual_price,
            "raw": raw_price,
            "passed": price_passed,
            "reason": price_reason or "Price satisfies required constraint",
        }
        if not price_passed:
            satisfied = False
            rejection_reasons.append(price_reason)

    # 3. Rating check
    if constraints.exact_rating is not None or constraints.min_rating is not None:
        raw_rating = candidate.get("rating")
        actual_rating = parse_numeric_rating(raw_rating)

        rating_passed = True
        rating_reason = ""

        if actual_rating is None:
            rating_passed = False
            rating_reason = "Rating not found or missing from product page (missing evidence)"
        else:
            if constraints.exact_rating is not None:
                # Exact rating equality check
                if abs(actual_rating - constraints.exact_rating) > 0.05:
                    rating_passed = False
                    rating_reason = f"Actual rating {actual_rating} does not meet required {constraints.exact_rating}"
            elif constraints.min_rating is not None:
                if actual_rating < constraints.min_rating:
                    rating_passed = False
                    rating_reason = f"Actual rating {actual_rating} is below required minimum {constraints.min_rating}"

        checks["rating"] = {
            "required": f"== {constraints.exact_rating}" if constraints.exact_rating is not None else f">= {constraints.min_rating}",
            "actual": actual_rating,
            "raw": raw_rating,
            "passed": rating_passed,
            "reason": rating_reason or "Rating satisfies required constraint",
        }
        if not rating_passed:
            satisfied = False
            rejection_reasons.append(rating_reason)

    # 4. Required features check
    for feat in constraints.required_features:
        feat_passed, feat_msg = check_feature_present(feat, text_corpus)
        checks[feat] = {
            "required": True,
            "actual": feat_passed,
            "passed": feat_passed,
            "reason": feat_msg,
        }
        if not feat_passed:
            satisfied = False
            rejection_reasons.append(feat_msg)

    status = "ACCEPTED" if satisfied else "REJECTED"
    return {
        "satisfied": satisfied,
        "status": status,
        "checks": checks,
        "rejection_reasons": rejection_reasons,
    }


def pick_best_ranked_candidate(
    candidates: list[dict[str, Any]],
    constraints: TaskConstraints | None,
    rank_field: str = "rating",
    rank_order: str = "desc",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Filter candidates by constraints first, then rank by specified field and order.
    Returns (best_candidate, valid_candidates).
    """
    if constraints and constraints.has_constraints():
        valid_candidates = [
            c for c in candidates
            if evaluate_candidate(c.get("extracted_data") or {}, "", constraints).get("satisfied", False)
        ]
    else:
        valid_candidates = list(candidates)

    if not valid_candidates:
        return None, []

    def sort_val(c: dict[str, Any]) -> float:
        if rank_field == "rating":
            val = c.get("numeric_rating")
            if val is None:
                return -1.0 if rank_order == "desc" else float("inf")
            return float(val)
        elif rank_field == "price":
            val = c.get("numeric_price")
            if val is None:
                return -1.0 if rank_order == "desc" else float("inf")
            return float(val)
        return 0.0

    reverse_sort = (rank_order == "desc")
    sorted_candidates = sorted(valid_candidates, key=sort_val, reverse=reverse_sort)
    return sorted_candidates[0], valid_candidates
