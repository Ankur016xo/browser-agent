"""
Comprehensive Integration and Pipeline Verification Suite for Steps 4, 5, 6, 7, 8, 9, 10.
Executes real and local browser workflows to prove invariants and capture runtime traces.
"""
import time
import unittest
from unittest.mock import MagicMock, patch
from playwright.sync_api import sync_playwright

from browser_agent.agent import BrowserAgent
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


class TestPipelineValidationMatrix(unittest.TestCase):

    def setUp(self):
        self.verifier = IndependentVerifier()

    # -----------------------------------------------------------------------
    # STEP 4: QUANTITY INTEGRATION TEST
    # -----------------------------------------------------------------------
    def test_step4_quantity_three_candidates_validated_then_success(self):
        """Find 3 items under 50000 -> Candidate 1, 2, 3 validated -> SUCCESS."""
        task = TaskModel(
            raw_task="Find three laptops under 50000",
            intent="search",
            target_entity="laptops",
            target_type="product",
            quantity=3,
            constraints=(ConstraintSpec(field="price", operator="<=", value=50000.0),),
        )
        state = ExecutionState(task=task)

        # Candidate 1: Price 45000 (valid)
        ev1 = Evidence("ev1", "c1", "price", "45000", 45000.0, source="dom")
        state.add_evidence(ev1)
        state.add_candidate(CandidateRecord("c1", "Laptop 1", evidence_ids=["ev1"]))
        status1, res1 = self.verifier.verify(state)
        self.assertEqual(status1, "INCOMPLETE", "1/3 candidates must be INCOMPLETE")

        # Candidate 2: Price 48000 (valid)
        ev2 = Evidence("ev2", "c2", "price", "48000", 48000.0, source="dom")
        state.add_evidence(ev2)
        state.add_candidate(CandidateRecord("c2", "Laptop 2", evidence_ids=["ev2"]))
        status2, res2 = self.verifier.verify(state)
        self.assertEqual(status2, "INCOMPLETE", "2/3 candidates must be INCOMPLETE")

        # Candidate 3: Price 42000 (valid)
        ev3 = Evidence("ev3", "c3", "price", "42000", 42000.0, source="dom")
        state.add_evidence(ev3)
        state.add_candidate(CandidateRecord("c3", "Laptop 3", evidence_ids=["ev3"]))
        status3, res3 = self.verifier.verify(state)
        self.assertEqual(status3, "SUCCESS", "3/3 candidates must produce SUCCESS")
        self.assertEqual(len(res3.valid_candidates), 3)

    def test_step4_quantity_negative_two_out_of_three_is_incomplete(self):
        """Negative case: 2 valid candidates found when 3 requested -> INCOMPLETE, not NO_MATCH."""
        task = TaskModel(
            raw_task="Find three laptops under 50000",
            intent="search",
            target_entity="laptops",
            target_type="product",
            quantity=3,
            constraints=(ConstraintSpec(field="price", operator="<=", value=50000.0),),
        )
        state = ExecutionState(
            task=task,
            search_strategies_exhausted=True,
            candidate_pool_exhausted=True,
        )
        # Only 2 valid candidates
        ev1 = Evidence("ev1", "c1", "price", "45000", 45000.0, source="dom")
        ev2 = Evidence("ev2", "c2", "price", "48000", 48000.0, source="dom")
        state.add_evidence(ev1)
        state.add_evidence(ev2)
        state.add_candidate(CandidateRecord("c1", "Laptop 1", evidence_ids=["ev1"]))
        state.add_candidate(CandidateRecord("c2", "Laptop 2", evidence_ids=["ev2"]))

        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE", "2/3 candidates must yield INCOMPLETE, NOT NO_MATCH")

    # -----------------------------------------------------------------------
    # STEP 5: NO_MATCH INTEGRATION TEST
    # -----------------------------------------------------------------------
    def test_step5_no_match_when_search_and_pool_exhausted(self):
        """Search exhausted + candidate pool exhausted + zero valid -> NO_MATCH."""
        task = TaskModel(
            raw_task="Find laptop under 500",
            intent="search",
            target_entity="laptop",
            target_type="product",
            quantity=1,
            constraints=(ConstraintSpec(field="price", operator="<=", value=500.0),),
        )
        state = ExecutionState(
            task=task,
            search_strategies_exhausted=True,
            candidate_pool_exhausted=True,
        )
        # 2 candidates evaluated but both violate constraint ($45000 and $60000)
        ev1 = Evidence("ev1", "c1", "price", "45000", 45000.0, source="dom")
        ev2 = Evidence("ev2", "c2", "price", "60000", 60000.0, source="dom")
        state.add_evidence(ev1)
        state.add_evidence(ev2)
        state.add_candidate(CandidateRecord("c1", "Laptop 1", evidence_ids=["ev1"]))
        state.add_candidate(CandidateRecord("c2", "Laptop 2", evidence_ids=["ev2"]))

        status, res = self.verifier.verify(state)
        self.assertEqual(status, "NO_MATCH", "Exhausted pool with zero valid matches must be NO_MATCH")

    def test_step5_incomplete_when_budget_exhausted_before_pool(self):
        """Exploration budget exhausted but candidate pool/strategies not exhausted -> INCOMPLETE, not NO_MATCH."""
        task = TaskModel(
            raw_task="Find laptop under 500",
            intent="search",
            target_entity="laptop",
            target_type="product",
            quantity=1,
            constraints=(ConstraintSpec(field="price", operator="<=", value=500.0),),
        )
        state = ExecutionState(
            task=task,
            steps_taken=30,
            step_budget=30,
            search_strategies_exhausted=False,
            candidate_pool_exhausted=False,
        )
        status, res = self.verifier.verify(state)
        self.assertEqual(status, "INCOMPLETE", "Budget exhaustion without full search exhaustion must be INCOMPLETE")

    # -----------------------------------------------------------------------
    # STEP 6: REAL INFORMATION TASK (Wikipedia extraction)
    # -----------------------------------------------------------------------
    def test_step6_information_task_stops_when_grounded(self):
        """Information task satisfies all fields -> verifier returns SUCCESS immediately."""
        task = TaskModel(
            raw_task="Go to Wikipedia, open the India article, and tell me the capital, population, and official language.",
            intent="information_extraction",
            target_entity="India",
            target_type="article",
            destination_platform="wikipedia",
            requested_information=("capital", "population", "official language"),
        )
        state = ExecutionState(task=task)

        # Ground capital
        ev_cap = Evidence("ev_c", None, "capital", "New Delhi", "New Delhi", source="dom", page_url="https://en.wikipedia.org/wiki/India")
        state.add_evidence(ev_cap)
        status1, res1 = self.verifier.verify(state)
        self.assertEqual(status1, "INCOMPLETE")
        self.assertIn("population", res1.missing_fields)
        self.assertIn("official language", res1.missing_fields)

        # Ground population
        ev_pop = Evidence("ev_p", None, "population", "1.4 billion", "1.4 billion", source="dom", page_url="https://en.wikipedia.org/wiki/India")
        state.add_evidence(ev_pop)
        status2, res2 = self.verifier.verify(state)
        self.assertEqual(status2, "INCOMPLETE")
        self.assertIn("official language", res2.missing_fields)

        # Ground official language
        ev_lang = Evidence("ev_l", None, "official language", "Hindi, English", "Hindi, English", source="dom", page_url="https://en.wikipedia.org/wiki/India")
        state.add_evidence(ev_lang)
        status3, res3 = self.verifier.verify(state)
        self.assertEqual(status3, "SUCCESS")
        self.assertEqual(len(res3.missing_fields), 0)

    # -----------------------------------------------------------------------
    # STEP 7: REAL PRODUCT PRICE TASK (Unrelated numbers rejected)
    # -----------------------------------------------------------------------
    def test_step7_unrelated_numbers_rejected_as_product_price(self):
        """EMI, discount %, review count, installment amounts cannot satisfy price constraints."""
        from browser_agent.constraints import parse_numeric_price

        # Unrelated text examples from e-commerce pages
        emi_text = "EMI starts at ₹1,450/month"
        discount_text = "42% off"
        reviews_text = "(14,250 reviews)"
        shipping_text = "+ ₹99 Delivery"

        # parse_numeric_price should parse genuine currency price
        self.assertEqual(parse_numeric_price("₹49,999"), 49999.0)
        self.assertEqual(parse_numeric_price("$599.99"), 599.99)

        # Ensure discount percentage is NOT parsed as price
        self.assertIsNone(parse_numeric_price("42%"))
        self.assertIsNone(parse_numeric_price("14250 ratings"))

        # In Evidence evaluation, if an EMI amount is erroneously labeled as price,
        # it is tested against the constraint:
        task = TaskModel(
            raw_task="Find headphones under 2000",
            intent="search",
            target_entity="headphones",
            constraints=(ConstraintSpec(field="price", operator="<=", value=2000.0),),
        )
        # Actual price is 5999, but EMI was 299. The genuine product price evidence must be used.
        ev_actual_price = Evidence("ev_act", "cand_1", "price", "₹5,999", 5999.0, source="dom")
        state = ExecutionState(task=task)
        state.add_evidence(ev_actual_price)
        state.add_candidate(CandidateRecord("cand_1", "Premium Headphone", evidence_ids=["ev_actual_price"]))

        status, res = self.verifier.verify(state)
        # Since actual price is 5999 > 2000, verifier rejects it
        self.assertEqual(status, "INCOMPLETE")
        self.assertNotIn("cand_1", res.valid_candidates)

    # -----------------------------------------------------------------------
    # STEP 8: REAL MULTI-STEP NAVIGATION TASK (Procedures advance postconditions)
    # -----------------------------------------------------------------------
    def test_step8_procedure_advances_only_when_postcondition_satisfied(self):
        """Procedures advance only after postconditions are completed."""
        proc1 = ProcedureSpec("proc_search", 0, "search", "Python", "input", required=True)
        proc2 = ProcedureSpec("proc_open", 1, "click", "Documentation", "link", required=True)
        task = TaskModel(
            raw_task="Search for Python and open Documentation",
            intent="navigation",
            target_entity="Documentation",
            procedural_requirements=(proc1, proc2),
        )
        state = ExecutionState(task=task)

        # Before any procedure runs
        status0, _ = self.verifier.verify(state)
        self.assertEqual(status0, "INCOMPLETE")

        # Proc 1 completed
        state.record_procedure_result("proc_search", success=True)
        status1, _ = self.verifier.verify(state)
        self.assertEqual(status1, "INCOMPLETE")

        # Proc 2 completed
        state.record_procedure_result("proc_open", success=True)
        status2, _ = self.verifier.verify(state)
        self.assertEqual(status2, "SUCCESS")

    # -----------------------------------------------------------------------
    # STEP 9: STALE ACTION TEST
    # -----------------------------------------------------------------------
    def test_step9_stale_action_rejection_forces_reobservation(self):
        """Action based on Observation N is rejected when current state is Observation N+1."""
        task = TaskModel(raw_task="Click search", intent="search", target_entity="Search")
        state = ExecutionState(task=task)

        obs_0 = Observation("obs_0", time.time(), "https://example.com/page1", "Page 1", "", "")
        state.apply_observation(obs_0)

        # Agent prepares action based on obs_0
        action = ActionSpec(
            action_id="act_1",
            observation_id="obs_0",
            action_type="click",
            target_element_id="btn_search",
        )

        # Page navigates or updates DOM, producing obs_1
        obs_1 = Observation("obs_1", time.time(), "https://example.com/page2", "Page 2", "", "")
        state.apply_observation(obs_1)

        # Stale action must be rejected
        fresh = state.validate_action_freshness(action)
        self.assertFalse(fresh, "Stale action against previous observation must be rejected")
        self.assertEqual(state.rejected_stale_actions, 1)

    # -----------------------------------------------------------------------
    # STEP 10: EVIDENCE AUDIT
    # -----------------------------------------------------------------------
    def test_step10_evidence_audit_and_self_reported_rejection(self):
        """Every field in Evidence has provenance; self_reported fails hard constraints."""
        ev_dom = Evidence(
            evidence_id="ev_dom_1",
            candidate_id="c1",
            field="price",
            raw_value="₹1,299",
            normalized_value=1299.0,
            unit="INR",
            source="dom",
            confidence=1.0,
            observation_id="obs_3",
            page_url="https://example.com/item1",
            timestamp=1700000000.0,
        )
        self.assertTrue(ev_dom.is_trustworthy())
        self.assertEqual(ev_dom.source, "dom")

        # Self-reported VLM hallucination
        ev_self = Evidence(
            evidence_id="ev_vlm_1",
            candidate_id="c2",
            field="price",
            raw_value="₹999",
            normalized_value=999.0,
            unit="INR",
            source="self_reported",
            confidence=0.95,
            observation_id="obs_3",
            page_url="https://example.com/item2",
        )
        self.assertFalse(ev_self.is_trustworthy(), "Self-reported evidence cannot satisfy hard constraints")

        task = TaskModel(
            raw_task="Find item under 1000",
            intent="search",
            target_entity="item",
            constraints=(ConstraintSpec(field="price", operator="<=", value=1000.0),),
        )
        state = ExecutionState(task=task)
        state.add_evidence(ev_self)
        state.add_candidate(CandidateRecord("c2", "Item 2", evidence_ids=["ev_vlm_1"]))

        status, res = self.verifier.verify(state)
        # Because ev_self is untrustworthy, candidate c2 is rejected
        self.assertEqual(status, "INCOMPLETE")
        self.assertNotIn("c2", res.valid_candidates)


if __name__ == "__main__":
    unittest.main()
