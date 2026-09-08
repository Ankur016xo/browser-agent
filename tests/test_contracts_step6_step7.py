"""Tests verifying Step 6 (Stale Action Contract) and Step 7 (Centralized Terminal State Resolution)."""
import pytest
from browser_agent.task_model import TaskModel, ConstraintSpec
from browser_agent.execution_state import (
    ExecutionState,
    Observation,
    GroundedElement,
    ActionSpec,
    CandidateRecord,
)
from browser_agent.evidence import Evidence
from browser_agent.verifier import (
    IndependentVerifier,
    resolve_terminal_state,
)


class TestStep6StaleActionContract:
    """Validate all 5 aspects of Step 6 Stale Action Contract."""

    def test_1_matching_observation_id_allowed(self):
        """Action with matching observation_id and existing element is allowed."""
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes")
        state = ExecutionState(task=task)
        obs = Observation(
            observation_id="obs_100",
            elements=(GroundedElement(element_id="elem_1", tag="button", text="Buy", role="button"),),
        )
        state.apply_observation(obs)

        action = ActionSpec(
            action_id="act_1",
            action_type="click",
            observation_id="obs_100",
            target_element_id="elem_1",
        )
        assert state.validate_action_freshness(action) is True

    def test_2_stale_observation_id_rejected(self):
        """Action referencing an older observation_id is rejected."""
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes")
        state = ExecutionState(task=task)
        obs1 = Observation(observation_id="obs_old")
        state.apply_observation(obs1)
        obs2 = Observation(observation_id="obs_new")
        state.apply_observation(obs2)

        action = ActionSpec(
            action_id="act_2",
            action_type="click",
            observation_id="obs_old",
            target_element_id=None,
        )
        assert state.validate_action_freshness(action) is False
        assert state.rejected_stale_actions == 1

    def test_3_missing_observation_id_on_grounded_action_rejected(self):
        """Grounded action (click, fill, scroll, select) with empty/missing observation_id is rejected."""
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes")
        state = ExecutionState(task=task)
        obs = Observation(
            observation_id="obs_current",
            elements=(GroundedElement(element_id="btn_submit", tag="button", text="Submit", role="button"),),
        )
        state.apply_observation(obs)

        # Dataclass missing obs_id (default empty "")
        action_spec = ActionSpec(
            action_id="act_grounded_no_obs",
            action_type="click",
            observation_id="",
            target_element_id="btn_submit",
        )
        assert state.validate_action_freshness(action_spec) is False

        # Dict without observation_id
        action_dict = {
            "action": "click",
            "element_id": "btn_submit",
        }
        assert state.validate_action_freshness(action_dict) is False

        # Dict with fill without observation_id
        fill_dict = {
            "action": "type",
            "element_id": "input_search",
            "text": "test",
        }
        assert state.validate_action_freshness(fill_dict) is False

    def test_4_no_current_observation_behavior(self):
        """When no observation has occurred yet: grounded actions fail, safe non-grounded pass."""
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes")
        state = ExecutionState(task=task)
        assert state.current_observation is None

        grounded_act = ActionSpec(action_id="act_g", action_type="click", observation_id="any")
        assert state.validate_action_freshness(grounded_act) is False

        safe_act = ActionSpec(action_id="act_safe", action_type="navigate", parameters={"url": "https://example.com"})
        assert state.validate_action_freshness(safe_act) is True

    def test_5_navigation_action_explicit_policy(self):
        """Navigation and non-grounded safe actions do not require an active observation, but if obs_id is given it must match."""
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes")
        state = ExecutionState(task=task)
        obs = Observation(observation_id="obs_5")
        state.apply_observation(obs)

        # Navigate without observation_id is allowed
        nav_no_obs = {"action": "navigate", "url": "https://wikipedia.org"}
        assert state.validate_action_freshness(nav_no_obs) is True

        # Wait without observation_id is allowed
        wait_act = {"action": "wait", "seconds": 2}
        assert state.validate_action_freshness(wait_act) is True

        # Navigate with matching observation_id is allowed
        nav_matching = {"action": "navigate", "observation_id": "obs_5", "url": "https://wikipedia.org"}
        assert state.validate_action_freshness(nav_matching) is True

        # Navigate with contradictory stale observation_id is rejected
        nav_stale = {"action": "navigate", "observation_id": "obs_stale", "url": "https://wikipedia.org"}
        assert state.validate_action_freshness(nav_stale) is False


class TestStep7CentralizedTerminalStateResolution:
    """Validate precedence order: BLOCKED / FAILED > NEEDS_CLARIFICATION > INCOMPLETE > SUCCESS > NO_MATCH > UNSET."""

    def test_blocked_beats_everything(self):
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes", quantity=1)
        state = ExecutionState(task=task, blocker_state="captcha")
        cand = CandidateRecord("c1", "Shoe", evidence_ids=["ev1"])
        state.add_candidate(cand)
        state.add_evidence(Evidence(
            evidence_id="ev1", candidate_id="c1", field="price",
            raw_value="100", normalized_value=100.0, source="dom",
            confidence=1.0, page_url="https://example.com"
        ))
        terminal_state, res = resolve_terminal_state(state)
        assert terminal_state == "BLOCKED"
        assert res.verified is False

    def test_failed_beats_everything(self):
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes")
        state = ExecutionState(task=task, execution_failed=True, failure_reason="Fatal browser crash")
        terminal_state, res = resolve_terminal_state(state)
        assert terminal_state == "FAILED"
        assert res.verified is False

    def test_needs_clarification_beats_incomplete_and_success(self):
        task = TaskModel(raw_task="find shoes", intent="search", target_entity="shoes", ambiguity_state="needs_clarification")
        state = ExecutionState(task=task)
        terminal_state, res = resolve_terminal_state(state)
        assert terminal_state == "NEEDS_CLARIFICATION"
        assert res.verified is False

    def test_incomplete_beats_success(self):
        """When candidate count is insufficient, result is INCOMPLETE, not SUCCESS."""
        task = TaskModel(raw_task="find 3 shoes", intent="search", target_entity="shoes", quantity=3)
        state = ExecutionState(task=task)
        # Only 2 candidates provided
        for i in (1, 2):
            cid = f"c{i}"
            evid = f"ev{i}"
            state.add_candidate(CandidateRecord(cid, f"Shoe {i}", evidence_ids=[evid]))
            state.add_evidence(Evidence(
                evidence_id=evid, candidate_id=cid, field="price",
                raw_value="500", normalized_value=500.0, source="dom",
                confidence=1.0, page_url="https://example.com"
            ))
        terminal_state, res = resolve_terminal_state(state)
        assert terminal_state == "INCOMPLETE"
        assert res.verified is False

    def test_success_when_all_invariants_satisfied(self):
        """SUCCESS is only emitted when all criteria pass."""
        task = TaskModel(raw_task="find 1 shoe", intent="search", target_entity="shoes", quantity=1)
        state = ExecutionState(task=task)
        state.add_candidate(CandidateRecord("c1", "Shoe 1", evidence_ids=["ev1"]))
        state.add_evidence(Evidence(
            evidence_id="ev1", candidate_id="c1", field="price",
            raw_value="500", normalized_value=500.0, source="dom",
            confidence=1.0, page_url="https://example.com"
        ))
        terminal_state, res = resolve_terminal_state(state)
        assert terminal_state == "SUCCESS"
        assert res.verified is True
        assert res.is_complete is True

    def test_no_match_only_when_search_and_pool_exhausted(self):
        """NO_MATCH is emitted only when candidate pool and search strategies are exhausted."""
        task = TaskModel(raw_task="impossible product", intent="search", target_entity="laptop", quantity=1)
        state = ExecutionState(task=task)
        state.search_strategies_exhausted = True
        state.candidate_pool_exhausted = True
        terminal_state, res = resolve_terminal_state(state)
        assert terminal_state == "NO_MATCH"
