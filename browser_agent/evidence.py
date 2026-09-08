from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    candidate_id: str | None
    field: str                              # e.g., "price", "rating", "capital"
    raw_value: Any                          # e.g., "₹49,999", "Paris"
    normalized_value: Any                   # e.g., 49999.0, "Paris"
    unit: str | None = None                 # e.g., "INR"
    source: Literal["dom", "url", "ocr", "vlm", "self_reported"] = "dom"
    confidence: float = 1.0                 # 0.0 to 1.0
    observation_id: str = ""
    page_url: str = ""
    supporting_text: str = ""
    timestamp: float = 0.0

    def is_trustworthy(self, min_confidence: float = 0.8) -> bool:
        """Self-reported evidence cannot satisfy hard constraints."""
        if self.source == "self_reported":
            return False
        return self.confidence >= min_confidence
