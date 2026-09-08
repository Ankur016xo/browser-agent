from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ConstraintSpec:
    field: str                              # e.g., "price", "rating", "origin", "destination", "cabin"
    operator: Literal["<=", ">=", "==", "!=", "contains", "in_range"]
    value: Any                              # e.g., 50000, 4.0, "Delhi", "economy"
    unit: str | None = None                 # e.g., "INR", "USD"
    required: bool = True


@dataclass(frozen=True)
class ProcedureSpec:
    procedure_id: str                       # e.g., "proc_1_open_india"
    order_index: int                        # 0-indexed execution order
    action_type: Literal["navigate", "click", "search", "extract", "back"]
    semantic_target: str                    # e.g., "India", "History of India", "capital"
    target_type: Literal["link", "input", "button", "content"]
    required: bool = True
    preconditions: dict[str, Any] | None = None   # e.g. {"url_contains": "wikipedia.org"}
    postconditions: dict[str, Any] | None = None  # e.g. {"url_contains": "History_of_India"}


@dataclass(frozen=True)
class TaskModel:
    """Canonical, immutable representation of a user task."""
    raw_task: str
    intent: Literal["search", "information_extraction", "navigation", "comparison", "aggregation", "action"]
    target_entity: str                      # e.g., "basketball shoes", "laptop", "flight", "India"
    target_type: str = "general"            # "product", "flight", "place", "document", "general"
    
    # Destination decomposition
    destination_platform: str | None = None # e.g., "amazon", "wikipedia", "youtube"
    destination_url: str | None = None      # Explicit URL if provided or resolved platform root
    geographic_destination: str | None = None # e.g., "Varanasi", "Lucknow", "India"
    geographic_origin: str | None = None    # e.g., "Delhi"
    
    search_query: str = ""                  # Concrete query string for search bars (does NOT include quantity keywords)
    requested_information: tuple[str, ...] = field(default_factory=tuple)  # e.g., ("price",), ("capital",)
    constraints: tuple[ConstraintSpec, ...] = field(default_factory=tuple)
    
    quantity: int | None = None             # None unless explicitly requested (e.g. 3)
    ranking_field: str | None = None        # "price", "rating", "departure_time"
    ranking_order: Literal["asc", "desc"] | None = None
    aggregation_operation: Literal["average", "min", "max", "count", "compare", "top_k"] | None = None
    aggregation_field: str | None = None    # Field to compute aggregation on (e.g. "price")
    
    procedural_requirements: tuple[ProcedureSpec, ...] = field(default_factory=tuple)
    ambiguity_state: Literal["resolved", "needs_clarification"] = "resolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_task": self.raw_task,
            "intent": self.intent,
            "target_entity": self.target_entity,
            "target_type": self.target_type,
            "destination_platform": self.destination_platform,
            "destination_url": self.destination_url,
            "geographic_destination": self.geographic_destination,
            "geographic_origin": self.geographic_origin,
            "search_query": self.search_query,
            "requested_information": list(self.requested_information),
            "constraints": [
                {
                    "field": c.field,
                    "operator": c.operator,
                    "value": c.value,
                    "unit": c.unit,
                    "required": c.required,
                }
                for c in self.constraints
            ],
            "quantity": self.quantity,
            "ranking_field": self.ranking_field,
            "ranking_order": self.ranking_order,
            "aggregation_operation": self.aggregation_operation,
            "aggregation_field": self.aggregation_field,
            "procedural_requirements": [
                {
                    "procedure_id": p.procedure_id,
                    "order_index": p.order_index,
                    "action_type": p.action_type,
                    "semantic_target": p.semantic_target,
                    "target_type": p.target_type,
                    "required": p.required,
                    "preconditions": p.preconditions,
                    "postconditions": p.postconditions,
                }
                for p in self.procedural_requirements
            ],
            "ambiguity_state": self.ambiguity_state,
        }

    @classmethod
    def from_task_plan(cls, plan: Any) -> TaskModel:
        if hasattr(plan, "to_task_model"):
            return plan.to_task_model()
        raise TypeError(f"Cannot convert {type(plan)} to TaskModel")
