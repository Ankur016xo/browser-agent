"""
Exhaustive Adversarial Validation Suite for Browser Agent.
Stress tests the browser agent backend across all 9 validation vectors:
1. Natural-Language Planning Stress Test (12 variations)
2. Target-Page Boundary Tests (portal, search results, subtopics vs primary)
3. Information Extraction & Missing Evidence (extraction + negative extraction)
4. Ranked Search Tests (direction, field, constrained ranking)
5. Constraint Combination Tests (multi-constraint, ANC strictness, impossible bounds)
6. Procedural State-Machine Tests (deep ordering, go_back tracking, blocking premature done)
7. Recovery Tests (oscillation detection, loop breaking)
8. Negative Tests & Zero False Positives
9. Hardcoding Audit (programmatic integrity check)
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from browser_agent.constraints import (
    TaskConstraints,
    check_feature_present,
    evaluate_candidate,
    extract_task_constraints,
    parse_numeric_price,
    parse_numeric_rating,
    pick_best_ranked_candidate,
)
from browser_agent.exploration import (
    choose_goal_exploration_action,
    find_matching_target_link,
    inspect_page_for_requested_info,
)
from browser_agent.loop_detector import LoopDetector, actions_equivalent
from browser_agent.planner import TaskPlan, parse_task_plan
from browser_agent.state import ActionRecord, AgentMemory, ElementInfo, PageState


class TestVector1NaturalLanguagePlanning(unittest.TestCase):
    """Vector 1: Stress test natural-language task decomposition across 12 distinct variations."""

    def test_all_12_nl_variations(self):
        queries = [
            ("Go to Wikipedia and find the capital of India.", "wikipedia", "India", "capital", "India"),
            ("Find India's capital on Wikipedia.", "wikipedia", "India", "capital", "India"),
            ("What is the capital of India according to Wikipedia?", "wikipedia", "India", "capital", "India"),
            ("Search Wikipedia for India and tell me its capital.", "wikipedia", "India", "capital", "India"),
            ("Look up India on Wikipedia and report its capital.", "wikipedia", "India", "capital", "India"),
            ("Find the capital city of India.", "", "India", "capital", "India"),
            ("Go to Wikipedia, look up India, and find its population.", "wikipedia", "India", "population", "India"),
            ("What is India's population on Wikipedia?", "wikipedia", "India", "population", "India"),
            ("Search Wikipedia for India and tell me its official language.", "wikipedia", "India", "official language", "India"),
            ("What is the capital of France?", "", "France", "capital", "France"),
            ("What is the population of Japan?", "", "Japan", "population", "Japan"),
            ("What is the official language of Germany?", "", "Germany", "official language", "Germany"),
        ]

        for q, exp_dest, exp_target, exp_info, exp_search in queries:
            with self.subTest(query=q):
                plan = parse_task_plan(q)
                self.assertEqual(plan.intent, "information_extraction")
                self.assertEqual(plan.destination, exp_dest)
                self.assertEqual(plan.target.lower(), exp_target.lower())
                self.assertIn(exp_info.lower(), [i.lower() for i in plan.requested_information])
                self.assertEqual(plan.search_query.lower(), exp_search.lower())
                # Search query must NOT equal the full raw prompt
                self.assertNotEqual(plan.search_query, q)


class TestVector2TargetPageBoundary(unittest.TestCase):
    """Vector 2: Verify portal rejection, search results rejection, and subtopic rejection."""

    def setUp(self):
        self.memory = AgentMemory()
        self.memory.task = "Go to Wikipedia and find the capital of India."
        self.memory.task_plan = parse_task_plan(self.memory.task)

    def test_wikipedia_homepage_portal_rejected(self):
        page = MagicMock()
        page.url = "https://www.wikipedia.org/"
        page.title.return_value = "Wikipedia"
        page.evaluate.return_value = ""

        sat, reason = self.memory.is_target_page_satisfied(page)
        self.assertFalse(sat)
        self.assertIn("entry portal", reason.lower())

    def test_wikipedia_main_page_rejected(self):
        page = MagicMock()
        page.url = "https://en.wikipedia.org/wiki/Main_Page"
        page.title.return_value = "Wikipedia, the free encyclopedia"
        page.evaluate.return_value = "Main Page"

        sat, reason = self.memory.is_target_page_satisfied(page)
        self.assertFalse(sat)
        self.assertIn("entry portal", reason.lower())

    def test_wikipedia_search_results_rejected(self):
        page = MagicMock()
        page.url = "https://en.wikipedia.org/w/index.php?search=India&title=Special%3ASearch&ns0=1"
        page.title.return_value = "Search results for \"India\" - Wikipedia"
        page.evaluate.return_value = "Search results"

        sat, reason = self.memory.is_target_page_satisfied(page)
        self.assertFalse(sat)
        self.assertIn("search results", reason.lower())

    def test_wikipedia_subtopics_rejected_when_target_is_primary_entity(self):
        subtopics = [
            ("https://en.wikipedia.org/wiki/Languages_of_India", "Languages of India - Wikipedia", "Languages of India"),
            ("https://en.wikipedia.org/wiki/Demographics_of_India", "Demographics of India - Wikipedia", "Demographics of India"),
            ("https://en.wikipedia.org/wiki/History_of_India", "History of India - Wikipedia", "History of India"),
            ("https://en.wikipedia.org/wiki/Geography_of_India", "Geography of India - Wikipedia", "Geography of India"),
            ("https://en.wikipedia.org/wiki/Economy_of_India", "Economy of India - Wikipedia", "Economy of India"),
        ]

        for url, title, h1 in subtopics:
            with self.subTest(subtopic=h1):
                page = MagicMock()
                page.url = url
                page.title.return_value = title
                page.evaluate.return_value = h1

                sat, reason = self.memory.is_target_page_satisfied(page)
                self.assertFalse(sat)
                self.assertIn("sub-topic", reason.lower())

    def test_primary_article_accepted(self):
        page = MagicMock()
        page.url = "https://en.wikipedia.org/wiki/India"
        page.title.return_value = "India - Wikipedia"
        page.evaluate.return_value = "India"

        sat, reason = self.memory.is_target_page_satisfied(page)
        self.assertTrue(sat)
        self.assertIn("matches target", reason.lower())


class TestVector3InformationExtractionAndNegativeEvidence(unittest.TestCase):
    """Vector 3: Grounded information extraction and negative extraction (Atlantis)."""

    def test_positive_extraction_capital_and_population(self):
        page = MagicMock()
        sample_dom = """
        Country: India
        Capital and largest city: New Delhi
        Population: 1,428,627,663 (2023 estimate)
        Official languages: Hindi, English
        """
        page.evaluate.return_value = sample_dom

        extracted = inspect_page_for_requested_info(page, ["capital", "population", "official language"])
        self.assertEqual(extracted.get("capital"), "New Delhi")
        self.assertIn("1,428,627,663", extracted.get("population", ""))

    def test_negative_extraction_atlantis_no_hallucination(self):
        memory = AgentMemory()
        memory.task = "Go to Wikipedia and find the population of Atlantis."
        memory.task_plan = parse_task_plan(memory.task)

        # On an article or search page about Atlantis that has no population infobox
        page = MagicMock()
        page.url = "https://en.wikipedia.org/wiki/Atlantis"
        page.title.return_value = "Atlantis - Wikipedia"
        page.evaluate.return_value = "Atlantis is a fictional island mentioned in Plato's works Timaeus and Critias."

        # DOM inspection finds no population
        extracted = inspect_page_for_requested_info(page, ["population"])
        self.assertNotIn("population", extracted)

        # Memory remains unpopulated
        memory.extracted_data = extracted
        self.assertFalse(memory.is_information_satisfied(memory.task, page=page))


class TestVector4RankedSearchDirectionsAndConstraints(unittest.TestCase):
    """Vector 4: Ranking directions (asc/desc), fields (price/rating), and constrained ranking."""

    def test_ranking_directions(self):
        candidates = [
            {"name": "Laptop A", "numeric_price": 50000.0, "numeric_rating": 4.5, "extracted_data": {"price": "₹50,000", "rating": "4.5"}},
            {"name": "Laptop B", "numeric_price": 30000.0, "numeric_rating": 4.2, "extracted_data": {"price": "₹30,000", "rating": "4.2"}},
            {"name": "Laptop C", "numeric_price": 80000.0, "numeric_rating": 4.8, "extracted_data": {"price": "₹80,000", "rating": "4.8"}},
        ]

        # 1. Cheapest (price ASC)
        best, _ = pick_best_ranked_candidate(candidates, None, rank_field="price", rank_order="asc")
        self.assertEqual(best["name"], "Laptop B")

        # 2. Most expensive (price DESC)
        best, _ = pick_best_ranked_candidate(candidates, None, rank_field="price", rank_order="desc")
        self.assertEqual(best["name"], "Laptop C")

        # 3. Highest rated (rating DESC)
        best, _ = pick_best_ranked_candidate(candidates, None, rank_field="rating", rank_order="desc")
        self.assertEqual(best["name"], "Laptop C")

        # 4. Lowest rated (rating ASC)
        best, _ = pick_best_ranked_candidate(candidates, None, rank_field="rating", rank_order="asc")
        self.assertEqual(best["name"], "Laptop B")

    def test_constrained_ranking_filter_first_then_rank(self):
        """
        Task: 'gaming laptop under ₹60000 with highest rating'
        Candidate A: ₹70,000 with 4.8 rating (VIOLATES constraint)
        Candidate B: ₹55,000 with 4.5 rating (SATISFIES constraint)
        Candidate C: ₹58,000 with 4.2 rating (SATISFIES constraint)
        Candidate A MUST NOT beat Candidate B despite higher rating!
        """
        constraints = extract_task_constraints("Find a gaming laptop under ₹60000 with highest rating")
        self.assertEqual(constraints.max_price, 60000.0)

        candidates = [
            {"name": "Laptop A (Overbudget)", "numeric_price": 70000.0, "numeric_rating": 4.8, "extracted_data": {"price": "₹70,000", "rating": "4.8"}},
            {"name": "Laptop B (Top Valid)", "numeric_price": 55000.0, "numeric_rating": 4.5, "extracted_data": {"price": "₹55,000", "rating": "4.5"}},
            {"name": "Laptop C (Lower Valid)", "numeric_price": 58000.0, "numeric_rating": 4.2, "extracted_data": {"price": "₹58,000", "rating": "4.2"}},
        ]

        best, valid = pick_best_ranked_candidate(candidates, constraints, rank_field="rating", rank_order="desc")
        self.assertEqual(len(valid), 2)
        self.assertNotIn("Laptop A (Overbudget)", [c["name"] for c in valid])
        self.assertEqual(best["name"], "Laptop B (Top Valid)")


class TestVector5ConstraintCombinationsAndANCStrictness(unittest.TestCase):
    """Vector 5: Multi-constraints, strict ANC verification, and impossible constraints."""

    def test_multi_constraint_evaluation(self):
        constraints = extract_task_constraints("wireless headphones under ₹2000 with rating above 4.0 and ANC")
        self.assertEqual(constraints.max_price, 2000.0)
        self.assertEqual(constraints.min_rating, 4.0)
        self.assertIn("active noise cancellation", constraints.required_features)

        # Pass: price 1500, rating 4.2, true ANC
        cand_pass = {"product_name": "True ANC Headphones", "price": "₹1,499", "rating": "4.2"}
        page_pass = "Features Active Noise Cancellation (ANC) up to 30dB."
        res = evaluate_candidate(cand_pass, page_pass, constraints)
        self.assertTrue(res["satisfied"])

        # Fail: price matches, rating matches, but NO ANC
        cand_no_anc = {"product_name": "Standard Headphones", "price": "₹1,499", "rating": "4.2"}
        page_no_anc = "Clear stereo sound with deep bass."
        res = evaluate_candidate(cand_no_anc, page_no_anc, constraints)
        self.assertFalse(res["satisfied"])

        # Fail: price matches, ANC matches, but rating 3.8 (< 4.0)
        cand_low_rating = {"product_name": "ANC Budget Headphones", "price": "₹1,499", "rating": "3.8"}
        page_anc = "Active Noise Cancellation enabled."
        res = evaluate_candidate(cand_low_rating, page_anc, constraints)
        self.assertFalse(res["satisfied"])

        # Fail: rating and ANC match, but price ₹2500 (> 2000)
        cand_high_price = {"product_name": "Premium ANC Headphones", "price": "₹2,500", "rating": "4.5"}
        res = evaluate_candidate(cand_high_price, page_anc, constraints)
        self.assertFalse(res["satisfied"])

    def test_anc_strictness_enc_and_noise_reduction_rejected(self):
        """Verify that ENC, noise reduction, and passive noise cancellation do NOT satisfy ANC."""
        # 1. ENC must fail
        ok, msg = check_feature_present("active noise cancellation", "Equipped with quad mics and Environmental Noise Cancellation (ENC).")
        self.assertFalse(ok)
        self.assertIn("ENC", msg)

        # 2. Generic noise reduction must fail
        ok, msg = check_feature_present("active noise cancellation", "Delivers superior passive noise reduction cushions.")
        self.assertFalse(ok)
        self.assertIn("reduction", msg)

        # 3. Explicit absence must fail
        ok, msg = check_feature_present("active noise cancellation", "Active Noise Cancellation: No")
        self.assertFalse(ok)
        self.assertIn("absent", msg)

    def test_impossible_constraints_fail_cleanly(self):
        """Verify impossible bounds (< ₹1 or rating 6.0) reject all candidates."""
        # 1. Price < 1
        c_price = extract_task_constraints("Find a gaming laptop under ₹1 on Flipkart")
        self.assertEqual(c_price.max_price, 1.0)
        cand = {"product_name": "Budget Laptop", "price": "₹15,000", "rating": "4.2"}
        res = evaluate_candidate(cand, "", c_price)
        self.assertFalse(res["satisfied"])
        self.assertIn("exceeds required maximum", res["rejection_reasons"][0])

        # 2. Rating 6.0 (impossible on 5-point scale)
        c_rating = extract_task_constraints("Find headphones with rating 6.0")
        self.assertEqual(c_rating.min_rating, 6.0)
        cand = {"product_name": "Top Headphones", "price": "₹1,500", "rating": "5.0"}
        res = evaluate_candidate(cand, "", c_rating)
        self.assertFalse(res["satisfied"])
        self.assertIn("below required minimum", res["rejection_reasons"][0])


class TestVector6ProceduralStateMachineOrdering(unittest.TestCase):
    """Vector 6: Procedural execution order, go_back tracking, and blocking premature DONE."""

    def test_deep_procedural_ordering_and_blocking(self):
        task = (
            "Open Wikipedia, search for India, click on History of India, "
            "go back to India, click on Geography of India, go back to India, "
            "click on Demographics of India, go back to India."
        )
        plan = parse_task_plan(task)
        memory = AgentMemory()
        memory.task = task
        memory.task_plan = plan

        self.assertEqual(len(plan.procedural_requirements), 6)
        self.assertEqual(plan.procedural_requirements[0], "click on History of India")
        self.assertEqual(plan.procedural_requirements[1], "go back to India")
        self.assertEqual(plan.procedural_requirements[2], "click on Geography of India")
        self.assertEqual(plan.procedural_requirements[3], "go back to India")
        self.assertEqual(plan.procedural_requirements[4], "click on Demographics of India")
        self.assertEqual(plan.procedural_requirements[5], "go back to India")

        # Initially, procedure index is 0
        self.assertEqual(memory.procedure_index, 0)
        self.assertEqual(memory.current_procedure, "click on History of India")

        # Verify premature completion is strictly blocked
        sat, reason = memory.is_procedure_satisfied()
        self.assertFalse(sat)
        self.assertIn("remaining", reason.lower())

        # Step 1: Click History of India
        page_history = MagicMock()
        page_history.url = "https://en.wikipedia.org/wiki/History_of_India"
        page_history.title.return_value = "History of India - Wikipedia"
        ver1 = MagicMock()
        ver1.verified = True
        ver1.state_changed = True
        ver1.details = {"navigated": True}

        advanced = memory.advance_procedure(
            page=page_history,
            action={"action": "click", "target": "History of India"},
            verification=ver1,
        )
        self.assertTrue(advanced)
        self.assertEqual(memory.procedure_index, 1)
        self.assertEqual(memory.current_procedure, "go back to India")

        # Trying to click Geography before going back must FAIL to satisfy next procedure
        can_adv, reason = memory.can_advance_procedure(
            page=page_history,
            action={"action": "click", "target": "Geography of India"},
            verification=ver1,
        )
        self.assertFalse(can_adv)
        self.assertIn("expected action 'go_back'", reason.lower())

        # Step 2: go_back to India
        page_india = MagicMock()
        page_india.url = "https://en.wikipedia.org/wiki/India"
        page_india.title.return_value = "India - Wikipedia"
        page_india.evaluate.return_value = "India"
        ver2 = MagicMock()
        ver2.verified = True
        ver2.state_changed = True

        advanced = memory.advance_procedure(
            page=page_india,
            action={"action": "go_back"},
            verification=ver2,
        )
        self.assertTrue(advanced)
        self.assertEqual(memory.procedure_index, 2)
        self.assertEqual(memory.current_procedure, "click on Geography of India")


class TestVector7LoopRecoveryAndOscillation(unittest.TestCase):
    """Vector 7: Oscillation detection and escape action generation."""

    def test_oscillation_detection(self):
        detector = LoopDetector()
        memory = AgentMemory()

        act_down = {"action": "scroll", "direction": "down", "amount": 300}
        act_up = {"action": "scroll", "direction": "up", "amount": 300}

        # Simulate history: down -> up -> down
        memory.action_history.append(ActionRecord(step=1, action=act_down, success=True, state_change=True))
        memory.action_history.append(ActionRecord(step=2, action=act_up, success=True, state_change=True))
        memory.action_history.append(ActionRecord(step=3, action=act_down, success=True, state_change=True))

        # Proposed action is up -> completes cycle
        is_loop, advice = detector.check_loop(memory, act_up)
        self.assertTrue(is_loop)
        self.assertIn("Oscillating loop detected", advice)

    def test_semantic_action_equivalence(self):
        a1 = {"action": "scroll", "direction": "down", "amount": 300, "reasoning": "Reason 1", "confidence": 0.8}
        a2 = {"action": "scroll", "direction": "down", "amount": 300, "reasoning": "Different Reason", "confidence": 0.95}
        a3 = {"action": "scroll", "direction": "up", "amount": 300}

        self.assertTrue(actions_equivalent(a1, a2))
        self.assertFalse(actions_equivalent(a1, a3))


class TestVector8NegativeTestsZeroFalsePositives(unittest.TestCase):
    """Vector 8: Guaranteed zero false positives on impossible tasks."""

    def test_impossible_task_cannot_be_verified_as_success(self):
        """Verify that an ungrounded or unsatisfied task cannot yield SUCCESS."""
        memory = AgentMemory()
        memory.task = "Search for xyznonexistentitem99999 on Amazon and report its price."
        memory.task_plan = parse_task_plan(memory.task)

        # On search page with no product results
        page = MagicMock()
        page.url = "https://www.amazon.in/s?k=xyznonexistentitem99999"
        page.title.return_value = "Amazon.in : xyznonexistentitem99999"

        # Information not satisfied
        sat = memory.is_information_satisfied(memory.task, page=page)
        self.assertFalse(sat)


class TestVector9HardcodingAudit(unittest.TestCase):
    """Vector 9: Scour the codebase programmatically to ensure no hardcoded cheats exist."""

    def test_no_hardcoded_answers_or_fixed_entity_branches(self):
        workspace_dir = Path(__file__).resolve().parent.parent / "browser_agent"
        py_files = list(workspace_dir.glob("*.py"))
        self.assertTrue(len(py_files) >= 5, "Should find browser_agent source files")

        forbidden_literals = [
            "new delhi",
            "1.48 billion",
            "hp victus",
            "94,990",
            "94990",
        ]

        for py_file in py_files:
            content = py_file.read_text(encoding="utf-8").lower()
            for forbidden in forbidden_literals:
                self.assertNotIn(
                    forbidden,
                    content,
                    f"Forbidden hardcoded literal '{forbidden}' found in {py_file.name}!",
                )


if __name__ == "__main__":
    unittest.main()
