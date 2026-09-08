"""
Regression test suite for generalized constraint-aware task execution.
Covers price, rating, feature, logical combinations, missing evidence,
ENC vs ANC distinction, bounded candidate exploration, and strict verification.
"""
import unittest
from typing import Any

from browser_agent.constraints import (
    TaskConstraints,
    check_feature_present,
    evaluate_candidate,
    extract_task_constraints,
    parse_numeric_price,
    parse_numeric_rating,
)
from browser_agent.state import AgentMemory


class TestConstraintAwareExecution(unittest.TestCase):

    # 1. Price-only constraint
    def test_price_only_constraint(self):
        constraints = extract_task_constraints("Find laptop bags under ₹1000")
        self.assertEqual(constraints.max_price, 1000.0)
        self.assertIsNone(constraints.min_rating)

        # Candidate under ₹1000 -> PASS
        cand1 = {"product_name": "Bag A", "price": "₹599", "rating": "4.1"}
        res1 = evaluate_candidate(cand1, "High quality laptop bag", constraints)
        self.assertTrue(res1["satisfied"])

        # Candidate above ₹1000 -> FAIL
        cand2 = {"product_name": "Bag B", "price": "₹1299", "rating": "4.1"}
        res2 = evaluate_candidate(cand2, "High quality laptop bag", constraints)
        self.assertFalse(res2["satisfied"])
        self.assertTrue(any("exceeds" in r for r in res2["rejection_reasons"]))

    # 2. Rating-only constraint
    def test_rating_only_constraint(self):
        constraints = extract_task_constraints("Find headphones with a 5.0 rating")
        self.assertEqual(constraints.exact_rating, 5.0)

        # Candidate 5.0 rating -> PASS
        cand1 = {"product_name": "Headphones A", "price": "₹1500", "rating": "5.0"}
        res1 = evaluate_candidate(cand1, "Great sound", constraints)
        self.assertTrue(res1["satisfied"])

        # Candidate 4.5 rating -> FAIL
        cand2 = {"product_name": "Headphones B", "price": "₹1500", "rating": "4.5"}
        res2 = evaluate_candidate(cand2, "Great sound", constraints)
        self.assertFalse(res2["satisfied"])
        self.assertTrue(any("does not meet required" in r or "below" in r for r in res2["rejection_reasons"]))

    # 3. Feature-only constraint
    def test_feature_only_constraint(self):
        constraints = extract_task_constraints("Find headphones with active noise cancellation")
        self.assertIn("active noise cancellation", constraints.required_features)

        # Candidate with explicit ANC -> PASS
        cand1 = {"product_name": "Headphones Pro ANC", "price": "₹2000", "rating": "4.2"}
        res1 = evaluate_candidate(cand1, "Features: Active Noise Cancellation, 30hr battery", constraints)
        self.assertTrue(res1["satisfied"])

        # Candidate without ANC -> FAIL
        cand2 = {"product_name": "Basic Headphones", "price": "₹500", "rating": "4.2"}
        res2 = evaluate_candidate(cand2, "Features: Good bass, wired", constraints)
        self.assertFalse(res2["satisfied"])

    # 4. Price AND Rating constraint
    def test_price_and_rating_constraint(self):
        constraints = extract_task_constraints("Find laptop bag under ₹1 with a 5.0 rating")
        self.assertEqual(constraints.max_price, 1.0)
        self.assertEqual(constraints.exact_rating, 5.0)

        # Passes price but fails rating -> FAIL
        cand1 = {"product_name": "Bag A", "price": "₹0.50", "rating": "4.8"}
        self.assertFalse(evaluate_candidate(cand1, "", constraints)["satisfied"])

        # Passes rating but fails price -> FAIL
        cand2 = {"product_name": "Bag B", "price": "₹499", "rating": "5.0"}
        self.assertFalse(evaluate_candidate(cand2, "", constraints)["satisfied"])

        # Passes BOTH -> PASS
        cand3 = {"product_name": "Bag C", "price": "₹0.90", "rating": "5.0"}
        self.assertTrue(evaluate_candidate(cand3, "", constraints)["satisfied"])

    # 5. Price AND Rating AND Feature constraint
    def test_price_and_rating_and_feature_constraint(self):
        constraints = extract_task_constraints(
            "Find wireless headphones under ₹1 with a 5.0 rating and active noise cancellation"
        )
        self.assertEqual(constraints.max_price, 1.0)
        self.assertEqual(constraints.exact_rating, 5.0)
        self.assertIn("active noise cancellation", constraints.required_features)

        # Passes price and rating, but missing ANC -> FAIL
        cand1 = {"product_name": "Earbuds A", "price": "₹0.50", "rating": "5.0"}
        self.assertFalse(evaluate_candidate(cand1, "Standard stereo sound", constraints)["satisfied"])

        # Passes all three -> PASS
        cand2 = {"product_name": "Earbuds B", "price": "₹0.50", "rating": "5.0"}
        self.assertTrue(evaluate_candidate(cand2, "Features: Active Noise Cancellation", constraints)["satisfied"])

    # 6. Candidate missing price
    def test_candidate_missing_price_rejected(self):
        constraints = extract_task_constraints("Find shoes under ₹1000")
        cand = {"product_name": "Shoes A", "price": None, "rating": "4.5"}
        res = evaluate_candidate(cand, "", constraints)
        self.assertFalse(res["satisfied"])
        self.assertTrue(any("missing" in r or "not found" in r for r in res["rejection_reasons"]))

    # 7. Candidate missing rating
    def test_candidate_missing_rating_rejected(self):
        constraints = extract_task_constraints("Find laptop bag with a 5.0 rating")
        cand = {"product_name": "Bag A", "price": "₹500", "rating": None}
        res = evaluate_candidate(cand, "", constraints)
        self.assertFalse(res["satisfied"])
        self.assertTrue(any("missing" in r or "not found" in r for r in res["rejection_reasons"]))

    # 8. Candidate missing feature
    def test_candidate_missing_feature_rejected(self):
        constraints = extract_task_constraints("Find headphones with active noise cancellation")
        cand = {"product_name": "Headphones X", "price": "₹1000", "rating": "4.5"}
        res = evaluate_candidate(cand, "Bluetooth 5.0, deep bass", constraints)
        self.assertFalse(res["satisfied"])

    # 9. ENC must not satisfy ANC
    def test_enc_must_not_satisfy_anc(self):
        present, msg = check_feature_present(
            "active noise cancellation",
            "Quad mic with Environmental Noise Cancellation (ENC) for crystal clear calls"
        )
        self.assertFalse(present)
        self.assertIn("ENC", msg)

        # Conversely, true ANC must satisfy
        present2, msg2 = check_feature_present(
            "active noise cancellation",
            "Features Hybrid Active Noise Cancellation (ANC) up to 35dB"
        )
        self.assertTrue(present2)

    # 10. Rejected candidate followed by successful candidate
    def test_rejected_candidate_followed_by_successful_candidate(self):
        constraints = extract_task_constraints("Find headphones under ₹2000 with a 4.0 rating")
        
        cand1 = {"product_name": "Headphones 1", "price": "₹2500", "rating": "4.5"}
        eval1 = evaluate_candidate(cand1, "", constraints)
        self.assertFalse(eval1["satisfied"])

        cand2 = {"product_name": "Headphones 2", "price": "₹1499", "rating": "4.2"}
        eval2 = evaluate_candidate(cand2, "", constraints)
        self.assertTrue(eval2["satisfied"])

    # 11. All candidates rejected => NO_MATCH
    def test_all_candidates_rejected_generates_no_match(self):
        constraints = extract_task_constraints(
            "Go to Flipkart and find laptop bag under ₹1 with a 5.0 rating. If no product satisfies both, report that no matching product was found."
        )
        candidates = [
            {"product_name": "Bag 1", "price": "₹448", "rating": "4.1"},
            {"product_name": "Bag 2", "price": "₹593", "rating": "4.2"},
            {"product_name": "Bag 3", "price": "₹761", "rating": "4.0"},
        ]
        evaluations = [evaluate_candidate(c, "", constraints) for c in candidates]
        self.assertTrue(all(not e["satisfied"] for e in evaluations))

        # Memory state reflects honest NO_MATCH
        memory = AgentMemory(task=constraints.raw_task)
        memory.extracted_data = {"status": "NO_MATCH", "message": "No matching product found."}
        self.assertTrue(memory.is_information_satisfied(constraints.raw_task, constraints=constraints))

    # 12. Verifier rejects unsatisfied candidate
    def test_verifier_rejects_unsatisfied_candidate(self):
        constraints = extract_task_constraints("Find laptop bag under ₹1 with 5.0 rating")
        extracted_data = {"product_name": "Overpriced Bag", "price": "₹599", "rating": "4.1"}
        eval_res = evaluate_candidate(extracted_data, "", constraints)
        self.assertFalse(eval_res["satisfied"])

    # 13. Verifier rejects incomplete candidate
    def test_verifier_rejects_incomplete_candidate(self):
        constraints = extract_task_constraints("Find headphones under ₹1000 with active noise cancellation")
        extracted_data = {"product_name": "Headphones", "price": "₹500"}  # missing ANC evidence
        eval_res = evaluate_candidate(extracted_data, "Regular sound", constraints)
        self.assertFalse(eval_res["satisfied"])

    # 14. Verifier accepts only fully satisfying candidate
    def test_verifier_accepts_only_fully_satisfying_candidate(self):
        constraints = extract_task_constraints("Find headphones under ₹2000 with a 4.0 rating and active noise cancellation")
        good_cand = {"product_name": "Pro ANC", "price": "₹1500", "rating": "4.3"}
        eval_res = evaluate_candidate(good_cand, "Full hybrid Active Noise Cancellation", constraints)
        self.assertTrue(eval_res["satisfied"])

    # 15. Exact second adversarial task semantics
    def test_exact_second_adversarial_task_semantics(self):
        task = "Go to Flipkart and find wireless headphones under ₹1 with a 5.0 rating and active noise cancellation. If no product satisfies all three conditions, report that no matching product was found. Do not invent or relax any constraint."
        constraints = extract_task_constraints(task)

        self.assertEqual(constraints.max_price, 1.0)
        self.assertEqual(constraints.exact_rating, 5.0)
        self.assertIn("active noise cancellation", constraints.required_features)
        self.assertTrue(constraints.has_no_match_instruction)

        # Real Flipkart product: HOPPUP BEAT X1 (₹294, 4.5 rating, ENC only)
        hoppup = {"product_name": "HOPPUP BEAT X1", "price": "₹294", "rating": "4.5"}
        page_text = "Wireless Bluetooth Earbuds with ENC environmental noise cancellation for calls"
        res = evaluate_candidate(hoppup, page_text, constraints)

        self.assertFalse(res["satisfied"])
        self.assertEqual(len(res["rejection_reasons"]), 3)
        self.assertTrue(any("₹294 exceeds" in r for r in res["rejection_reasons"]))
        self.assertTrue(any("4.5 does not meet" in r for r in res["rejection_reasons"]))
        self.assertTrue(any("ENC" in r or "Active Noise Cancellation" in r for r in res["rejection_reasons"]))

    # 16. Natural-language rating operators
    def test_natural_language_rating_operators(self):
        cases = [
            ("rating of at least 4.0", 4.0, None),
            ("rating at least 4.0", 4.0, None),
            ("rating >= 4.0", 4.0, None),
            ("4.0 rating or higher", 4.0, None),
            ("exactly 5.0 rating", 5.0, 5.0),
            ("5.0 rating", 5.0, 5.0),
            ("rating exactly 5.0", 5.0, 5.0),
            ("with a rating of 4.5 or higher", 4.5, None),
        ]
        for query, expected_min, expected_exact in cases:
            with self.subTest(query=query):
                c = extract_task_constraints(query)
                self.assertEqual(c.min_rating, expected_min, f"min_rating mismatch for '{query}'")
                self.assertEqual(c.exact_rating, expected_exact, f"exact_rating mismatch for '{query}'")
                self.assertIsNone(c.min_price, f"Erroneous min_price parsed for rating query '{query}'")

    # 17. Exact failed live task constraint extraction
    def test_exact_failed_live_task_constraints(self):
        task = "Go to Flipkart and find wireless headphones under ₹2000 with a rating of at least 4.0."
        constraints = extract_task_constraints(task)

        self.assertEqual(constraints.category, "wireless headphones")
        self.assertEqual(constraints.max_price, 2000.0)
        self.assertIsNone(constraints.min_price, "Constraints must NOT contain a second price constraint!")
        self.assertEqual(constraints.min_rating, 4.0)
        self.assertIsNone(constraints.exact_rating)
        self.assertEqual(constraints.summary(), "category='wireless headphones', price < 2000, rating >= 4.0")

    # 18. Complete evaluator on candidate combinations
    def test_complete_evaluator_candidates(self):
        task = "Go to Flipkart and find wireless headphones under ₹2000 with a rating of at least 4.0."
        constraints = extract_task_constraints(task)

        # Candidate 1: price = ₹1500, rating = 4.3 => satisfied = True
        cand1 = {"product_name": "Wireless Headphones Pro", "price": "₹1500", "rating": "4.3"}
        res1 = evaluate_candidate(cand1, "", constraints)
        self.assertTrue(res1["satisfied"], f"Candidate 1 should be satisfied: {res1['rejection_reasons']}")

        # Candidate 2: price = ₹1500, rating = 3.7 => satisfied = False
        cand2 = {"product_name": "Wireless Headphones Basic", "price": "₹1500", "rating": "3.7"}
        res2 = evaluate_candidate(cand2, "", constraints)
        self.assertFalse(res2["satisfied"])
        self.assertTrue(any("3.7 is below required minimum 4.0" in r for r in res2["rejection_reasons"]))

        # Candidate 3: price = ₹2500, rating = 4.5 => satisfied = False
        cand3 = {"product_name": "Wireless Headphones Premium", "price": "₹2500", "rating": "4.5"}
        res3 = evaluate_candidate(cand3, "", constraints)
        self.assertFalse(res3["satisfied"])
        self.assertTrue(any("2500" in r and "exceeds" in r for r in res3["rejection_reasons"]))

    # 19. Task completed flag cannot override failed constraints
    def test_task_completed_cannot_override_failed_constraints(self):
        task = "Go to Flipkart and find wireless headphones under ₹2000 with a rating of at least 4.0."
        constraints = extract_task_constraints(task)

        # A candidate that fails rating (e.g. 3.7)
        cand = {"product_name": "Aroma NB120", "price": "₹999", "rating": "3.7"}
        eval_res = evaluate_candidate(cand, "", constraints)
        self.assertFalse(eval_res["satisfied"])

        # Emulate final verification logic:
        # Even if task_completed was True, verifier MUST strictly evaluate eval_res["satisfied"]
        task_completed = True
        is_success = bool(eval_res["satisfied"])  # Must NOT be (eval_res["satisfied"] or task_completed)
        final_state_str = "SUCCESS" if is_success else "FAILED"

        self.assertFalse(is_success, "task_completed must NOT override failed constraints!")
        self.assertEqual(final_state_str, "FAILED")
        self.assertNotEqual(final_state_str, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
