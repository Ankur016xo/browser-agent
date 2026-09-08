from __future__ import annotations

from typing import Any
from browser_agent.task_model import TaskModel


class TaskPlanAdapter:
    """Read-only compatibility adapter wrapping TaskModel as legacy TaskPlan.
    
    Ensures backward compatibility for CLI, UI, and dashboard without
    maintaining multiple competing parsers or re-parsing text.
    """
    def __init__(self, model: TaskModel):
        self._model = model

    @property
    def raw_task(self) -> str:
        return self._model.raw_task

    @property
    def destination(self) -> str:
        return self._model.destination_platform or ""

    @property
    def destination_url(self) -> str | None:
        return self._model.destination_url

    @property
    def target(self) -> str:
        return self._model.target_entity

    @property
    def target_type(self) -> str:
        return self._model.target_type

    @property
    def search_query(self) -> str:
        return self._model.search_query

    @property
    def intent(self) -> str:
        return self._model.intent

    @property
    def task_type(self) -> str:
        return self._model.intent

    @property
    def requested_information(self) -> list[str]:
        return list(self._model.requested_information)

    @property
    def quantity(self) -> int:
        return self._model.quantity or 1

    @property
    def ranking_field(self) -> str | None:
        return self._model.ranking_field

    @property
    def ranking_order(self) -> str:
        return self._model.ranking_order or "desc"

    @property
    def constraints(self) -> list[dict[str, Any]]:
        return [
            {
                "field": c.field,
                "operator": c.operator,
                "value": c.value,
                "unit": c.unit,
                "required": c.required,
            }
            for c in self._model.constraints
        ]

    def summary(self) -> str:
        return (
            f"destination='{self.destination}', target='{self.target}', "
            f"query='{self.search_query}', intent='{self.intent}'"
        )
