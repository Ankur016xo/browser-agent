"""
Perception Engine for the Browser Agent.
Extracts interactive DOM elements, computes bounding boxes, and generates
Set-of-Marks (SOM) visual annotations on screenshots.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page

from browser_agent.logging import get_logger
from browser_agent.state import ElementInfo

logger = get_logger(__name__)

# JavaScript snippet to extract interactive DOM elements and their viewport bounding boxes
EXTRACT_ELEMENTS_JS = """
() => {
    const isVisible = (elem, rect) => {
        if (!rect || rect.width <= 3 || rect.height <= 3) return false;
        const style = window.getComputedStyle(elem);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        
        const vw = window.innerWidth || document.documentElement.clientWidth;
        const vh = window.innerHeight || document.documentElement.clientHeight;
        
        // Must intersect viewport
        if (rect.bottom < 0 || rect.top > vh || rect.right < 0 || rect.left > vw) return false;
        return true;
    };

    const interactiveSelectors = [
        'button',
        'a[href]',
        'input',
        'textarea',
        'select',
        '[role="button"]',
        '[role="dialog"] button',
        '[aria-modal="true"] button',
        '[aria-label*="close" i]',
        '[aria-label*="dismiss" i]',
        '[class*="close" i]',
        '[role="link"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="tab"]',
        '[role="menuitem"]',
        '[role="searchbox"]',
        '[role="combobox"]',
        '[role="option"]',
        '[role="switch"]',
        '[role="slider"]',
        '[role="spinbutton"]',
        '[contenteditable="true"]',
        '[onclick]',
        '[onmouseenter]',
        '[onmouseover]',
        '[tabindex]:not([tabindex="-1"])',
        'summary',
    ];

    const elements = [];
    const seenRects = [];

    const nodes = document.querySelectorAll(interactiveSelectors.join(','));
    
    let idCounter = 1;
    for (const node of nodes) {
        const rect = node.getBoundingClientRect();
        if (!isVisible(node, rect)) continue;

        // Avoid duplicate overlapping elements with nearly identical coordinates (e.g. nested span in button)
        const isDuplicate = seenRects.some(r => 
            Math.abs(r.x - rect.x) < 4 &&
            Math.abs(r.y - rect.y) < 4 &&
            Math.abs(r.width - rect.width) < 4 &&
            Math.abs(r.height - rect.height) < 4
        );
        if (isDuplicate) continue;
        seenRects.push({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });

        // Extract text representation
        let text = (node.innerText || node.textContent || '').trim();
        if (node.tagName.toLowerCase() === 'input' || node.tagName.toLowerCase() === 'textarea') {
            const val = node.value || '';
            if (val) text = val;
        }
        if (!text) {
            text = (node.getAttribute('title') || node.getAttribute('aria-label') || '').trim();
            if (!text && node.querySelector('img')) {
                const img = node.querySelector('img');
                text = (img.getAttribute('alt') || img.getAttribute('title') || '').trim();
            }
            if (!text && node.getAttribute('href')) {
                const hrefVal = node.getAttribute('href') || '';
                const slugMatch = hrefVal.match(/\\/([a-zA-Z0-9_-]{5,80})(?:\\/p\\/|\\/dp\\/|\\?|$)/);
                if (slugMatch) {
                    text = slugMatch[1].replace(/[-_]+/g, ' ').trim();
                }
            }
        }

        const tag = node.tagName.toLowerCase();
        const type = node.getAttribute('type') || '';
        const role = node.getAttribute('role') || '';
        const placeholder = node.getAttribute('placeholder') || '';
        const ariaLabel = node.getAttribute('aria-label') || '';
        const name = node.getAttribute('name') || '';
        const idAttr = node.getAttribute('id') || '';
        const href = node.getAttribute('href') || '';
        const title = node.getAttribute('title') || '';

        // Accessible name computation
        let accessibleName = '';
        const ariaLabelledBy = node.getAttribute('aria-labelledby') || '';
        if (ariaLabel) {
            accessibleName = ariaLabel;
        } else if (ariaLabelledBy) {
            try {
                const refElem = document.getElementById(ariaLabelledBy);
                if (refElem) accessibleName = (refElem.innerText || refElem.textContent || '').trim();
            } catch (e) {}
        }
        if (!accessibleName) {
            accessibleName = (title || placeholder || '').trim();
        }

        // Associated label text computation
        let labelText = '';
        if (idAttr) {
            try {
                const lbl = document.querySelector('label[for="' + CSS.escape(idAttr) + '"]');
                if (lbl) labelText = (lbl.innerText || lbl.textContent || '').trim();
            } catch (e) {}
        }
        if (!labelText) {
            try {
                const parentLbl = node.closest('label');
                if (parentLbl) {
                    labelText = (parentLbl.innerText || parentLbl.textContent || '').trim();
                }
            } catch (e) {}
        }
        if (!accessibleName && labelText) {
            accessibleName = labelText;
        }

        // State attributes
        let checked = null;
        if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
            checked = !!node.checked;
        } else if (node.hasAttribute('aria-checked')) {
            checked = node.getAttribute('aria-checked') === 'true';
        }

        const disabled = !!node.disabled || node.getAttribute('aria-disabled') === 'true';
        const required = !!node.required || node.getAttribute('aria-required') === 'true';
        
        let value = '';
        if (tag === 'input' || tag === 'textarea' || tag === 'select') {
            value = node.value || '';
        }

        let ariaExpanded = null;
        if (node.hasAttribute('aria-expanded')) {
            ariaExpanded = node.getAttribute('aria-expanded') === 'true';
        }

        const ariaHasPopup = node.getAttribute('aria-haspopup') || '';
        let ariaSelected = null;
        if (node.hasAttribute('aria-selected')) {
            ariaSelected = node.getAttribute('aria-selected') === 'true';
        }
        const ariaInvalid = node.getAttribute('aria-invalid') === 'true';

        elements.push({
            id: idCounter++,
            tag: tag,
            text: text.substring(0, 150),
            type: type,
            role: role,
            accessible_name: accessibleName.substring(0, 150),
            label_text: labelText.substring(0, 150),
            checked: checked,
            disabled: disabled,
            required: required,
            value: value.substring(0, 100),
            aria_expanded: ariaExpanded,
            aria_haspopup: ariaHasPopup,
            aria_selected: ariaSelected,
            aria_invalid: ariaInvalid,
            bbox: [
                Math.round(rect.left),
                Math.round(rect.top),
                Math.round(rect.width),
                Math.round(rect.height)
            ],
            center: [
                Math.round(rect.left + rect.width / 2),
                Math.round(rect.top + rect.height / 2)
            ],
            attributes: {
                placeholder: placeholder,
                "aria-label": ariaLabel,
                name: name,
                id: idAttr,
                href: href,
                title: title,
            }
        });

        if (idCounter > 75) break; // Limit to most relevant elements
    }

    return elements;
}
"""


class PerceptionEngine:
    """Extracts elements and annotates screenshots for visual grounding."""

    def __init__(self, font_size: int = 12) -> None:
        self.font_size = font_size
        self._font = None

    def _get_font(self):
        if self._font is None:
            try:
                # Try common system fonts
                self._font = ImageFont.truetype("arial.ttf", self.font_size)
            except Exception:
                try:
                    self._font = ImageFont.truetype("segoeui.ttf", self.font_size)
                except Exception:
                    self._font = ImageFont.load_default()
        return self._font

    def extract_interactive_elements(self, page: Page) -> list[ElementInfo]:
        """Query page DOM for visible interactive elements and return structured ElementInfo."""
        try:
            raw_elements = page.evaluate(EXTRACT_ELEMENTS_JS)
            elements: list[ElementInfo] = []
            for item in raw_elements:
                elements.append(
                    ElementInfo(
                        id=int(item["id"]),
                        tag=str(item["tag"]),
                        text=str(item["text"]),
                        element_type=str(item.get("type", "")),
                        role=str(item.get("role", "")),
                        bbox=tuple(item.get("bbox", [0, 0, 0, 0])),
                        center=tuple(item.get("center", [0, 0])),
                        attributes=item.get("attributes", {}),
                        confidence=1.0,
                        accessible_name=str(item.get("accessible_name", "")),
                        label_text=str(item.get("label_text", "")),
                        checked=item.get("checked"),
                        disabled=bool(item.get("disabled", False)),
                        required=bool(item.get("required", False)),
                        value=str(item.get("value", "")),
                        aria_expanded=item.get("aria_expanded"),
                        aria_haspopup=str(item.get("aria_haspopup", "")),
                        aria_selected=item.get("aria_selected"),
                        aria_invalid=bool(item.get("aria_invalid", False)),
                    )
                )
            logger.debug("Extracted %d interactive elements from page", len(elements))
            return elements
        except Exception as exc:
            logger.error("Failed to extract DOM elements: %s", exc)
            return []

    def annotate_screenshot(
        self,
        screenshot_path: str | Path,
        elements: list[ElementInfo],
        output_path: str | Path | None = None,
        viewport: tuple[int, int] | None = None,
    ) -> Path:
        """
        Draw Set-of-Marks (bounding boxes with numbered ID badges) on screenshot.
        Automatically scales coordinates if screenshot dimensions differ from viewport.
        Returns the path to the annotated screenshot.
        """
        screenshot_path = Path(screenshot_path)
        if output_path is None:
            output_path = screenshot_path.with_name(
                screenshot_path.stem + "_annotated" + screenshot_path.suffix
            )
        else:
            output_path = Path(output_path)

        if not screenshot_path.exists():
            logger.warning("Screenshot not found for annotation: %s", screenshot_path)
            return screenshot_path

        try:
            with Image.open(screenshot_path) as src_image:
                image = src_image.convert("RGBA")

            overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(overlay)
            font = self._get_font()

            # Calculate scaling factors if viewport is given
            scale_x = 1.0
            scale_y = 1.0
            if viewport and viewport[0] > 0 and viewport[1] > 0:
                scale_x = image.width / viewport[0]
                scale_y = image.height / viewport[1]

            # Palette for distinct colored bounding boxes
            palette = [
                ((59, 130, 246, 180), (29, 78, 216, 255)),    # Blue
                ((16, 185, 129, 180), (4, 120, 87, 255)),     # Green
                ((245, 158, 11, 180), (180, 83, 9, 255)),     # Amber
                ((239, 68, 68, 180), (185, 28, 28, 255)),     # Red
                ((139, 92, 246, 180), (109, 40, 217, 255)),   # Purple
                ((236, 72, 153, 180), (190, 24, 93, 255)),    # Pink
            ]

            for elem in elements:
                orig_x, orig_y, orig_w, orig_h = elem.bbox
                x = int(orig_x * scale_x)
                y = int(orig_y * scale_y)
                w = int(orig_w * scale_x)
                h = int(orig_h * scale_y)

                if w <= 0 or h <= 0:
                    continue

                color_idx = (elem.id - 1) % len(palette)
                fill_color, border_color = palette[color_idx]

                # Draw bounding box outline
                draw.rectangle(
                    [x, y, x + w, y + h],
                    outline=border_color,
                    width=2,
                )

                # Draw badge for element ID
                label = f"{elem.id}"
                # Measure badge size
                try:
                    left, top, right, bottom = font.getbbox(label)
                    text_w = right - left
                    text_h = bottom - top
                except Exception:
                    text_w = len(label) * 8
                    text_h = 12

                badge_pad = 3
                badge_w = text_w + badge_pad * 2 + 2
                badge_h = text_h + badge_pad * 2

                badge_x = max(0, x)
                badge_y = max(0, y - badge_h)
                if badge_y < 0:
                    badge_y = y

                # Draw badge background
                draw.rectangle(
                    [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                    fill=border_color,
                )
                # Draw badge text (white)
                draw.text(
                    (badge_x + badge_pad + 1, badge_y + 1),
                    label,
                    fill=(255, 255, 255, 255),
                    font=font,
                )

            # Combine original image with overlay
            combined = Image.alpha_composite(image, overlay).convert("RGB")
            combined.save(output_path, "PNG")
            logger.debug("Saved annotated screenshot to %s", output_path)
            return output_path

        except Exception as exc:
            logger.error("Failed to annotate screenshot: %s", exc)
            return screenshot_path

    def format_elements_for_prompt(self, elements: list[ElementInfo], max_items: int = 50) -> str:
        """Format the element list into clean structured text for the prompt."""
        if not elements:
            return "No interactive elements detected."

        lines = []
        for elem in elements[:max_items]:
            lines.append(elem.summary())
        return "\n".join(lines)


def extract_tables(page: Any) -> list[dict[str, Any]]:
    """
    Extract structured table data from HTML <table> elements on the page.
    Returns list of dicts with headers, rows, and row count.
    """
    if not hasattr(page, "evaluate"):
        return []
    try:
        raw_tables = page.evaluate("""() => {
            const tables = Array.from(document.querySelectorAll('table'));
            return tables.slice(0, 5).map((table, idx) => {
                let headers = Array.from(table.querySelectorAll('thead th, tr:first-child th')).map(th => th.innerText.trim());
                const rows = [];
                const trs = Array.from(table.querySelectorAll('tbody tr, tr')).slice(headers.length ? 1 : 0);
                for (const tr of trs) {
                    const cells = Array.from(tr.querySelectorAll('td, th')).map(c => c.innerText.trim());
                    if (cells.length === 0) continue;
                    if (!headers.length && rows.length === 0) {
                        headers = cells;
                        continue;
                    }
                    const rowObj = {};
                    cells.forEach((cell, i) => {
                        const col = headers[i] || `col_${i+1}`;
                        rowObj[col] = cell;
                    });
                    rows.push(rowObj);
                }
                const caption = table.querySelector('caption') ? table.querySelector('caption').innerText.trim() : '';
                return {
                    table_index: idx,
                    caption: caption,
                    headers: headers,
                    rows: rows.slice(0, 100),
                    row_count: rows.length
                };
            });
        }""")
        return raw_tables or []
    except Exception as exc:
        logger.error("Failed to extract tables: %s", exc)
        return []


def find_text_in_page(page: Any, query: str) -> dict[str, Any]:
    """
    Deterministic DOM search for text string before visual scanning.
    Locates matching elements, extracts text context, and retrieves bounding coordinates.
    """
    if not hasattr(page, "evaluate") or not query:
        return {"found": False}
    try:
        res = page.evaluate("""(searchQuery) => {
            const q = searchQuery.toLowerCase().trim();
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            let node;
            while (node = walker.nextNode()) {
                const txt = (node.textContent || '').toLowerCase();
                if (txt.includes(q)) {
                    const parent = node.parentElement;
                    if (parent && parent.offsetParent !== null) {
                        const rect = parent.getBoundingClientRect();
                        try {
                            parent.scrollIntoView({ block: 'center', inline: 'center' });
                        } catch (e) {}
                        return {
                            found: true,
                            text: (parent.innerText || parent.textContent || '').trim().substring(0, 200),
                            tag: parent.tagName.toLowerCase(),
                            bbox: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)],
                            center: [Math.round(rect.left + rect.width / 2), Math.round(rect.top + rect.height / 2)]
                        };
                    }
                }
            }
            return { found: false };
        }""", query)
        return res or {"found": False}
    except Exception as exc:
        logger.debug("find_text_in_page error: %s", exc)
        return {"found": False}

