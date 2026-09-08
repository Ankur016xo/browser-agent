from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
import time

from browser_agent.task_model import TaskModel
from browser_agent.evidence import Evidence


@dataclass(frozen=True)
class GroundedElement:
    element_id: str                         # Unique ID within this observation
    tag: str
    text: str
    role: str
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    observation_id: str                     # Monotonically generated unique ID (e.g. "obs_1")
    timestamp: float = field(default_factory=time.time)
    url: str = ""
    title: str = ""
    dom_hash: str = ""
    visual_hash: str = ""
    elements: tuple[GroundedElement, ...] = field(default_factory=tuple)
    is_blocked: bool = False
    blocker_type: Literal["none", "captcha", "auth", "rate_limit"] = "none"


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    action_type: Literal["navigate", "click", "fill", "press_key", "scroll", "wait", "back"]
    observation_id: str = ""                     # MUST match active Observation.observation_id for grounded actions
    target_element_id: str | None = None    # ID corresponding to GroundedElement in observation
    parameters: dict[str, Any] = field(default_factory=dict)
    semantic_target: str = ""


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    success: bool
    error: str | None = None
    observation_id_after: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class CandidateRecord:
    candidate_id: str
    title: str
    url: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    status: Literal["discovered", "inspected", "rejected"] = "discovered"
    rejection_reason: str | None = None


@dataclass
class ExecutionState:
    task: TaskModel
    current_observation: Observation | None = None
    observation_history: list[str] = field(default_factory=list) # observation_ids
    
    # Procedure Progress
    active_procedure_index: int = 0
    completed_procedures: list[str] = field(default_factory=list)
    failed_procedures: list[str] = field(default_factory=list)
    
    # Candidates & Evidence
    candidates: dict[str, CandidateRecord] = field(default_factory=dict)
    evidence_store: dict[str, Evidence] = field(default_factory=dict)
    
    # Budgets & Strategy Exploration
    steps_taken: int = 0
    step_budget: int = 30
    exploration_budget: int = 20
    candidate_pool_exhausted: bool = False
    search_strategies_exhausted: bool = False
    
    # Stale & Action Safety
    rejected_stale_actions: int = 0
    consecutive_action_failures: int = 0
    action_history: list[ActionSpec] = field(default_factory=list)
    state_version: int = 0
    
    # Authoritative Blocker / Terminal Flags
    blocker_state: Literal["none", "captcha", "auth", "rate_limit", "unrecoverable"] = "none"
    execution_failed: bool = False
    failure_reason: str | None = None
    terminal_state: Literal["unset", "success", "incomplete", "blocked", "failed", "no_match", "needs_clarification"] = "unset"

    def apply_observation(self, obs: Observation) -> None:
        """Sole mutation point for receiving new observation."""
        self.current_observation = obs
        self.observation_history.append(obs.observation_id)
        self.state_version += 1
        if obs.is_blocked:
            self.blocker_state = obs.blocker_type if obs.blocker_type in ("captcha", "auth", "rate_limit") else "unrecoverable"

    def add_candidate(self, cand: CandidateRecord) -> None:
        """Register a candidate record."""
        self.candidates[cand.candidate_id] = cand
        self.state_version += 1

    def add_evidence(self, ev: Evidence) -> None:
        """Sole mutation point for registering evidence."""
        self.evidence_store[ev.evidence_id] = ev
        if ev.candidate_id and ev.candidate_id in self.candidates:
            self.candidates[ev.candidate_id].evidence_ids.append(ev.evidence_id)
        self.state_version += 1

    def record_procedure_result(self, procedure_id: str, success: bool) -> None:
        """Record the outcome of a procedure step."""
        if success:
            if procedure_id not in self.completed_procedures:
                self.completed_procedures.append(procedure_id)
        else:
            if procedure_id not in self.failed_procedures:
                self.failed_procedures.append(procedure_id)
        self.state_version += 1

    def record_action(self, action: ActionSpec) -> None:
        """Record executed action."""
        self.action_history.append(action)
        self.steps_taken += 1
        self.state_version += 1

    def is_duplicate_action(self, action: ActionSpec, cycle_window: int = 3) -> bool:
        """Check if action is a duplicate within recent cycle_window actions."""
        recent = self.action_history[-cycle_window:]
        for prev in recent:
            if (
                prev.action_type == action.action_type
                and prev.target_element_id == action.target_element_id
                and prev.semantic_target == action.semantic_target
                and prev.parameters == action.parameters
            ):
                return True
        return False

    def validate_action_freshness(self, action: ActionSpec | dict[str, Any]) -> bool:
        """Enforce observation identity and grounded element freshness contract.
        
        Contract:
        1. Safe non-grounded actions ('navigate', 'wait', 'back'):
           - Operate on browser window / URL navigation / history / timing directly.
           - Do not require a current observation to be initiated (e.g. initial URL navigation
             before first observation exists).
           - If an observation_id is explicitly provided and a current observation exists,
             it must not contradict the current observation (it must match).
        2. Grounded actions ('click', 'fill', 'type', 'scroll', 'select', or 'press_key' with target):
           - Depend upon viewport and DOM elements.
           - Require a current observation; if no observation exists, returns False.
           - Require a non-empty observation_id; missing observation_id is rejected.
           - observation_id MUST match self.current_observation.observation_id; mismatch is rejected.
           - If target_element_id is specified, element MUST exist in current observation.
        """
        # Support both ActionSpec dataclass and dict action representations
        if isinstance(action, dict):
            action_type = str(action.get("action_type") or action.get("action") or "").lower()
            obs_id = action.get("observation_id")
            target_id = action.get("target_element_id") or action.get("element_id")
        else:
            action_type = str(action.action_type).lower()
            obs_id = action.observation_id
            target_id = action.target_element_id

        # Normalize action_type synonyms
        if action_type == "type":
            action_type = "fill"

        grounded_actions = {"click", "fill", "scroll", "select"}
        is_grounded = action_type in grounded_actions or (action_type == "press_key" and target_id is not None)

        if not is_grounded:
            # Safe non-grounded action (e.g. navigate, wait, back)
            if self.current_observation is None:
                return True
            if obs_id and obs_id != self.current_observation.observation_id:
                self.rejected_stale_actions += 1
                return False
            return True

        # Grounded action checks
        if self.current_observation is None:
            # Cannot execute grounded action without an active observation
            return False

        if not obs_id:
            # Missing observation_id on grounded action is strictly rejected
            self.rejected_stale_actions += 1
            return False

        if obs_id != self.current_observation.observation_id:
            # Stale observation_id
            self.rejected_stale_actions += 1
            return False

        if target_id is not None and self.current_observation.elements:
            match = any(str(e.element_id) == str(target_id) for e in self.current_observation.elements)
            if not match:
                self.rejected_stale_actions += 1
                return False

        return True

