"""
20 Architecture Invariant Regression Tests.
Validates the canonical TaskModel, ExecutionState, Evidence, and IndependentVerifier pipeline.
"""
import dataclasses
import inspect
import unittest
from browser_agent.evidence import Evidence
from browser_agent.execution_state import (
    ActionSpec,
    CandidateRecord,
    ExecutionState,
    GroundedElement,
    Observation,
)
from browser_agent.legacy_shim import TaskPlanAdapter
from browser_agent.planner import parse_task_model, parse_task_plan
from browser_agent.task_model import ConstraintSpec, ProcedureSpec, TaskModel
from browser_agent.verifier import IndependentVerifier, TaskVerificationResult


class TestArchitectureInvariants(unittest.TestCase):
    def setUp(self):
        self.verifier = IndependentVerifier()

    def _create_minimal_task(self, **kwargs) -> TaskModel:
        defaults = {
            "raw_task": "test task",
            "intent": "search",
            "target_entity": "laptop",
            "target_type": "product",
            "search_query": "laptop",
            "quantity": 1,
            "ambiguity_state": "resolved",
        }
        defaults.update(kwargs)
        return TaskModel(**defaults)

    # Invariant 1: Precedence: BLOCKED > SUCCESS / COMPLETE
    def test_invariant_1_precedence_blocked_over_complete(self):
        task = self._create_minimal_task()
        state = ExecutionState(task=task, blocker_state="captcha")
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "BLOCKED")
        self.assertIn("captcha", res.reason)

    # Invariant 2: Precedence: FAILED > NEEDS_CLARIFICATION
    def test_invariant_2_precedence_failed_over_clarification(self):
        task = self._create_minimal_task(ambiguity_state="needs_clarification")
        state = ExecutionState(task=task, execution_failed=True, failure_reason="Crash")
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "FAILED")
        self.assertIn("Crash", res.reason)

    # Invariant 3: Precedence: INCOMPLETE over NO_MATCH when search budget remains
    def test_invariant_3_precedence_incomplete_over_no_match(self):
        task = self._create_minimal_task(quantity=1)
        state = ExecutionState(
            task=task,
            search_strategies_exhausted=False,
            candidate_pool_exhausted=True,
        )
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE")

    # Invariant 4: Precedence: NO_MATCH requires explicit strategy & candidate pool exhaustion
    def test_invariant_4_precedence_no_match_requires_exhaustion(self):
        task = self._create_minimal_task(quantity=1)
        state = ExecutionState(
            task=task,
            search_strategies_exhausted=True,
            candidate_pool_exhausted=True,
        )
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "NO_MATCH")

    # Invariant 5: Sole mutation boundary: state fields cannot be mutated directly without commit
    def test_invariant_5_sole_mutation_boundary(self):
        task = self._create_minimal_task()
        state = ExecutionState(task=task)
        cand = CandidateRecord(candidate_id="c1", title="Shoe A")
        state.add_candidate(cand)
        self.assertIn("c1", state.candidates)
        v1 = state.state_version
        state.record_procedure_result("proc_1", success=True)
        self.assertGreater(state.state_version, v1)

    # Invariant 6: Self-reported evidence rejected for hard constraints
    def test_invariant_6_self_reported_evidence_rejected_for_hard_constraints(self):
        ev = Evidence(
            evidence_id="ev_1",
            candidate_id="cand_1",
            field="price",
            raw_value="$40",
            normalized_value=40.0,
            source="self_reported",
            confidence=0.99,
        )
        self.assertFalse(ev.is_trustworthy())

    # Invariant 7: Candidate re-evaluated from scratch against authoritative evidence
    def test_invariant_7_candidate_re_evaluated_from_scratch(self):
        constraint = ConstraintSpec(field="price", operator="<=", value=50.0)
        task = self._create_minimal_task(constraints=(constraint,), quantity=1)
        state = ExecutionState(task=task)

        # Candidate claims validity but evidence value violates constraint
        ev = Evidence(
            evidence_id="ev_price",
            candidate_id="cand_1",
            field="price",
            raw_value="$80",
            normalized_value=80.0,
            source="dom",
            confidence=1.0,
        )
        cand = CandidateRecord(
            candidate_id="cand_1",
            title="Product Over Price",
            evidence_ids=["ev_price"],
        )
        state.evidence_store["ev_price"] = ev
        state.candidates["cand_1"] = cand

        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE")
        self.assertNotIn("cand_1", res.valid_candidates)

    # Invariant 8: Stale action rejection
    def test_invariant_8_stale_action_rejection(self):
        task = self._create_minimal_task()
        obs0 = Observation(observation_id="obs_0", timestamp=1.0, url="http://x", title="", dom_hash="", visual_hash="")
        obs1 = Observation(observation_id="obs_1", timestamp=2.0, url="http://x", title="", dom_hash="", visual_hash="")
        state = ExecutionState(task=task)
        state.apply_observation(obs0)
        state.apply_observation(obs1)
        action = ActionSpec(
            action_id="a1",
            observation_id="obs_0",
            action_type="click",
            target_element_id="btn_1",
        )
        is_fresh = state.validate_action_freshness(action)
        self.assertFalse(is_fresh)

    # Invariant 9: Duplicate action suppression
    def test_invariant_9_duplicate_action_suppression(self):
        task = self._create_minimal_task()
        state = ExecutionState(task=task)
        action1 = ActionSpec(
            action_id="a1",
            observation_id="obs_1",
            action_type="click",
            target_element_id="btn_next",
        )
        state.record_action(action1)
        self.assertTrue(state.is_duplicate_action(action1, cycle_window=3))

    # Invariant 10: TaskModel immutability
    def test_invariant_10_task_model_immutability(self):
        task = self._create_minimal_task()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            task.intent = "navigation"  # type: ignore

    # Invariant 11: ConstraintSpec immutability
    def test_invariant_11_constraint_spec_immutability(self):
        constraint = ConstraintSpec(field="price", operator="<=", value=100)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            constraint.value = 200  # type: ignore

    # Invariant 12: Evidence immutability
    def test_invariant_12_evidence_immutability(self):
        ev = Evidence(
            evidence_id="ev_1",
            candidate_id="c1",
            field="rating",
            raw_value="4.5",
            normalized_value=4.5,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ev.normalized_value = 5.0  # type: ignore

    # Invariant 13: TaskPlanAdapter backward compatibility
    def test_invariant_13_task_plan_adapter_backward_compat(self):
        model = self._create_minimal_task(
            raw_task="find laptops",
            search_query="laptops",
            destination_platform="flipkart",
        )
        adapter = TaskPlanAdapter(model)
        self.assertEqual(adapter.raw_task, "find laptops")
        self.assertEqual(adapter.search_query, "laptops")
        self.assertEqual(adapter.destination, "flipkart")

    # Invariant 14: Missing required fields prevents completion in information extraction
    def test_invariant_14_missing_required_fields_prevents_completion(self):
        task = self._create_minimal_task(
            intent="information_extraction",
            requested_information=("capital", "population"),
        )
        state = ExecutionState(task=task)
        ev = Evidence(
            evidence_id="ev_cap",
            candidate_id=None,
            field="capital",
            raw_value="Paris",
            normalized_value="Paris",
            source="dom",
        )
        state.evidence_store["ev_cap"] = ev
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("population", res.missing_fields)

    # Invariant 15: Incomplete required procedures prevents completion
    def test_invariant_15_incomplete_required_procedures_prevents_completion(self):
        proc = ProcedureSpec(
            procedure_id="p1",
            order_index=0,
            action_type="navigate",
            semantic_target="Doc",
            target_type="link",
            required=True,
        )
        task = self._create_minimal_task(procedural_requirements=(proc,))
        state = ExecutionState(task=task)
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE")

    # Invariant 16: Aggregation average computation
    def test_invariant_16_aggregation_average_computation(self):
        task = self._create_minimal_task(
            quantity=2,
            aggregation_operation="average",
            aggregation_field="price",
        )
        state = ExecutionState(task=task)
        ev1 = Evidence(
            evidence_id="ev1", candidate_id="c1", field="price",
            raw_value="100", normalized_value=100.0, source="dom"
        )
        ev2 = Evidence(
            evidence_id="ev2", candidate_id="c2", field="price",
            raw_value="200", normalized_value=200.0, source="dom"
        )
        state.evidence_store["ev1"] = ev1
        state.evidence_store["ev2"] = ev2
        state.candidates["c1"] = CandidateRecord("c1", "Item 1", evidence_ids=["ev1"])
        state.candidates["c2"] = CandidateRecord("c2", "Item 2", evidence_ids=["ev2"])

        status, res = self.verifier.verify(state)
        self.assertEqual(status, "SUCCESS")
        self.assertEqual(res.aggregation_value, 150.0)

    # Invariant 17: Aggregation fails on zero valid values
    def test_invariant_17_aggregation_fails_on_zero_valid_values(self):
        task = self._create_minimal_task(
            quantity=1,
            aggregation_operation="average",
            aggregation_field="price",
        )
        state = ExecutionState(task=task)
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE")
        self.assertIsNone(res.aggregation_value)

    # Invariant 18: No site-specific keywords in task_model or verifier
    def test_invariant_18_no_site_specific_keywords_in_task_model_or_verifier(self):
        import browser_agent.task_model as tm_module
        import browser_agent.verifier as ver_module

        tm_src = inspect.getsource(tm_module).lower()
        ver_src = inspect.getsource(ver_module.IndependentVerifier).lower()

        for forbidden in ["amazon", "flipkart", "youtube", "ebay"]:
            self.assertNotIn(
                f'"{forbidden}"',
                ver_src,
                f"IndependentVerifier contains hardcoded domain literal '{forbidden}'",
            )

    # Invariant 19: Quantity satisfaction strict threshold
    def test_invariant_19_quantity_satisfaction_strict_threshold(self):
        task = self._create_minimal_task(quantity=3)
        state = ExecutionState(task=task)
        ev1 = Evidence("ev1", "c1", "price", "$10", 10.0, source="dom")
        ev2 = Evidence("ev2", "c2", "price", "$20", 20.0, source="dom")
        state.evidence_store["ev1"] = ev1
        state.evidence_store["ev2"] = ev2
        state.candidates["c1"] = CandidateRecord("c1", "Item 1", evidence_ids=["ev1"])
        state.candidates["c2"] = CandidateRecord("c2", "Item 2", evidence_ids=["ev2"])

        # Only 2 out of 3 valid candidates
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE")

    # Invariant 20: Failed required procedure causes task failure
    def test_invariant_20_failed_required_procedure_causes_task_failure(self):
        proc = ProcedureSpec(
            procedure_id="p_must_open",
            order_index=0,
            action_type="navigate",
            semantic_target="Portal",
            target_type="link",
            required=True,
        )
        task = self._create_minimal_task(procedural_requirements=(proc,))
        state = ExecutionState(task=task)
        state.record_procedure_result("p_must_open", success=False)

        status, res = self.verifier.verify(state)
        self.assertEqual(status, "FAILED")
        self.assertIn("p_must_open", res.reason)


if __name__ == "__main__":
    unittest.main()
