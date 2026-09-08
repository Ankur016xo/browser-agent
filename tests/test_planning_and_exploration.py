"""
Unit tests for Task Planning, Target-Page Satisfaction, Goal-First Exploration,
and Structured Loop Recovery in Vision Lite.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from browser_agent.exploration import (
    choose_goal_exploration_action,
    find_matching_target_link,
    inspect_page_for_requested_info,
    is_page_relevant_to_target,
)
from browser_agent.loop_detector import LoopDetector
from browser_agent.planner import TaskPlan, parse_task_plan
from browser_agent.state import ActionRecord, AgentMemory, ElementInfo, ScrollState


class TestTaskPlanParsing(unittest.TestCase):
    """Test natural language task plan decomposition."""

    def test_wikipedia_extraction_task(self):
        task = "Go to Wikipedia, open the India article, and find the official language of India."
        plan = parse_task_plan(task)
        self.assertEqual(plan.destination, "wikipedia")
        self.assertEqual(plan.destination_url, "https://www.wikipedia.org")
        self.assertEqual(plan.target, "India")
        self.assertEqual(plan.target_type, "article")
        self.assertEqual(plan.search_query, "India")
        self.assertEqual(plan.intent, "information_extraction")
        self.assertIn("official language", plan.requested_information)
        self.assertIn("open the India article", plan.navigation_requirement)

    def test_wikipedia_capital_task(self):
        task = "Go to Wikipedia, search for India, open the India article, and find the capital of India."
        plan = parse_task_plan(task)
        self.assertEqual(plan.destination, "wikipedia")
        self.assertEqual(plan.target, "India")
        self.assertEqual(plan.target_type, "article")
        self.assertEqual(plan.search_query, "India")
        self.assertIn("capital", plan.requested_information)

    def test_search_engine_documentation_navigation(self):
        task = "Search DuckDuckGo for Python official documentation and open the official Python documentation website."
        plan = parse_task_plan(task)
        self.assertEqual(plan.destination, "duckduckgo")
        self.assertEqual(plan.destination_url, "https://duckduckgo.com")
        self.assertEqual(plan.target, "official Python documentation")
        self.assertEqual(plan.target_type, "website")
        self.assertEqual(plan.intent, "navigation")
        self.assertIn("Python", plan.search_query)

    def test_direct_url_navigation(self):
        task = "Go to https://docs.python.org/3/index.html and check the page title"
        plan = parse_task_plan(task)
        self.assertEqual(plan.destination_url, "https://docs.python.org/3/index.html")
        self.assertEqual(plan.intent, "information_extraction")
        self.assertIn("page title", plan.requested_information)

    def test_constrained_product_search(self):
        task = "Go to Flipkart and find wireless headphones under ₹2000 with a rating of at least 4.0."
        plan = parse_task_plan(task)
        self.assertEqual(plan.destination, "flipkart")
        self.assertEqual(plan.search_query, "wireless headphones")
        self.assertEqual(plan.intent, "product_search")


class TestTargetPageSatisfaction(unittest.TestCase):
    """Test deterministic verification of target page identity."""

    def test_exact_target_article_satisfied(self):
        plan = parse_task_plan("Go to Wikipedia, open the India article, and find the official language of India.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        satisfied, reason = memory.is_target_page_satisfied(mock_page)
        self.assertTrue(satisfied)
        self.assertIn("matches", reason.lower())

    def test_wrong_related_article_rejected(self):
        """CRITICAL: 'Languages of India' must NOT satisfy target 'India'."""
        plan = parse_task_plan("Go to Wikipedia, open the India article, and find the official language of India.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/Languages_of_India"
        mock_page.title.return_value = "Languages of India - Wikipedia"
        mock_page.evaluate.return_value = "Languages of India"

        satisfied, reason = memory.is_target_page_satisfied(mock_page)
        self.assertFalse(satisfied)
        self.assertIn("specialized sub-topic", reason.lower())

    def test_search_results_page_rejected_as_target(self):
        plan = parse_task_plan("Search DuckDuckGo for Python official documentation and open the official Python documentation website.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://duckduckgo.com/?q=Python+documentation"
        mock_page.title.return_value = "Python documentation at DuckDuckGo"
        mock_page.evaluate.return_value = ""

        satisfied, reason = memory.is_target_page_satisfied(mock_page)
        self.assertFalse(satisfied)
        self.assertIn("search engine", reason.lower())

    def test_documentation_website_satisfied(self):
        plan = parse_task_plan("Search DuckDuckGo for Python official documentation and open the official Python documentation website.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://docs.python.org/3/index.html"
        mock_page.title.return_value = "3.12.2 Documentation"
        mock_page.evaluate.return_value = "Welcome to Python 3.12.2 documentation"

        satisfied, reason = memory.is_target_page_satisfied(mock_page)
        self.assertTrue(satisfied)

    def test_navigation_only_already_satisfied_at_start(self):
        plan = parse_task_plan("Open the official Python documentation website.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://docs.python.org/3/index.html"
        mock_page.title.return_value = "Python 3 Documentation"

        self.assertTrue(memory.is_information_satisfied(plan.raw_task, page=mock_page))


class TestScrollState(unittest.TestCase):
    """Test ScrollState boundary detection, position tracking, and verification."""

    def test_scroll_state_updates(self):
        state = ScrollState()
        self.assertEqual(state.current_y, 0)
        self.assertTrue(state.reached_top)
        self.assertFalse(state.reached_bottom)

        # Scrolled down to y=500, max=2000, viewport=800
        changed = state.update(scroll_y=500, max_y=2000, vp_height=800)
        self.assertTrue(changed)
        self.assertEqual(state.current_y, 500)
        self.assertFalse(state.reached_top)
        self.assertFalse(state.reached_bottom)
        self.assertEqual(state.consecutive_no_scroll_changes, 0)

        # Scrolled to bottom: y=1200 + 800 = 2000 >= 1975
        changed = state.update(scroll_y=1200, max_y=2000, vp_height=800)
        self.assertTrue(changed)
        self.assertTrue(state.reached_bottom)

        # Scroll down attempted again but didn't move
        changed = state.update(scroll_y=1200, max_y=2000, vp_height=800)
        self.assertFalse(changed)
        self.assertEqual(state.consecutive_no_scroll_changes, 1)


class TestExplorationEngine(unittest.TestCase):
    """Test target link selection and goal-aware exploration."""

    def test_find_matching_target_link_prefers_exact_article(self):
        elements = [
            ElementInfo(id=1, tag="a", role="link", text="Languages of India", attributes={"href": "/wiki/Languages_of_India"}),
            ElementInfo(id=2, tag="a", role="link", text="History of India", attributes={"href": "/wiki/History_of_India"}),
            ElementInfo(id=3, tag="a", role="link", text="India", attributes={"href": "/wiki/India"}),
            ElementInfo(id=4, tag="a", role="link", text="Help", attributes={"href": "/wiki/Help"}),
        ]
        best = find_matching_target_link(elements, target="India", target_type="article")
        self.assertIsNotNone(best)
        self.assertEqual(best.id, 3)
        self.assertEqual(best.text, "India")

    def test_target_content_page_scrolls_instead_of_clicking_search(self):
        plan = parse_task_plan("Go to Wikipedia, open the India article, and find the official language of India.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        elements = [
            ElementInfo(id=1, tag="input", role="textbox", text="", attributes={"name": "search"}),
            ElementInfo(id=2, tag="button", role="button", text="Search", attributes={}),
        ]

        # Official language is not in mock page body text yet
        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertIsNotNone(action)
        # MUST NOT CLICK SEARCH! MUST SCROLL DOWN!
        self.assertEqual(action["action"], "scroll")
        self.assertEqual(action["direction"], "down")

    def test_target_content_page_extracts_when_info_visible(self):
        plan = parse_task_plan("Go to Wikipedia, open the India article, and find the official language of India.")
        memory = AgentMemory(task=plan.raw_task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        # Return h1 for querySelector, body text containing official languages for body
        def mock_eval(script):
            if "querySelector('h1')" in script:
                return "India"
            return "Official languages: Hindi, English [1]\nCapital: New Delhi"

        mock_page.evaluate.side_effect = mock_eval

        action = choose_goal_exploration_action(mock_page, [], memory)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "done")
        self.assertIn("official_language", action["result"])
        self.assertIn("Hindi", action["result"]["official_language"])


class TestStructuredLoopRecovery(unittest.TestCase):
    """Test that failed repeated clicks trigger non-repeating structured recovery."""

    def test_failed_search_click_triggers_enter_or_scroll(self):
        detector = LoopDetector(max_identical_actions=2)
        memory = AgentMemory()
        # Simulate previous failed click on search button (id=5)
        failed_act = {"action": "click", "element_id": 5, "text": None}
        memory.action_history.append(ActionRecord(
            step=1,
            action=failed_act,
            success=True,
            verified=True,
            state_change=False,
            reasoning="Click search button",
            confidence=0.9,
            url_before="https://en.wikipedia.org",
            url_after="https://en.wikipedia.org",
            title_before="Wikipedia",
            title_after="Wikipedia",
        ))

        elements = [
            ElementInfo(id=5, tag="button", role="button", text="Search", attributes={}),
            ElementInfo(id=6, tag="a", role="link", text="Explore Main Page", attributes={"href": "/wiki/Main"}),
        ]
        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org"

        recovery = detector.get_recovery_action(memory, elements, mock_page, failed_action=failed_act)
        # Should press Enter or choose non-repeating alternative action
        self.assertIn(recovery["action"], ["press_key", "scroll", "click"])
        if recovery["action"] == "click":
            self.assertNotEqual(recovery["element_id"], 5)


class TestProceduralRequirementsAndSatisfaction(unittest.TestCase):
    """
    Test that:
    A. Parser preserves procedural actions.
    B. Target + information + remaining procedure is NOT considered complete.
    C. Target + information + no remaining procedure CAN complete.
    D. An impossible intermediate procedure causes INCOMPLETE/FAILED.
    E. Loop recovery does not abandon a satisfied target page unnecessarily.
    """

    def test_parser_preserves_procedural_actions(self):
        task = "Go to Wikipedia, open the India article, click a link called This link definitely does not exist, go back to the India article, and report the page heading."
        plan = parse_task_plan(task)
        self.assertEqual(plan.target, "India")
        self.assertIn("heading", plan.requested_information)
        self.assertEqual(len(plan.procedural_requirements), 3)
        self.assertIn("open the India article", plan.procedural_requirements)
        self.assertTrue(any("click a link called" in pr for pr in plan.procedural_requirements))
        self.assertTrue(any("go back" in pr for pr in plan.procedural_requirements))

    def test_target_info_with_remaining_procedure_not_complete(self):
        task = "Go to Wikipedia, open the India article, click a link called This link definitely does not exist, go back to the India article, and report the page heading."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.evaluate.return_value = "India"

        # Simulate heading already extracted
        memory.extracted_data = {"heading": "India"}

        # Target satisfied: True
        target_sat, _ = memory.is_target_page_satisfied(mock_page)
        self.assertTrue(target_sat)

        # Information satisfied: True
        info_sat = memory.is_information_satisfied(task, mock_page)
        self.assertTrue(info_sat)

        # BUT procedural requirements remain unexecuted!
        proc_sat, proc_reason = memory.is_procedure_satisfied(mock_page)
        self.assertFalse(proc_sat)
        self.assertIn("This link definitely does not exist", proc_reason)

        # Therefore task_satisfied MUST be False!
        task_sat, task_reason = memory.is_task_satisfied(mock_page)
        self.assertFalse(task_sat)
        self.assertIn("Procedure not satisfied", task_reason)

    def test_target_info_with_no_remaining_procedure_can_complete(self):
        task = "Go to Wikipedia, open the India article, and report the page heading."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.evaluate.return_value = "India"

        memory.extracted_data = {"heading": "India"}

        # Only procedure is "open the India article", which is satisfied on mock_page
        proc_sat, _ = memory.is_procedure_satisfied(mock_page)
        self.assertTrue(proc_sat)

        task_sat, _ = memory.is_task_satisfied(mock_page)
        self.assertTrue(task_sat)

    def test_impossible_intermediate_procedure_causes_incomplete(self):
        task = "Go to Wikipedia, open the India article, click a link called This link definitely does not exist, go back to the India article, and report the page heading."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.evaluate.return_value = "India"

        # Information was found, but impossible intermediate step was never completed
        memory.extracted_data = {"heading": "India"}

        task_sat, reason = memory.is_task_satisfied(mock_page)
        self.assertFalse(task_sat)
        self.assertIn("This link definitely does not exist", reason)

    def test_loop_recovery_does_not_abandon_satisfied_target(self):
        task = "Go to Wikipedia, open the India article, click a link called This link definitely does not exist, go back to the India article, and report the page heading."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.evaluate.return_value = "India"

        # Failed action: clicked on some element
        failed_act = {"action": "click", "element_id": 10}
        memory.action_history.append(ActionRecord(
            step=1,
            action=failed_act,
            success=True,
            verified=True,
            state_change=False,
            reasoning="Attempting to find nonexistent link",
            confidence=0.8,
            url_before="https://en.wikipedia.org/wiki/India",
            url_after="https://en.wikipedia.org/wiki/India",
            title_before="India - Wikipedia",
            title_after="India - Wikipedia",
        ))

        elements = [
            ElementInfo(id=2, tag="a", role="link", text="Main Page", attributes={"href": "/wiki/Main_Page"}),
            ElementInfo(id=3, tag="a", role="link", text="Talk", attributes={"href": "/wiki/Talk"}),
        ]

        detector = LoopDetector(max_identical_actions=2)
        recovery = detector.get_recovery_action(memory, elements, mock_page, failed_action=failed_act)

        # Loop recovery MUST NOT click "Main Page" or "Talk" to navigate away!
        # It must terminate with fail if absent, or scroll/wait while preserving target.
        if recovery["action"] == "click":
            self.assertNotEqual(recovery.get("element_id"), 2)
            self.assertNotEqual(recovery.get("element_id"), 3)
        self.assertIn(recovery["action"], ["fail", "scroll", "wait"])

    def test_procedural_element_in_viewport_clicks(self):
        task = "Go to Wikipedia, open the India article, click History of India, and find the capital of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.evaluate.return_value = "India"

        # Procedural target "History of India" is in viewport
        elements = [
            ElementInfo(id=5, tag="a", role="link", text="History of India", attributes={"href": "/wiki/History_of_India"}),
            ElementInfo(id=6, tag="a", role="link", text="Geography of India", attributes={"href": "/wiki/Geography_of_India"}),
        ]

        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertEqual(action["action"], "click")
        self.assertEqual(action.get("element_id"), 5)

    def test_procedural_element_in_dom_outside_viewport_scrolls(self):
        task = "Go to Wikipedia, open the India article, click History of India, and find the capital of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"

        # Not in viewport elements
        elements = [
            ElementInfo(id=1, tag="a", role="link", text="Main Page", attributes={"href": "/wiki/Main_Page"}),
        ]

        # DOM inspection finds it below viewport
        def mock_eval(script, *args):
            if "matchingNodes" in script or "document.querySelectorAll" in script:
                return {
                    "exists": True,
                    "inViewport": False,
                    "top": 2500,
                    "bottom": 2530,
                    "scrollDirection": "down",
                    "scrollDistance": 800,
                }
            return "India"

        mock_page.evaluate.side_effect = mock_eval

        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertEqual(action["action"], "scroll")
        self.assertEqual(action["direction"], "down")

    def test_procedural_element_nonexistent_in_dom_fails(self):
        task = "Go to Wikipedia, open the India article, click a link called This link definitely does not exist, and report the heading."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"

        elements = [
            ElementInfo(id=1, tag="a", role="link", text="Main Page", attributes={"href": "/wiki/Main_Page"}),
        ]

        # DOM inspection confirms it does not exist
        def mock_eval(script, *args):
            if "matchingNodes" in script or "document.querySelectorAll" in script:
                return {
                    "exists": False,
                    "inViewport": False,
                }
            return "India"

        mock_page.evaluate.side_effect = mock_eval

        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertEqual(action["action"], "fail")
        self.assertIn("This link definitely does not exist", memory.failed_procedures[0])

    def test_failed_procedure_rejects_satisfaction(self):
        task = "Go to Wikipedia, open the India article, click a link called Nonexistent Link, and report heading."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.evaluate.return_value = "India"

        memory.failed_procedures.append("click a link called Nonexistent Link")
        proc_sat, reason = memory.is_procedure_satisfied(mock_page)
        self.assertFalse(proc_sat)
        self.assertIn("failed", reason.lower())


class TestOrderedProceduralStateMachine(unittest.TestCase):
    """Test the ordered procedural completion state machine."""

    def test_two_procedural_steps_ordered(self):
        task = "Go to Wikipedia, open the India article, and click History of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        self.assertEqual(len(plan.procedural_requirements), 2)
        self.assertEqual(plan.procedural_requirements[0], "open the India article")
        self.assertEqual(plan.procedural_requirements[1], "click History of India")
        self.assertEqual(memory.procedure_index, 0)
        self.assertEqual(memory.current_procedure, "open the India article")

        # Step 1: Open India article
        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        adv = memory.check_and_advance_open_procedure(mock_page)
        self.assertTrue(adv)
        self.assertEqual(memory.procedure_index, 1)
        self.assertEqual(memory.current_procedure, "click History of India")

        # Step 2: Click History of India
        action = {"action": "click", "target": "history of india"}
        verification = MagicMock(verified=True, state_changed=True, details={"navigated": True})
        mock_page.url = "https://en.wikipedia.org/wiki/History_of_India"
        mock_page.title.return_value = "History of India - Wikipedia"
        mock_page.evaluate.return_value = "History of India"

        adv2 = memory.advance_procedure(mock_page, action, verification)
        self.assertTrue(adv2)
        self.assertEqual(memory.procedure_index, 2)
        self.assertIsNone(memory.current_procedure)

        sat, _ = memory.is_procedure_satisfied(mock_page)
        self.assertTrue(sat)

    def test_four_procedural_steps_ordered(self):
        task = "Go to Wikipedia, open the India article, click History of India, go back to the India article, and click Geography of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        self.assertEqual(len(plan.procedural_requirements), 4)
        self.assertEqual(plan.procedural_requirements[0], "open the India article")
        self.assertEqual(plan.procedural_requirements[1], "click History of India")
        self.assertEqual(plan.procedural_requirements[2], "go back to the India article")
        self.assertEqual(plan.procedural_requirements[3], "click Geography of India")

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        # Advance step 0: open
        self.assertTrue(memory.check_and_advance_open_procedure(mock_page))
        self.assertEqual(memory.procedure_index, 1)

        # Attempt out of order action (e.g. Geography of India while expecting History)
        geo_action = {"action": "click", "target": "geography of india"}
        ver_ok = MagicMock(verified=True, state_changed=True, details={"navigated": True})
        can_adv, reason = memory.can_advance_procedure(mock_page, geo_action, ver_ok)
        self.assertFalse(can_adv)
        self.assertEqual(memory.procedure_index, 1)

        # Execute correct step 1: click History of India
        hist_action = {"action": "click", "target": "history of india"}
        mock_page.url = "https://en.wikipedia.org/wiki/History_of_India"
        mock_page.title.return_value = "History of India - Wikipedia"
        mock_page.evaluate.return_value = "History of India"
        self.assertTrue(memory.advance_procedure(mock_page, hist_action, ver_ok))
        self.assertEqual(memory.procedure_index, 2)
        self.assertEqual(memory.current_procedure, "go back to the India article")

        # Execute step 2: go_back to India
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"
        back_action = {"action": "go_back"}
        self.assertTrue(memory.advance_procedure(mock_page, back_action, ver_ok))
        self.assertEqual(memory.procedure_index, 3)
        self.assertEqual(memory.current_procedure, "click Geography of India")

        # Execute step 3: click Geography of India
        mock_page.url = "https://en.wikipedia.org/wiki/Geography_of_India"
        mock_page.title.return_value = "Geography of India - Wikipedia"
        mock_page.evaluate.return_value = "Geography of India"
        self.assertTrue(memory.advance_procedure(mock_page, geo_action, ver_ok))
        self.assertEqual(memory.procedure_index, 4)
        self.assertTrue(memory.is_procedure_satisfied(mock_page)[0])

    def test_six_plus_procedural_steps_ordered(self):
        task = "Go to Wikipedia, open the India article, click History of India, go back to the India article, click Geography of India, go back to the India article, click Demographics of India, go back to the India article."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        self.assertEqual(len(plan.procedural_requirements), 7)
        self.assertEqual(
            plan.procedural_requirements,
            [
                "open the India article",
                "click History of India",
                "go back to the India article",
                "click Geography of India",
                "go back to the India article",
                "click Demographics of India",
                "go back to the India article",
            ]
        )

        mock_page = MagicMock()
        ver_ok = MagicMock(verified=True, state_changed=True, details={"navigated": True})

        # Step 0: open
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"
        self.assertTrue(memory.check_and_advance_open_procedure(mock_page))
        self.assertEqual(memory.procedure_index, 1)

        # Steps 1 to 6
        steps = [
            ({"action": "click", "target": "history of india"}, "https://en.wikipedia.org/wiki/History_of_India", "History of India"),
            ({"action": "go_back"}, "https://en.wikipedia.org/wiki/India", "India"),
            ({"action": "click", "target": "geography of india"}, "https://en.wikipedia.org/wiki/Geography_of_India", "Geography of India"),
            ({"action": "go_back"}, "https://en.wikipedia.org/wiki/India", "India"),
            ({"action": "click", "target": "demographics of india"}, "https://en.wikipedia.org/wiki/Demographics_of_India", "Demographics of India"),
            ({"action": "go_back"}, "https://en.wikipedia.org/wiki/India", "India"),
        ]

        for expected_idx, (act, url, title) in enumerate(steps, start=1):
            mock_page.url = url
            mock_page.title.return_value = f"{title} - Wikipedia"
            mock_page.evaluate.return_value = title
            adv = memory.advance_procedure(mock_page, act, ver_ok)
            self.assertTrue(adv, f"Failed to advance at step {expected_idx}: {memory.current_procedure}")
            self.assertEqual(memory.procedure_index, expected_idx + 1)

        self.assertEqual(memory.procedure_index, 7)
        self.assertTrue(memory.is_procedure_satisfied(mock_page)[0])

    def test_target_reached_before_procedures_complete_does_not_finish(self):
        task = "Go to Wikipedia, open the India article, click History of India, go back to the India article, and click Geography of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        # Reached India on open
        memory.check_and_advance_open_procedure(mock_page)
        # Even though target page is satisfied, procedures remain!
        is_target_sat, _ = memory.is_target_page_satisfied(mock_page)
        self.assertTrue(is_target_sat)

        is_task_sat, reason = memory.is_task_satisfied(mock_page)
        self.assertFalse(is_task_sat)
        self.assertIn("procedure not satisfied", reason.lower())

        elements = [
            ElementInfo(id=10, tag="a", role="link", text="History of India", attributes={"href": "/wiki/History_of_India"}),
        ]
        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertIsNotNone(action)
        self.assertNotEqual(action.get("action"), "done")
        self.assertEqual(action.get("action"), "click")
        self.assertEqual(action.get("element_id"), 10)

    def test_procedure_completion_advances_exactly_one_index(self):
        task = "Go to Wikipedia, open the India article, click History of India, and click Geography of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        self.assertEqual(memory.procedure_index, 0)
        memory.check_and_advance_open_procedure(mock_page)
        self.assertEqual(memory.procedure_index, 1)

        # Unverified action -> no advance
        unverified_ver = MagicMock(verified=False, state_changed=False)
        act = {"action": "click", "target": "history of india"}
        adv = memory.advance_procedure(mock_page, act, unverified_ver)
        self.assertFalse(adv)
        self.assertEqual(memory.procedure_index, 1)

        # Verified action -> advances exactly one index to 2
        ver_ok = MagicMock(verified=True, state_changed=True, details={"navigated": True})
        mock_page.url = "https://en.wikipedia.org/wiki/History_of_India"
        mock_page.title.return_value = "History of India - Wikipedia"
        mock_page.evaluate.return_value = "History of India"

        adv = memory.advance_procedure(mock_page, act, ver_ok)
        self.assertTrue(adv)
        self.assertEqual(memory.procedure_index, 2)
        self.assertEqual(memory.current_procedure, "click Geography of India")

    def test_go_back_requires_expected_destination(self):
        task = "Go to Wikipedia, open the India article, click History of India, and go back to the India article."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"
        memory.check_and_advance_open_procedure(mock_page)

        ver_ok = MagicMock(verified=True, state_changed=True, details={"navigated": True})
        # Complete History of India click
        mock_page.url = "https://en.wikipedia.org/wiki/History_of_India"
        mock_page.title.return_value = "History of India - Wikipedia"
        mock_page.evaluate.return_value = "History of India"
        memory.advance_procedure(mock_page, {"action": "click", "target": "history of india"}, ver_ok)

        self.assertEqual(memory.current_procedure, "go back to the India article")

        # Simulate go_back returning to wrong page (e.g. still on History of India or unrelated page)
        mock_page.url = "https://en.wikipedia.org/wiki/History_of_India"
        mock_page.title.return_value = "History of India - Wikipedia"
        mock_page.evaluate.return_value = "History of India"

        back_act = {"action": "go_back"}
        can_adv, reason = memory.can_advance_procedure(mock_page, back_act, ver_ok)
        self.assertFalse(can_adv)
        self.assertIn("did not return to expected target page", reason)

        # Now simulate go_back returning to India article
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"

        can_adv2, reason2 = memory.can_advance_procedure(mock_page, back_act, ver_ok)
        self.assertTrue(can_adv2)
        adv = memory.advance_procedure(mock_page, back_act, ver_ok)
        self.assertTrue(adv)
        self.assertEqual(memory.procedure_index, 3)

    def test_nonexistent_procedure_fails(self):
        task = "Go to Wikipedia, open the India article, click a link called This link definitely does not exist, and go back to the India article."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"
        memory.check_and_advance_open_procedure(mock_page)

        self.assertEqual(memory.current_procedure, "click a link called This link definitely does not exist")

        elements = [
            ElementInfo(id=1, tag="a", role="link", text="Main Page"),
        ]

        def mock_eval(script, *args):
            if "matchingNodes" in script or "document.querySelectorAll" in script:
                return {"exists": False, "inViewport": False}
            return "India"

        mock_page.evaluate.side_effect = mock_eval

        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertEqual(action["action"], "fail")
        self.assertIn("This link definitely does not exist", memory.failed_procedures[0])

        sat, reason = memory.is_procedure_satisfied(mock_page)
        self.assertFalse(sat)
        self.assertIn("failed", reason.lower())

    def test_all_procedures_complete_success(self):
        task = "Go to Wikipedia, open the India article, and click History of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://en.wikipedia.org/wiki/India"
        mock_page.title.return_value = "India - Wikipedia"
        mock_page.evaluate.return_value = "India"
        memory.check_and_advance_open_procedure(mock_page)

        ver_ok = MagicMock(verified=True, state_changed=True, details={"navigated": True})
        mock_page.url = "https://en.wikipedia.org/wiki/History_of_India"
        mock_page.title.return_value = "History of India - Wikipedia"
        mock_page.evaluate.return_value = "History of India"
        memory.advance_procedure(mock_page, {"action": "click", "target": "history of india"}, ver_ok)

        sat, reason = memory.is_procedure_satisfied(mock_page)
        self.assertTrue(sat)
        self.assertIn("completed successfully", reason)

    def test_wikipedia_entry_portal_types_search_query_before_candidate_selection(self):
        """On platform entry portal, search query must be typed rather than clicking unrelated candidate links."""
        task = "Go to Wikipedia and find the capital of India."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task, task_plan=plan)

        mock_page = MagicMock()
        mock_page.url = "https://www.wikipedia.org/"
        mock_page.title.return_value = "Wikipedia"
        mock_page.evaluate.return_value = ""

        elements = [
            ElementInfo(id=1, tag="input", role="combobox", text="", attributes={"id": "searchInput", "name": "search", "type": "search"}),
            ElementInfo(id=2, tag="button", role="button", text="Search", attributes={"type": "submit"}),
            ElementInfo(id=3, tag="a", role="link", text="English", attributes={"href": "//en.wikipedia.org/"}),
            ElementInfo(id=4, tag="a", role="link", text="Español", attributes={"href": "//es.wikipedia.org/"}),
        ]

        action = choose_goal_exploration_action(mock_page, elements, memory)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "type")
        self.assertEqual(action["element_id"], 1)
        self.assertEqual(action["text"], "India")
        self.assertTrue(action.get("press_enter"))


if __name__ == "__main__":
    unittest.main()
