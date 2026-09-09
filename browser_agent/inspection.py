"""Generic DOM-first inspection for arbitrary webpages.

This module deliberately avoids website-specific selectors and answer databases.
It extracts semantic page structure (key/value pairs, tables, headings, links,
JSON-LD and visible text) so the agent can ground decisions in the live DOM.
Visual/VLM perception remains a fallback for pages whose useful state is not
represented in accessible HTML.
"""
from __future__ import annotations

import json
import re
from typing import Any


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "with", "on", "in",
    "is", "are", "was", "were", "tell", "give", "find", "show", "what", "who",
    "when", "where", "how", "me", "its", "their", "this", "that",
}


def normalize_label(value: str) -> str:
    """Normalize a human/DOM label for deterministic matching."""
    return _NORMALIZE_RE.sub(" ", str(value or "").lower()).strip()


def label_tokens(value: str) -> set[str]:
    return {t for t in normalize_label(value).split() if t not in _STOPWORDS and len(t) > 1}


def _clean(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _similarity(label: str, query: str) -> float:
    a = label_tokens(label)
    b = label_tokens(query)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a <= b or b <= a:
        return 0.9
    overlap = len(a & b) / max(1, min(len(a), len(b)))
    return overlap


PAGE_STRUCTURE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const text = (el) => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  const attrs = (el) => ({
    id: el?.id || '',
    className: typeof el?.className === 'string' ? el.className : '',
    role: el?.getAttribute?.('role') || '',
    ariaLabel: el?.getAttribute?.('aria-label') || '',
    title: el?.getAttribute?.('title') || ''
  });

  const facts = [];
  const pushFact = (label, value, source, element) => {
    label = text(label);
    value = text(value);
    if (!label || !value || value.length > 1000) return;
    facts.push({ label: label.slice(0, 200), value: value.slice(0, 500), source,
      element: element ? { tag: element.tagName.toLowerCase(), ...attrs(element) } : null });
  };

  // Definition lists: the cleanest generic key/value representation.
  for (const dl of document.querySelectorAll('dl')) {
    let pending = '';
    for (const child of dl.children) {
      const tag = child.tagName.toLowerCase();
      if (tag === 'dt') pending = text(child);
      else if (tag === 'dd' && pending) { pushFact(pending, child, 'dom_dl', child); pending = ''; }
    }
  }

  // Tables: support infoboxes, comparison tables, specs and ordinary data tables.
  for (const table of Array.from(document.querySelectorAll('table')).slice(0, 30)) {
    if (!visible(table)) continue;
    for (const row of Array.from(table.querySelectorAll('tr')).slice(0, 300)) {
      const cells = Array.from(row.querySelectorAll(':scope > th, :scope > td'));
      if (cells.length === 2) pushFact(cells[0], cells[1], 'dom_table', row);
      else if (cells.length > 2) {
        const headers = cells.map(c => text(c));
        if (headers.length && row.querySelector('th')) {
          // Header rows are retained separately; data rows are handled below.
          continue;
        }
      }
    }
  }

  // Common ARIA grid/list rows without assuming a particular framework.
  for (const row of Array.from(document.querySelectorAll('[role="row"]')).slice(0, 200)) {
    if (!visible(row)) continue;
    const cells = Array.from(row.querySelectorAll('[role="rowheader"], [role="gridcell"], [role="cell"]'));
    if (cells.length === 2) pushFact(cells[0], cells[1], 'dom_aria_row', row);
  }

  // Microdata/meta information is often more reliable than rendered prose.
  for (const el of Array.from(document.querySelectorAll('[itemprop]')).slice(0, 500)) {
    if (!visible(el)) continue;
    const prop = el.getAttribute('itemprop') || '';
    const value = el.getAttribute('content') || text(el);
    if (prop && value) pushFact(prop, value, 'dom_itemprop', el);
  }

  // JSON-LD is structured page data and is still page-grounded evidence.
  const jsonld = [];
  for (const script of Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 20)) {
    const raw = script.textContent || '';
    if (raw.trim()) jsonld.push(raw.slice(0, 20000));
  }

  const headings = Array.from(document.querySelectorAll('h1,h2,h3')).slice(0, 100)
    .filter(visible).map(el => text(el)).filter(Boolean);

  const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 300)
    .filter(visible).map(a => ({ text: text(a).slice(0, 250), href: a.href }));

  return {
    url: location.href,
    title: document.title || '',
    h1: text(document.querySelector('h1')),
    headings,
    facts,
    jsonld,
    links,
    body_text: text(document.body).slice(0, 20000)
  };
}
"""


def inspect_page_structure(page: Any) -> dict[str, Any]:
    """Return a normalized, generic structural snapshot of the live DOM."""
    if not hasattr(page, "evaluate"):
        return {}
    try:
        data = page.evaluate(PAGE_STRUCTURE_JS)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _flatten_json(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten JSON-LD into label/value pairs without assuming a schema."""
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = f"{prefix} {key}".strip()
            if isinstance(child, (str, int, float, bool)):
                out.append((label, str(child)))
            else:
                out.extend(_flatten_json(child, label))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(_flatten_json(child, f"{prefix} {idx}".strip()))
    return out


def extract_structured_facts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert structural DOM data into deduplicated evidence candidates."""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in snapshot.get("facts", []) or []:
        if not isinstance(item, dict):
            continue
        label, value = _clean(item.get("label")), _clean(item.get("value"))
        if not label or not value:
            continue
        key = (normalize_label(label), normalize_label(value))
        if key in seen:
            continue
        seen.add(key)
        facts.append({
            "field": label,
            "value": value,
            "source": item.get("source", "dom"),
            "element": item.get("element"),
        })

    for raw in snapshot.get("jsonld", []) or []:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        for label, value in _flatten_json(parsed):
            if not label or not value:
                continue
            key = (normalize_label(label), normalize_label(value))
            if key in seen:
                continue
            seen.add(key)
            facts.append({"field": label, "value": _clean(value), "source": "dom_jsonld", "element": None})

    return facts


def inspect_requested_information(
    page: Any,
    requested_info: list[str],
    target: str | None = None,
) -> dict[str, Any]:
    """Extract requested facts using DOM structure first, then bounded text fallback.

    The function never invents values. A value is returned only when it is grounded
    in the current page's DOM/structured data.
    """
    if not requested_info:
        return {}
    snapshot = inspect_page_structure(page)
    if not snapshot:
        return {}

    facts = extract_structured_facts(snapshot)
    result: dict[str, Any] = {}

    for requested in requested_info:
        req = normalize_label(requested)
        best: tuple[float, dict[str, Any]] | None = None
        for fact in facts:
            score = _similarity(fact["field"], req)
            if score < 0.75:
                # Also allow a requested phrase to match a structured field with
                # one useful semantic token, but never accept arbitrary numeric text.
                req_tokens = label_tokens(requested)
                field_tokens = label_tokens(fact["field"])
                if not (req_tokens and field_tokens and req_tokens & field_tokens):
                    continue
                score = 0.76
            if best is None or score > best[0]:
                best = (score, fact)

        if best is not None:
            value = best[1]["value"]
            key = _result_key(requested, best[1]["field"])
            result[key] = value
            continue

        # Minimal generic text fallback: only accept a labeled line/segment where
        # the requested label appears immediately before a value. This is deliberately
        # conservative to avoid the old "first number in page" failure mode.
        body = str(snapshot.get("body_text") or "")
        value = _labeled_text_value(body, requested)
        if value is not None:
            result[_result_key(requested, requested)] = value

    # Heading/title are structural facts, not LLM guesses.
    for requested in requested_info:
        req = normalize_label(requested)
        if req in {"heading", "page heading", "main heading"} and snapshot.get("h1"):
            result["heading"] = snapshot["h1"]
        elif req == "title" and snapshot.get("title"):
            result["title"] = snapshot["title"]

    return result


def _result_key(requested: str, field: str) -> str:
    tokens = label_tokens(requested) or label_tokens(field)
    return "_".join(sorted(tokens)) if tokens else normalize_label(field).replace(" ", "_")


def _labeled_text_value(body: str, requested: str) -> str | None:
    labels = [normalize_label(requested)]
    # Common phrasing variants are generated from the request itself, not a site.
    if requested.lower().startswith("official "):
        labels.append(normalize_label(requested[9:]))
    for label in labels:
        if not label:
            continue
        pattern = re.compile(rf"(?im)(?:^|[\n\r•])\s*{re.escape(label)}\s*(?::|–|-|\t)\s*([^\n\r•]{{1,200}})")
        match = pattern.search(body)
        if match:
            value = _clean(match.group(1), 300)
            if value:
                return value
    return None
