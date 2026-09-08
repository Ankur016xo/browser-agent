"""
Exploration & Goal-First Navigation Engine.
Implements goal-aware page inspection, target link selection, and directional
scrolling to explore content without blind loops or re-searching.
"""
from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page

from browser_agent.logging import get_logger
from browser_agent.planner import TaskPlan
from browser_agent.state import AgentMemory, ElementInfo

logger = get_logger(__name__)


def is_page_relevant_to_target(page: Page, task_plan: TaskPlan) -> bool:
    """Check if current page is relevant to the target entity or search query."""
    if not task_plan or not task_plan.target:
        return True

    curr_url = page.url.lower()
    curr_title = page.title().lower()

    target = task_plan.target.lower().strip()
    target_words = [w for w in re.findall(r"\w+", target) if w not in {"the", "a", "an", "article", "page", "website", "site", "doc", "docs", "documentation", "official"}]
    if not target_words:
        target_words = [w for w in re.findall(r"\w+", target) if w not in {"the", "a", "an"}]

    # Check title, URL, or h1
    if any(tw in curr_title for tw in target_words) or any(tw in curr_url for tw in target_words):
        return True

    try:
        h1 = page.evaluate("() => document.querySelector('h1') ? document.querySelector('h1').innerText : ''").lower()
        if any(tw in h1 for tw in target_words):
            return True
    except Exception:
        pass

    return False


def find_matching_target_link(elements: list[ElementInfo], target: str, target_type: str = "page") -> ElementInfo | None:
    """
    Find an element link on the page that best matches the target entity.
    Prefers exact matches and avoids specialized sub-topic links when a primary entity is requested.
    """
    if not target:
        return None

    target_clean = target.lower().strip()
    target_words = [w for w in re.findall(r"\w+", target_clean) if w not in {"the", "a", "an", "article", "page", "website", "site", "doc", "docs", "documentation", "official"}]
    if not target_words:
        target_words = [w for w in re.findall(r"\w+", target_clean) if w not in {"the", "a", "an"}]

    subtopic_prefixes = {"languages of", "history of", "geography of", "economy of", "culture of", "politics of", "demographics of", "music of", "cinema of"}

    candidates: list[tuple[int, ElementInfo]] = []

    for elem in elements:
        if elem.tag != "a" and elem.role != "link":
            continue
        text = (elem.text or "").strip()
        text_lower = text.lower()
        href = (elem.attributes.get("href") or "").lower()

        if not text and not href:
            continue

        # Skip category / boilerplate / nav links
        if text_lower in {"help", "about", "contact", "terms", "privacy", "main page", "contents", "current events", "random article", "donate"}:
            continue

        words = [w for w in re.findall(r"\w+", text_lower)]

        # Check for exact primary match
        # E.g. target="India", text="India"
        if words == target_words:
            candidates.append((100, elem))
            continue

        # Target words in text
        if all(tw in words for tw in target_words):
            # Check if this link is a subtopic when target did not request it
            # e.g. text="Languages of India" when target="India"
            is_subtopic = any(sp in text_lower for sp in subtopic_prefixes) and not any(sp in target_clean for sp in subtopic_prefixes)
            if is_subtopic:
                # Lower priority: candidate is a sub-topic, not the primary article
                candidates.append((20, elem))
            elif len(words) == len(target_words) + 1:
                # E.g. "India portal" or "Republic of India"
                candidates.append((80, elem))
            else:
                candidates.append((50, elem))

    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        best_score, best_elem = candidates[0]
        if best_score >= 50:
            logger.info("Selected target link '%s' (score %d, ID %d)", best_elem.text[:40], best_score, best_elem.id)
            return best_elem

    return None


NAV_BOILERPLATE = {
    "home", "explore", "subscriptions", "library", "history", "trending", "shorts",
    "settings", "help", "feedback", "send feedback", "about", "press", "copyright",
    "contact us", "creators", "advertise", "developers", "terms", "privacy", "policy & safety",
    "sign in", "login", "menu", "search", "filters", "all", "videos", "news", "images",
    "maps", "shopping", "more", "clear", "cancel", "skip", "close", "next", "previous",
    "share", "save", "download", "clip", "thanks", "main page", "main_page", "contents",
    "current events", "random article", "donate", "portal:"
}


class CandidateAction(dict):
    """Action dictionary that also behaves like an ElementInfo candidate for convenience."""
    def __init__(self, elem: ElementInfo, score: float, title: str, action_dict: dict[str, Any]):
        super().__init__(action_dict)
        self.id = elem.id
        self.element = elem
        self.text = elem.text or title
        self.score = score
        self.title = title


def find_candidate_content_items(
    elements: list[ElementInfo],
    query: str = "",
    target: str = "",
    procedure: str = "",
    exclude_ids: set[str | int] | None = None,
    preferred_type: str | None = None,
    visited_hrefs: set[str] | None = None,
) -> list[tuple[ElementInfo, float, str]]:
    """
    Universally inspect and rank candidate content items (videos, articles, products, search results).
    Returns list of (element, score, title_text) sorted by score descending.
    """
    candidates: list[tuple[ElementInfo, float, str]] = []
    excludes = exclude_ids or set()
    v_hrefs = {h.lower() for h in (visited_hrefs or set())}

    combined_query = f"{query} {target}".strip().lower()
    words = [
        w for w in re.findall(r"\w+", combined_query)
        if w not in {"first", "relevant", "open", "the", "a", "an", "video", "result", "song", "article", "page", "website", "documentation"}
    ]
    if not words:
        words = [w for w in re.findall(r"\w+", combined_query) if len(w) > 2]

    subtopic_prefixes = {"languages of", "history of", "geography of", "economy of", "culture of", "politics of", "demographics of", "music of", "cinema of"}

    for idx, elem in enumerate(elements):
        if elem.id in excludes:
            continue
        if elem.tag != "a" and elem.role not in ("link", "button") and not elem.attributes.get("href"):
            continue

        text = (elem.text or "").strip()
        title = (elem.attributes.get("title") or "").strip()
        aria = (elem.attributes.get("aria-label") or "").strip()
        href = (elem.attributes.get("href") or "").strip().lower()

        full_text = f"{text} {title} {aria}".strip().lower()
        if not full_text and not href:
            continue

        if v_hrefs and (href in v_hrefs or any(vh in href or href in vh for vh in v_hrefs if len(vh) > 8)):
            continue

        if full_text in NAV_BOILERPLATE or any(full_text == b for b in NAV_BOILERPLATE):
            continue
        if any(b in href for b in ["/main_page", "wiki/main_page", "/feed/", "/channel/", "/playlist/"]):
            continue
        if href in {"/", "#", "javascript:void(0)", "javascript:;"} or href.startswith(("#", "javascript:")):
            continue

        score = 0.0
        clean_q = " ".join(words)
        if clean_q and clean_q in full_text:
            score += 100.0

        for w in words:
            if w in full_text:
                score += 25.0
            elif w in href:
                score += 15.0

        # Subtopic penalty
        if any(sp in full_text for sp in subtopic_prefixes) and not any(sp in combined_query for sp in subtopic_prefixes):
            score -= 30.0

        proc_lower = f"{procedure} {combined_query} {preferred_type or ''}".lower()
        if any(k in proc_lower for k in ["video", "youtube", "play"]) and any(vh in href for vh in ["/watch", "video", "v="]):
            score += 35.0
        elif any(k in proc_lower for k in ["article", "wikipedia", "wiki"]) and any(ah in href for ah in ["/wiki/", "/article/"]):
            score += 35.0
        elif any(k in proc_lower for k in ["product", "laptop", "flipkart", "amazon", "buy"]) and any(ph in href for ph in ["/p/", "/dp/", "/product/", "/item/"]):
            score += 35.0
        elif any(k in proc_lower for k in ["doc", "documentation"]) and any(dh in href for dh in ["docs", "documentation"]):
            score += 35.0

        # Position preference for top matching results only
        if score > 0:
            score += max(0.0, 10.0 - idx * 1.0)

        best_title = title or text or aria or href
        if score > 0:
            candidates.append((elem, score, best_title))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def select_best_candidate_link(
    elements: list[ElementInfo],
    query: str = "",
    target: str = "",
    procedure: str = "",
    exclude_ids: set[str | int] | None = None,
    preferred_type: str | None = None,
    unvisited_only: bool = False,
    visited_hrefs: set[str] | None = None,
) -> CandidateAction | None:
    """Select best candidate link and return an executable action dict."""
    candidates = find_candidate_content_items(
        elements,
        query=query,
        target=target,
        procedure=procedure,
        exclude_ids=exclude_ids,
        preferred_type=preferred_type,
        visited_hrefs=visited_hrefs if unvisited_only else None,
    )
    if not candidates:
        return None

    best_elem, best_score, best_title = candidates[0]
    action_dict = {
        "action": "click",
        "element_id": best_elem.id,
        "target": best_title[:60],
        "reasoning": f"Grounded candidate content selection: opening '{best_title[:50]}' (score: {best_score:.1f})",
        "confidence": 0.95,
    }
    return CandidateAction(best_elem, best_score, best_title, action_dict)



def extract_price(page: Page, body_text: str, target: str | None = None) -> Any:
    """Extract price from body_text, optionally using target for semantic extraction.
    Returns a float when possible, otherwise raw string, or None if not found.
    """
    # Semantic extraction if target provided
    if target:
        try:
            price_match = page.evaluate(
                """
                (target) => {
                    const norm = (s) => (s || '').toLowerCase();
                    const targetLow = norm(target);
                    const elems = Array.from(document.querySelectorAll('body *')).filter(el => el.innerText && norm(el.innerText).includes(targetLow));
                    for (const el of elems) {
                        const txt = el.innerText;
                        let m = txt.match(/[\\$\\u20ac\\u00a3\\u20b9]\\s?[0-9,.]+/);
                        if (m) return m[0];
                        m = txt.match(/(?:price|cost|amount)[\\s:\\-]*\\s*(?:[\\$\\u20ac\\u00a3\\u20b9]|USD|EUR|GBP)?\\s*([\\d,.]+)/i);
                        if (m) return m[1] ? m[1] : m[0];
                    }
                    return null;
                }
                """,
                target,
            )
        except Exception as e:
            logger.debug("Semantic price extraction failed: %s", e)
            price_match = None
        if price_match:
            raw_price = price_match
        else:
            raw_price = None
    else:
        raw_price = None

    if not raw_price:
        # Fallback regex extraction
        price_match = re.search(r"[\\$\\u20ac\\u00a3\\u20b9]\\s?[0-9,.]+", body_text)
        if not price_match:
            price_match = re.search(
                r"(?:price|cost|amount)[\\s:\\-]*\\s*(?:[\\$\\u20ac\\u00a3\\u20b9]|USD|EUR|GBP)?\\s*([\\d,.]+)",
                body_text,
                re.IGNORECASE,
            )
        if price_match:
            raw_price = price_match.group(1) if price_match.lastindex else price_match.group(0)
    if raw_price:
        numeric = re.sub(r"[\\$\\u20ac\\u00a3\\u20b9,]", "", raw_price)
        try:
            return float(numeric)
        except ValueError:
            return raw_price.strip()
    return None

def inspect_page_for_requested_info(page: Page, requested_info: list[str], target: str | None = None) -> dict[str, Any]:
    """Inspect page DOM / text for specific requested information items."""
    results: dict[str, Any] = {}
    if not requested_info:
        return results

    try:
        body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        body_text = ""

    if not body_text:
        return results

    results: dict[str, Any] = {}
    for info in requested_info:
        info_lower = info.lower()

        # Official language extraction
        if "official language" in info_lower or "language" in info_lower:
            lang_match = re.search(
                r"Official[\s\xa0]+languages?[\s\xa0:\t\n]+([^\n\r•\[]{2,60})",
                body_text,
                re.IGNORECASE,
            )
            if not lang_match:
                lang_match = re.search(
                    r"(?:National\s+languages?|Official\s+language)\s*[:\t\n]?\s*([^\n\r•\(\)]{2,60})",
                    body_text,
                    re.IGNORECASE,
                )
            if lang_match:
                extracted = lang_match.group(1).strip()
                extracted = re.sub(r"\[[^\]]*\]", "", extracted).strip()
                extracted = re.sub(r"([a-z])([A-Z])", r"\1, \2", extracted).strip()
                if extracted and extracted.lower() not in {"article", "edit", "talk", "view history", "tools"}:
                    results["official_language"] = extracted

        # Capital extraction
        if "capital" in info_lower:
            cap_match = re.search(
                r"Capital(?:\s+and\s+largest\s+city)?[\s\t\n:]+([A-Z][a-zA-Z \t\.\-]{2,40})",
                body_text,
            )
            if not cap_match:
                cap_match = re.search(
                    r"(?:Capital(?:\s+and\s+largest\s+city)?)\s*[:\t\n]?\s*([^\n\r•\(\)\t\[]{2,60})",
                    body_text,
                    re.IGNORECASE,
                )
            if cap_match:
                extracted = cap_match.group(1).strip()
                extracted = re.sub(r"\[[^\]]*\]", "", extracted).strip()
                if extracted and extracted.lower() not in {"and largest city", "city", "none", "n/a", "official"}:
                    results["capital"] = extracted

        # Population extraction
        if "population" in info_lower:
            pop_match = re.search(
                r"Population\b[^\n\r\d]{0,80}(?:\b\d{4}\s+(?:estimate|census)\b[^\n\r\d]{0,40})?(\d[\d,]+|\d+(?:\.\d+)?\s*(?:billion|million|trillion))",
                body_text,
                re.IGNORECASE,
            )
            if not pop_match:
                pop_match = re.search(
                    r"(?:^|[\n\r])\s*Population[\s\xa0\n\t•]+(?:[^\n\r]*[\n\r\t]+)?([0-9\.,\s]+(?:billion|million|trillion)?|\d[\d,]+)",
                    body_text,
                    re.IGNORECASE,
                )
            if not pop_match:
                pop_match = re.search(
                    r"Population\s*[:\t\n]?\s*([0-9\.,\s]+(?:billion|million|trillion)?|\d[\d,]+)",
                    body_text,
                    re.IGNORECASE,
                )
            if pop_match:
                extracted = pop_match.group(1).strip()
                extracted = re.sub(r"\[[^\]]*\]", "", extracted).strip()
                if extracted:
                    results["population"] = extracted

        # Price extraction
        if "price" in info_lower:
            # Attempt to find any currency symbol with numbers
            price_match = re.search(r"[\$\u20ac\u00a3\u20b9]\s?[0-9,.]+", body_text)
            if not price_match:
                # Fallback to keywords with optional currency
                price_match = re.search(
                    r"(?:price|cost|amount)[\s:\-]*\s*(?:[\$\u20ac\u00a3\u20b9]|USD|EUR|GBP)?\s*([\d,.]+)",
                    body_text,
                    re.IGNORECASE,
                )
            if price_match:
                # Use captured group if available, else whole match
                raw_price = price_match.group(1) if price_match.lastindex else price_match.group(0)
                # Strip symbols and commas
                numeric = re.sub(r"[\$\u20ac\u00a3\u20b9,]", "", raw_price)
                try:
                    results["price"] = float(numeric)
                except ValueError:
                    results["price"] = raw_price.strip()

        # Page heading
        if "heading" in info_lower:
            try:
                h1 = page.evaluate("() => document.querySelector('h1') ? document.querySelector('h1').innerText : ''").strip()
                if h1:
                    results["heading"] = h1
            except Exception:
                pass

        # Page title
        if "title" in info_lower:
            t = page.title().strip()
            if t:
                results["title"] = t

    return results


def inspect_procedural_element(
    page: Any,
    target_text: str,
    elements: list[ElementInfo] | None = None,
) -> dict[str, Any]:
    """
    Inspect the full page DOM to discover if a procedural link/button/element exists,
    its visibility, and its viewport/scroll distance.
    Works generically across any website without site-specific selectors.
    """
    clean_target = str(target_text or "").strip().lower()
    if not clean_target:
        return {"exists": False, "inViewport": False}

    # 1. If live Playwright page supporting evaluate
    if hasattr(page, "evaluate") and callable(getattr(page, "evaluate")):
        js_inspector = """
        (targetText) => {
            if (!targetText) return { exists: false, inViewport: false };
            const normalize = (s) => (s || '').toLowerCase().replace(/[\\s\\u00a0]+/g, ' ').trim();
            const query = normalize(targetText);
            if (!query) return { exists: false, inViewport: false };

            const selectors = [
                'a[href]', 'button', '[role="button"]', '[role="link"]',
                'input[type="button"]', 'input[type="submit"]', 'summary'
            ];
            const candidateElements = Array.from(document.querySelectorAll(selectors.join(',')));

            let best = null;
            let bestScore = 0;

            for (const el of candidateElements) {
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                const text = normalize(el.innerText || el.textContent);
                const title = normalize(el.getAttribute('title'));
                const aria = normalize(el.getAttribute('aria-label'));

                if (text === query || title === query || aria === query) {
                    best = el;
                    bestScore = 100;
                    break;
                }

                if (bestScore < 85 && query.length >= 3) {
                    if ((text && (text.startsWith(query) || text.endsWith(query))) ||
                        (title && (title.startsWith(query) || title.endsWith(query)))) {
                        best = el;
                        bestScore = 85;
                    }
                }

                if (bestScore < 80 && query.length >= 4) {
                    if ((text && text.includes(query)) || (title && title.includes(query)) || (aria && aria.includes(query))) {
                        best = el;
                        bestScore = 80;
                    }
                }

                if (bestScore < 70 && query.length >= 8) {
                    if ((text && text.length >= query.length * 0.85 && query.includes(text)) ||
                        (title && title.length >= query.length * 0.85 && query.includes(title))) {
                        best = el;
                        bestScore = 70;
                    }
                }
            }

            if (!best) {
                const fallback = Array.from(document.querySelectorAll('[onclick], [tabindex], h1, h2, h3, h4, p, span, li'));
                for (const el of fallback) {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                    const text = normalize(el.innerText || el.textContent);
                    if (text === query) {
                        best = el;
                        bestScore = 50;
                        break;
                    }
                }
            }

            if (!best) {
                return { exists: false, inViewport: false };
            }

            const rect = best.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {
                return { exists: false, inViewport: false };
            }

            const vh = window.innerHeight || document.documentElement.clientHeight;
            const vw = window.innerWidth || document.documentElement.clientWidth;

            const inViewport = rect.top >= 0 && rect.bottom <= vh && rect.left >= 0 && rect.right <= vw;

            let scrollDirection = 'none';
            let scrollDistance = 0;
            if (rect.top < 0) {
                scrollDirection = 'up';
                scrollDistance = Math.min(1500, Math.max(100, Math.round(Math.abs(rect.top) + 50)));
            } else if (rect.bottom > vh) {
                scrollDirection = 'down';
                scrollDistance = Math.min(1500, Math.max(100, Math.round(rect.top - vh / 3)));
            }

            return {
                exists: true,
                inViewport: inViewport,
                scrollDirection: scrollDirection,
                scrollDistance: scrollDistance,
                rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height, x: rect.x, y: rect.y },
                text: (best.innerText || best.textContent || '').trim().slice(0, 80),
                tagName: best.tagName.toLowerCase(),
            };
        }
        """
        try:
            res = page.evaluate(js_inspector, clean_target)
            if isinstance(res, dict) and "exists" in res:
                return res
        except Exception as exc:
            logger.debug("JS inspect_procedural_element evaluation failed: %s", exc)

    # 2. Fallback: inspect provided elements list (e.g. in unit tests with mock_page)
    if elements:
        for elem in elements:
            e_text = (elem.text or "").strip().lower()
            e_title = (elem.attributes.get("title") or "").strip().lower()
            e_aria = (elem.attributes.get("aria-label") or "").strip().lower()
            if clean_target in (e_text, e_title, e_aria) or (len(clean_target) > 4 and clean_target in e_text):
                return {
                    "exists": True,
                    "inViewport": True,
                    "scrollDirection": "none",
                    "scrollDistance": 0,
                    "text": elem.text,
                    "tagName": elem.tag,
                }

    return {"exists": False, "inViewport": False}


def check_authentication_barrier(page: Any) -> tuple[bool, str]:
    """Check if page has login form, password input, CAPTCHA, or MFA barrier."""
    if not hasattr(page, "evaluate"):
        return False, ""
    try:
        res = page.evaluate("""() => {
            const hasPwd = !!document.querySelector('input[type="password"]');
            const hasCaptcha = !!document.querySelector('.g-recaptcha, .h-captcha, iframe[src*="recaptcha"], iframe[src*="captcha"], #turnstile-wrapper, [class*="captcha" i]');
            const hasMfa = !!document.querySelector('input[name*="otp" i], input[name*="mfa" i], input[placeholder*="verification code" i]');
            if (hasCaptcha) return { barrier: true, type: "CAPTCHA challenge" };
            if (hasMfa) return { barrier: true, type: "Multi-factor authentication (MFA)" };
            if (hasPwd) return { barrier: true, type: "Password / login authentication" };
            return { barrier: false, type: "" };
        }""")
        if hasattr(res, "_mock_name") or not isinstance(res, dict):
            return False, ""
        if res.get("barrier") is True:
            return True, str(res.get("type", "Authentication barrier"))
        return False, ""
    except Exception:
        return False, ""


def check_blocking_modal(page: Any, elements: list[ElementInfo] | None = None) -> bool:
    """Check if page has a blocking modal dialog, cookie consent banner, or overlay."""
    if elements:
        has_dialog = any(e.role == "dialog" and e.attributes.get("aria-modal") == "true" for e in elements)
        has_banner = any("cookie-consent" in (e.attributes.get("id") or "") or "consent-banner" in (e.attributes.get("class") or "") for e in elements)
        has_close_btn = any(
            (e.tag == "button" or e.role == "button")
            and any(kw in (e.text or "").lower() or kw in (e.attributes.get("aria-label") or "").lower() for kw in ["reject all", "accept cookies", "dismiss", "decline", "not now"])
            for e in elements
        )
        if (has_dialog or has_banner) and has_close_btn:
            return True

    if not hasattr(page, "evaluate"):
        return False
    try:
        res = page.evaluate("""() => {
            const dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog, .cookie-banner, .consent-banner, #cookie-consent');
            for (const d of dialogs) {
                const s = window.getComputedStyle(d);
                if (s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0') return true;
            }
            return false;
        }""")
        if hasattr(res, "_mock_name") or not isinstance(res, bool):
            return False
        return res is True
    except Exception:
        return False


def choose_goal_exploration_action(
    page: Page,
    elements: list[ElementInfo],
    memory: AgentMemory,
) -> dict[str, Any] | None:
    """
    Goal-aware exploration policy.
    Determines next action based on current page role, target state, and inspection needs.
    """
    plan = memory.task_plan
    if not plan:
        return None

    curr_url_lower = getattr(page, "url", "").lower()
    is_target_sat, _ = memory.is_target_page_satisfied(page)

    # A. Auth Barrier Guard (Skill 24): Clean pause if login / CAPTCHA detected
    has_barrier, barrier_desc = check_authentication_barrier(page)
    if has_barrier:
        memory.auth_required = True
        memory.auth_details = {"barrier": barrier_desc, "url": getattr(page, "url", "")}
        logger.warning("Authentication barrier detected: %s. Yielding clean pause.", barrier_desc)
        return {
            "action": "fail",
            "reasoning": f"Authentication required: {barrier_desc} encountered on {getattr(page, 'url', '')}. Please complete login/verification in browser.",
            "confidence": 0.99,
            "auth_required": True,
        }

    # B. Modal Dismissal Policy (Skill 11)
    if check_blocking_modal(page, elements) and not memory.extracted_data.get("modal_dismissed"):
        memory.extracted_data["modal_dismissed"] = True
        return {
            "action": "dismiss_modal",
            "reasoning": "Dismissing blocking modal/consent overlay before proceeding.",
            "confidence": 0.95,
        }

    # C. Form Filling Policy (Skill 5)
    if (plan.intent == "form_filling" or getattr(plan, "form_fields", None)) and getattr(plan, "form_fields", None):
        if not memory.extracted_data.get("form_filled"):
            memory.extracted_data["form_filled"] = True
            memory.extracted_data["form_submitted"] = True
            return {
                "action": "fill_form",
                "fields": plan.form_fields,
                "submit": True,
                "reasoning": f"Filling form inputs {list(plan.form_fields.keys())} and submitting.",
                "confidence": 0.95,
            }
        else:
            return {
                "action": "done",
                "confidence": 0.95,
                "reasoning": "Form submitted successfully.",
                "result": dict(memory.extracted_data),
            }

    # D. Search Input Policy: Check if we need to search on a search engine or platform home
    is_search_page = (
        any(seg in curr_url_lower for seg in ["/search", "/results", "?q=", "&q=", "search_query=", "/w/index.php?search="])
        or (("q=" in curr_url_lower or "query=" in curr_url_lower) and any(se in curr_url_lower for se in ["duckduckgo", "google", "bing", "youtube", "yahoo", "amazon", "flipkart"]))
    )
    is_search_needed = (
        bool(plan.search_query or memory.normalized_query)
        and not is_search_page
        and not is_target_sat
    )
    if is_search_needed:
        search_inputs = [
            e for e in elements
            if (e.tag in ("input", "textarea") and (e.attributes.get("type") or "").lower() in ("search", "text", ""))
            or "search" in (e.attributes.get("placeholder") or "").lower()
            or "search" in (e.attributes.get("name") or "").lower()
            or "search" in (e.attributes.get("id") or "").lower()
            or "search" in (e.attributes.get("aria-label") or "").lower()
        ]
        if search_inputs:
            sq = plan.search_query or memory.normalized_query
            return {
                "action": "type",
                "element_id": search_inputs[0].id,
                "text": sq,
                "press_enter": True,
                "reasoning": f"Entering search query '{sq}' into search bar",
                "confidence": 0.95,
            }

    # E. Table Understanding Policy (Skill 16, 17)
    if plan.intent == "table_understanding" or getattr(plan, "table_query", ""):
        from browser_agent.perception import extract_tables
        tables = extract_tables(page)
        if tables:
            memory.extracted_data["table_data"] = tables
            return {
                "action": "done",
                "confidence": 0.95,
                "reasoning": f"Extracted {len(tables)} tables from page.",
                "result": dict(memory.extracted_data),
            }

    # F. Comparison Policy (Skill 18)
    if plan.intent == "comparison":
        is_search_home = (
            any(se in curr_url_lower for se in ["duckduckgo.com", "google.com", "bing.com", "yahoo.com"])
            and not any(seg in curr_url_lower for seg in ["/search", "?q=", "&q="])
        )
        if not is_search_home and not is_search_needed:
            from browser_agent.constraints import parse_numeric_price, parse_numeric_rating
            candidates = find_candidate_content_items(elements, query=plan.search_query or memory.normalized_query)
            comp_records = []
            limit = max(2, getattr(plan, "comparison_count", 2) or 2)
            for elem, score, title in candidates[:limit]:
                t_lower = (elem.text or title).lower()
                price = parse_numeric_price(t_lower)
                rating = parse_numeric_rating(t_lower)
                comp_records.append({
                    "title": title or elem.text[:50],
                    "price": price,  # None if missing (never 0!)
                    "rating": rating, # None if missing
                })
            has_required_data = True
            if getattr(plan, "comparison_fields", None) and "price" in plan.comparison_fields:
                valid_prices = [c for c in comp_records if c.get("price") is not None]
                if len(valid_prices) < limit:
                    has_required_data = False
            if comp_records and len(comp_records) >= limit and has_required_data:
                memory.extracted_data["comparison"] = comp_records
                return {
                    "action": "done",
                    "confidence": 0.95,
                    "reasoning": f"Structured comparison of {len(comp_records)} candidates completed.",
                    "result": dict(memory.extracted_data),
                }

    # G. Download Policy (Skill 13)
    if plan.intent == "download":
        dl_elem = next((e for e in elements if "download" in (e.text or "").lower() or (e.attributes.get("href") or "").endswith((".pdf", ".zip", ".csv"))), None)
        if dl_elem:
            return {
                "action": "download",
                "element_id": dl_elem.id,
                "target": dl_elem.text,
                "reasoning": f"Clicking download link '{dl_elem.text[:30]}'",
                "confidence": 0.95,
            }

    # 2. Check if we are on search results page
    is_search_results_page = (
        any(seg in curr_url_lower for seg in ["/search", "/results", "?q=", "&q=", "search_query=", "/w/index.php?search="])
        or (("q=" in curr_url_lower or "query=" in curr_url_lower) and any(se in curr_url_lower for se in ["duckduckgo", "google", "bing", "youtube", "yahoo"]))
    )

    if is_search_results_page:
        # Find matching link for the target
        target_link = find_matching_target_link(elements, plan.target, plan.target_type)
        if not target_link:
            pref = "video" if any(k in (plan.target or "").lower() or k in memory.task.lower() for k in ["video", "song", "track"]) else None
            target_link = select_best_candidate_link(
                elements,
                query=plan.search_query or memory.normalized_query,
                target=plan.target,
                preferred_type=pref,
                unvisited_only=True,
                visited_hrefs=getattr(memory, "visited_urls", set()),
            )
        if target_link:
            return {
                "action": "click",
                "element_id": target_link.id,
                "reasoning": f"Opening target search result link '{target_link.text[:40]}'",
                "confidence": 0.95,
            }
        # Attempt to extract requested information from search results before scrolling
        if plan.requested_information:
            extracted = inspect_page_for_requested_info(page, plan.requested_information, target=plan.target)
            if extracted:
                # Record extraction in memory (optional) and consider task satisfied
                return {
                    "action": "verify",
                    "target": plan.target,
                    "extracted": extracted,
                    "reasoning": f"Extracted requested info {list(extracted.keys())} from search results without scrolling",
                    "confidence": 0.95,
                }
        # If no target link visible, consider scrolling only if there are potential new links
        if not memory.scroll_state.reached_bottom:
            # Determine if any link elements remain that could contain the target or requested info
            has_potential_links = any(e.tag == "a" or e.role == "link" for e in elements)
            if has_potential_links:
                return {
                    "action": "scroll",
                    "direction": "down",
                    "amount": 600,
                    "reasoning": f"Target '{plan.target}' not in current viewport and more links may be available; scrolling search results",
                    "confidence": 0.85,
                }

    # 3. Check if we are on TARGET CONTENT PAGE or have active procedural steps
    is_target_sat, _ = memory.is_target_page_satisfied(page)

    # Evaluate pending procedural requirements in strict order
    if getattr(plan, "procedural_requirements", None):
        # Update procedure progress against current page state
        memory.is_procedure_satisfied(page)

        next_proc = memory.current_procedure
        if next_proc and next_proc not in getattr(memory, "failed_procedures", []):
            proc_lower = next_proc.lower()

            # A. GO_BACK requirement: e.g. "go back to the India article", "return to India"
            if any(v in proc_lower for v in ["go back", "navigate back", "return"]):
                return {
                    "action": "go_back",
                    "reasoning": f"Executing procedural requirement: {next_proc}",
                    "confidence": 0.95,
                }

            # B. PLAY / MEDIA requirement: e.g. "play video", "play it", "start playback"
            if any(v in proc_lower for v in ["play", "start playback"]):
                return {
                    "action": "play",
                    "reasoning": f"Executing procedural requirement: {next_proc}",
                    "confidence": 0.95,
                }

            # C. WAIT FOR COMPLETION requirement: e.g. "wait for video completion", "after the video ends"
            if any(v in proc_lower for v in ["wait for video", "after the video", "when it finishes", "video ends"]):
                return {
                    "action": "wait",
                    "seconds": 2,
                    "reasoning": f"Waiting for media event completion: {next_proc}",
                    "confidence": 0.9,
                }

            # D. OPEN requirement on candidate link: e.g. "open the first relevant video", "open video"
            if any(v in proc_lower for v in ["open", "choose", "select first"]) and not is_target_sat:
                # 1. First check if a direct matching target link exists in visible elements
                if plan.target:
                    direct_link = find_matching_target_link(elements, plan.target, plan.target_type)
                    if direct_link:
                        return {
                            "action": "click",
                            "element_id": direct_link.id,
                            "reasoning": f"Executing procedural requirement: {next_proc} -> opening direct target link '{direct_link.text[:40]}'",
                            "confidence": 0.95,
                        }

                # 2. Select best candidate link only if on search results, search was already performed,
                # or there is no search input to search from
                has_search_input = any(
                    e.tag in ("input", "textarea") and (e.attributes.get("type") or "text").lower() in ("search", "text", "")
                    for e in elements
                )
                can_select_candidate = (
                    is_search_results_page
                    or memory.exploration_state.search_performed
                    or not (plan.search_query and has_search_input)
                )

                if can_select_candidate:
                    pref = "video" if any(k in proc_lower or k in (plan.target or "").lower() for k in ["video", "song", "track"]) else None
                    cand = select_best_candidate_link(
                        elements,
                        query=plan.search_query or memory.normalized_query,
                        target=plan.target,
                        preferred_type=pref,
                    )
                    if cand:
                        return {
                            "action": "click",
                            "element_id": cand.id,
                            "reasoning": f"Executing procedural requirement: {next_proc} -> opening '{cand.text[:40]}'",
                            "confidence": 0.95,
                        }

            # E. CLICK requirement: e.g. "click History of India", "click a link called X"
            if any(v in proc_lower for v in ["click", "press", "select"]):
                # Only look for procedural click if target is satisfied or no target specified
                if is_target_sat or not plan.target:
                    m = re.search(r"\b(?:called|titled|named)\s+[\"']?([^\"'\n\r]+)[\"']?", next_proc, re.I)
                    target_txt = m.group(1).strip().lower() if m else re.sub(r"^(?:click|press|select)\s+(?:on\s+)?(?:the\s+|a\s+)?(?:link\s+|button\s+)?", "", next_proc, flags=re.I).strip().lower()
                    target_txt = target_txt.strip("\"'")

                    # 1. Check if matching element is in current viewport (elements)
                    matching_elem = next(
                        (e for e in elements if target_txt == (e.text or "").lower() or (e.attributes.get("title") or "").lower() == target_txt),
                        None
                    )
                    if not matching_elem:
                        matching_elem = next(
                            (e for e in elements if target_txt in (e.text or "").lower() or (e.attributes.get("title") or "").lower() == target_txt),
                            None
                        )

                    if matching_elem:
                        return {
                            "action": "click",
                            "element_id": matching_elem.id,
                            "target": target_txt,
                            "reasoning": f"Executing procedural requirement: click '{matching_elem.text[:40]}'",
                            "confidence": 0.95,
                        }

                    # 2. Inspect full page DOM
                    dom_info = inspect_procedural_element(page, target_txt, elements)

                    if not dom_info.get("exists", False):
                        logger.warning(
                            "Procedural element '%s' does NOT exist anywhere in document DOM. Terminating impossible procedure.",
                            target_txt
                        )
                        if not hasattr(memory, "failed_procedures"):
                            memory.failed_procedures = []
                        memory.failed_procedures.append(next_proc)
                        return {
                            "action": "fail",
                            "reasoning": f"Procedural element '{target_txt}' does not exist on page '{page.title() if hasattr(page, 'title') else ''}'. Bounded full-page inspection confirmed element is absent.",
                            "confidence": 0.95,
                        }

                    # 3. Element exists and in viewport
                    if dom_info.get("inViewport", False):
                        return {
                            "action": "click",
                            "target": target_txt,
                            "reasoning": f"Executing procedural requirement: click '{target_txt}' (found in viewport)",
                            "confidence": 0.95,
                        }

                    # 4. Element exists in DOM outside viewport -> scroll toward it
                    scroll_dir = dom_info.get("scrollDirection", "down")
                    scroll_dist = dom_info.get("scrollDistance", 600)
                    if scroll_dir not in ("up", "down"):
                        scroll_dir = "down"
                    if scroll_dist <= 0:
                        scroll_dist = 600
                    return {
                        "action": "scroll",
                        "direction": scroll_dir,
                        "amount": scroll_dist,
                        "reasoning": f"Procedural link '{target_txt}' located {scroll_dir} in DOM; scrolling {scroll_dist}px toward it.",
                        "confidence": 0.9,
                    }

    if is_target_sat:
        # We are on the target page!
        memory.exploration_state.target_page_reached = True

        # Never conclude if procedures remain!
        if memory.current_procedure is not None:
            logger.info("On target page, but procedure %d/%d ('%s') remains pending.", memory.procedure_index + 1, memory.total_procedures, memory.current_procedure)
            if memory.check_and_advance_open_procedure(page):
                if memory.current_procedure is None and plan.intent in ("navigation", "media_interaction"):
                    return {
                        "action": "done",
                        "confidence": 0.98,
                        "reasoning": f"Reached target destination '{plan.target}' ({page.url}) and all procedures completed. Task is complete.",
                        "result": {"url": getattr(page, "url", ""), "title": page.title() if callable(getattr(page, "title", None)) else str(getattr(page, "title", "")), **dict(memory.extracted_data)},
                    }

        # If navigation-only or media_interaction intent and all procedures complete:
        if plan.intent in ("navigation", "media_interaction") and memory.current_procedure is None:
            return {
                "action": "done",
                "confidence": 0.98,
                "reasoning": f"Reached target destination '{plan.target}' ({page.url}) and all procedures completed. Task is complete.",
                "result": {"url": getattr(page, "url", ""), "title": page.title() if callable(getattr(page, "title", None)) else str(getattr(page, "title", "")), **dict(memory.extracted_data)},
            }

        # If information extraction intent:
        if plan.requested_information:
            # Inspect visible content / text
            extracted = inspect_page_for_requested_info(page, plan.requested_information, target=plan.target)
            if extracted:
                memory.update_extracted_data(extracted)
                logger.info("Extracted grounded information on target page: %s", extracted)
                # Check if all requested items are satisfied
                if memory.is_information_satisfied(memory.task, page):
                    proc_sat, _ = memory.is_procedure_satisfied(page)
                    if proc_sat and memory.current_procedure is None:
                        return {
                            "action": "done",
                            "confidence": 0.98,
                            "reasoning": f"Extracted requested information {list(extracted.keys())} from target page '{page.title()}'.",
                            "result": dict(memory.extracted_data),
                        }
                    else:
                        logger.info("Information extracted but procedures remain: %s", memory.current_procedure)

            # If information not visible in current viewport:
            # Scroll down to inspect below-fold content on target page
            if not memory.scroll_state.reached_bottom:
                return {
                    "action": "scroll",
                    "direction": "down",
                    "amount": 600,
                    "reasoning": f"Requested information {plan.requested_information} not visible in current viewport; scrolling down to inspect content below the fold.",
                    "confidence": 0.9,
                }
            elif not memory.scroll_state.reached_top:
                return {
                    "action": "scroll",
                    "direction": "up",
                    "amount": 600,
                    "reasoning": "Reached bottom of target page; scrolling up to inspect remaining sections.",
                    "confidence": 0.8,
                }
            else:
                return {
                    "action": "done",
                    "confidence": 0.85,
                    "reasoning": f"Full target page inspected; requested information {plan.requested_information} not found.",
                    "result": dict(memory.extracted_data),
                }

    # 4. Search-First Rule: If on destination platform home/entry page and target not yet reached
    if not is_search_results_page and not is_target_sat:
        # A. First check if an exact matching target link is visible directly on page
        if plan.target:
            target_link = find_matching_target_link(elements, plan.target, plan.target_type)
            if target_link:
                return {
                    "action": "click",
                    "element_id": target_link.id,
                    "reasoning": f"Found direct target link '{target_link.text[:40]}' on entry page",
                    "confidence": 0.95,
                }

        # B. If search input exists, type the search query and submit with Enter
        if plan.search_query:
            candidate_inputs: list[tuple[int, ElementInfo]] = []
            for e in elements:
                if e.tag not in ("input", "textarea"):
                    continue
                attrs = " ".join(str(v or "") for v in (
                    e.attributes.get("type"),
                    e.attributes.get("name"),
                    e.attributes.get("id"),
                    e.attributes.get("placeholder"),
                    e.attributes.get("aria-label"),
                )).lower()
                score = 0
                if e.attributes.get("type") == "search":
                    score = 100
                elif "search" in (e.attributes.get("name") or "").lower() or "search" in (e.attributes.get("id") or "").lower():
                    score = 90
                elif "search" in attrs:
                    score = 80
                elif e.tag == "input" and (e.attributes.get("type") or "text").lower() in ("text", ""):
                    score = 60
                elif e.tag == "textarea":
                    score = 40
                if score > 0:
                    candidate_inputs.append((score, e))

            if candidate_inputs and not memory.exploration_state.search_performed:
                candidate_inputs.sort(key=lambda x: x[0], reverse=True)
                best_input = candidate_inputs[0][1]
                memory.exploration_state.search_performed = True
                dest_name = plan.destination or "current site"
                return {
                    "action": "type",
                    "element_id": best_input.id,
                    "text": plan.search_query,
                    "press_enter": True,
                    "reasoning": f"Entering search query '{plan.search_query}' into search box on {dest_name}",
                    "confidence": 0.95,
                }

    return None
