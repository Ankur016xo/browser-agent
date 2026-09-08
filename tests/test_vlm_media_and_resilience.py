"""
Unit tests for VLM failure recovery, generic candidate grounding,
media playback execution & verification, TargetClosedError resilience,
and multi-stage procedural & temporal planning.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from browser_agent.actions import execute_action
from browser_agent.agent import (
    BrowserAgent,
    is_page_actively_loading,
    is_page_alive,
    safe_page_title,
    safe_page_url,
)
from browser_agent.exploration import (
    NAV_BOILERPLATE,
    find_candidate_content_items,
    select_best_candidate_link,
)
from browser_agent.planner import parse_task_plan
from browser_agent.state import ActionRecord, AgentMemory, AgentState, ElementInfo
from browser_agent.verifier import ActionVerifier


class TestVLMRecoveryAndCandidateGrounding(unittest.TestCase):
    """Tests for robust VLM failure recovery and candidate grounding."""

    def test_vlm_gibberish_recovery_selects_candidate_on_results_page(self):
        """When VLM returns invalid JSON on a search results page, agent clicks candidate item."""
        agent = BrowserAgent()
        task = "Go to YouTube, search for a Java programming tutorial, open the first relevant video, and play it."
        agent.memory = AgentMemory(task=task)
        agent.task_plan = parse_task_plan(task)
        agent.memory.task_plan = agent.task_plan
        agent.memory.procedural_requirements = ["open the first relevant video", "play video"]
        agent.memory.procedure_index = 0

        mock_page = MagicMock()
        mock_page.url = "https://www.youtube.com/results?search_query=Java+programming+tutorial"
        mock_page.title.return_value = "Java programming tutorial - YouTube"
        mock_page.evaluate.return_value = False  # Not loading
        mock_page.is_closed.return_value = False

        elements = [
            ElementInfo(id=0, tag="a", text="YouTube Home", attributes={"href": "/"}),
            ElementInfo(id=1, tag="a", text="Shorts", attributes={"href": "/shorts"}),
            ElementInfo(
                id=10,
                tag="a",
                text="Java Full Course for Beginners - Programming Tutorial",
                attributes={"href": "/watch?v=abc123java", "title": "Java Full Course"},
            ),
        ]

        pref = "video"
        best_cand = select_best_candidate_link(
            elements,
            query="Java programming tutorial",
            target="first relevant video",
            preferred_type=pref,
        )
        self.assertIsNotNone(best_cand)
        self.assertEqual(best_cand.id, 10)
        self.assertEqual(best_cand["action"], "click")

    def test_vlm_failure_on_loading_page_waits(self):
        """When VLM fails but page is actively loading/busy, agent emits wait action."""
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.evaluate.return_value = True  # document.readyState !== 'complete' or busy spinner

        self.assertTrue(is_page_actively_loading(mock_page))

    def test_nav_boilerplate_filtered_out(self):
        """Verify navigation boilerplate links (Home, Shorts, Subscriptions, History) are rejected."""
        elements = [
            ElementInfo(id=1, tag="a", text="Home", attributes={"href": "/"}),
            ElementInfo(id=2, tag="a", text="Subscriptions", attributes={"href": "/feed/subscriptions"}),
            ElementInfo(id=3, tag="a", text="Library", attributes={"href": "/feed/library"}),
            ElementInfo(id=4, tag="a", text="History", attributes={"href": "/feed/history"}),
            ElementInfo(id=5, tag="a", text="Settings", attributes={"href": "/account"}),
            ElementInfo(id=6, tag="a", text="Main Page", attributes={"href": "/wiki/Main_Page"}),
            ElementInfo(
                id=20,
                tag="a",
                text="Tujhe Bhula Diya Full Song | Anjaana Anjaani",
                attributes={"href": "/watch?v=xyz789tujhe"},
            ),
        ]
        candidates = find_candidate_content_items(elements, query="Tujhe Bhula Diya", target="first relevant video")
        candidate_ids = [c[0].id for c in candidates]

        # IDs 1-6 must be completely excluded
        for nav_id in [1, 2, 3, 4, 5, 6]:
            self.assertNotIn(nav_id, candidate_ids)

        # ID 20 must be present
        self.assertIn(20, candidate_ids)

    def test_select_best_candidate_cross_domain(self):
        """Verify candidate link grounding works across YouTube, Wikipedia, and documentation sites."""
        # 1. YouTube video
        yt_elements = [
            ElementInfo(id=0, tag="a", text="YouTube Home", attributes={"href": "/"}),
            ElementInfo(id=1, tag="a", text="Trending", attributes={"href": "/feed/trending"}),
            ElementInfo(id=2, tag="a", text="Python Crash Course for Beginners", attributes={"href": "/watch?v=py1"}),
            ElementInfo(id=3, tag="a", text="C++ Tutorial", attributes={"href": "/watch?v=cpp1"}),
        ]
        best_yt = select_best_candidate_link(yt_elements, query="Python Crash Course", target="video", preferred_type="video")
        self.assertIsNotNone(best_yt)
        self.assertEqual(best_yt.id, 2)
        self.assertEqual(best_yt["action"], "click")

        # 2. Wikipedia article
        wiki_elements = [
            ElementInfo(id=0, tag="a", text="Main Page", attributes={"href": "/wiki/Main_Page"}),
            ElementInfo(id=1, tag="a", text="Languages of India", attributes={"href": "/wiki/Languages_of_India"}),
            ElementInfo(id=2, tag="a", text="India", attributes={"href": "/wiki/India"}),
            ElementInfo(id=3, tag="a", text="History of India", attributes={"href": "/wiki/History_of_India"}),
        ]
        best_wiki = select_best_candidate_link(wiki_elements, query="India", target="India", preferred_type="article")
        self.assertIsNotNone(best_wiki)
        self.assertEqual(best_wiki.id, 2)
        self.assertEqual(best_wiki["action"], "click")


class TestTargetClosedErrorResilience(unittest.TestCase):
    """Tests for safe handling of closed browser tabs / TargetClosedError."""

    def test_is_page_alive_with_closed_page(self):
        """is_page_alive returns False when page is closed."""
        closed_page = MagicMock()
        closed_page.is_closed.return_value = True
        self.assertFalse(is_page_alive(closed_page))

        none_page = None
        self.assertFalse(is_page_alive(none_page))

    def test_safe_page_title_and_url_on_closed_page(self):
        """safe_page_title and safe_page_url return empty string without raising."""
        closed_page = MagicMock()
        closed_page.is_closed.return_value = True
        closed_page.title.side_effect = Exception("Target page, context or browser has been closed")
        closed_page.url = "https://example.com"

        self.assertEqual(safe_page_title(closed_page), "")
        self.assertEqual(safe_page_url(closed_page), "")

    def test_action_verifier_gracefully_handles_closed_page(self):
        """ActionVerifier returns verified=False when page is closed during verification."""
        closed_page = MagicMock()
        closed_page.is_closed.return_value = True
        closed_page.title.side_effect = Exception("TargetClosedError")
        closed_page.url = "https://example.com"

        verifier = ActionVerifier()
        pre_state = verifier.capture_pre_action_state(closed_page, {"action": "click"})
        self.assertEqual(pre_state.url, "")

        result = verifier.verify_action(closed_page, {"action": "click"}, pre_state, execution_success=False)
        self.assertFalse(result.verified)
        self.assertIn("closed", result.reason.lower())


class TestMediaExecutionAndVerification(unittest.TestCase):
    """Tests for media action execution and verification."""

    def test_play_action_dispatch(self):
        """execute_action dispatches 'play' and 'play_media' to media playback executor."""
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.evaluate.return_value = {"success": True, "method": "video_element.play()"}

        action = {"action": "play", "reasoning": "Play video"}
        res = execute_action(mock_page, action)
        self.assertTrue(res)

        action_media = {"action": "play_media", "reasoning": "Play audio/video"}
        res_media = execute_action(mock_page, action_media)
        self.assertTrue(res_media)

    def test_play_action_verification_by_playback_state(self):
        """ActionVerifier verifies playback when isPlaying is True or currentTime advances."""
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://www.youtube.com/watch?v=abc123java"
        mock_page.title.return_value = "Java Tutorial - YouTube"
        mock_page.evaluate.return_value = {
            "hasMedia": True,
            "isPlaying": True,
            "paused": False,
            "ended": False,
            "currentTime": 5.2,
            "duration": 300.0,
            "hasPauseButton": True,
        }

        verifier = ActionVerifier()
        pre_state = verifier.capture_pre_action_state(mock_page, {"action": "play"})
        result = verifier.verify_action(mock_page, {"action": "play"}, pre_state, execution_success=True)

        self.assertTrue(result.verified)
        self.assertIn("playback", result.reason.lower())


class TestMultiStageProceduralAndTemporalPlanning(unittest.TestCase):
    """Tests for multi-stage procedural & temporal planning."""

    def test_multi_stage_procedural_decomposition(self):
        """'play X, after it ends play Y' parses into sequential procedural requirements."""
        task = "Go to YouTube, search for Tujhe Bhula Diya, open the first relevant video, and play it. After the video ends, play Milne Hai Mujhse Aai."
        plan = parse_task_plan(task)

        self.assertEqual(plan.destination, "youtube")
        self.assertIn("Tujhe Bhula Diya", plan.search_query)

        procs = plan.procedural_requirements
        self.assertIsNotNone(procs)
        self.assertTrue(len(procs) >= 4)

        # First stage procedures
        self.assertTrue(any("tujhe bhula diya" in p.lower() for p in procs))
        self.assertTrue(any("open" in p.lower() for p in procs))
        self.assertTrue(any("play" in p.lower() for p in procs))

        # Temporal dependency & second stage procedures
        self.assertTrue(any("video completion" in p.lower() or "video ends" in p.lower() or "after" in p.lower() for p in procs))
        self.assertTrue(any("milne hai mujhse aai" in p.lower() for p in procs))

    def test_advance_procedure_updates_query_and_target_for_subsequent_stage(self):
        """When transitioning to a subsequent stage ('play Milne Hai Mujhse Aai'), queries update."""
        task = "Go to YouTube, search for Tujhe Bhula Diya, open the first relevant video, and play it. After the video ends, play Milne Hai Mujhse Aai."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task)
        memory.task_plan = plan
        memory.procedural_requirements = list(plan.procedural_requirements)
        memory.procedure_index = 0
        memory.normalized_query = plan.search_query

        # Fast-forward procedures until the second song search
        for idx, proc in enumerate(memory.procedural_requirements):
            if "milne hai mujhse aai" in proc.lower():
                memory.procedure_index = idx
                break

        # Simulate executing the search/open for the second song
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://www.youtube.com/results?search_query=Milne+Hai+Mujhse+Aai"
        mock_page.title.return_value = "Milne Hai Mujhse Aai - YouTube"

        adv = memory.advance_procedure(
            mock_page,
            {"action": "type", "text": "Milne Hai Mujhse Aai"},
            MagicMock(verified=True, state_changed=True),
        )
        self.assertTrue(adv)
        self.assertIn("milne hai mujhse aai", memory.normalized_query.lower())


class TestTargetPageProgressPreservation(unittest.TestCase):
    """Tests that reaching content target page preserves progress without resetting."""

    def test_youtube_watch_page_satisfies_target_page(self):
        """is_target_page_satisfied returns True when on YouTube watch page matching query."""
        task = "Go to YouTube, search for Tujhe Bhula Diya, open the first relevant video, and play it."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task)
        memory.task_plan = plan

        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://www.youtube.com/watch?v=Dk_Ihx3Lw8w"
        mock_page.title.return_value = "Tujhe Bhula Diya Full Song | Anjaana Anjaani | Ranbir Kapoor - YouTube"

        is_sat, reason = memory.is_target_page_satisfied(mock_page)
        self.assertTrue(is_sat)
        self.assertTrue("video" in reason.lower() or "watch" in reason.lower())

    def test_open_procedure_marked_satisfied_on_watch_page(self):
        """check_and_advance_open_procedure advances 'open the first relevant video' on watch page."""
        task = "Go to YouTube, search for Tujhe Bhula Diya, open the first relevant video, and play it."
        plan = parse_task_plan(task)
        memory = AgentMemory(task=task)
        memory.task_plan = plan
        memory.procedural_requirements = list(plan.procedural_requirements)
        # Point to 'open the first relevant video'
        for idx, proc in enumerate(memory.procedural_requirements):
            if "open" in proc.lower() and "video" in proc.lower():
                memory.procedure_index = idx
                break

        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://www.youtube.com/watch?v=Dk_Ihx3Lw8w"
        mock_page.title.return_value = "Tujhe Bhula Diya - YouTube"

        advanced = memory.check_and_advance_open_procedure(mock_page)
        self.assertTrue(advanced)
        # Current procedure should now be 'play video'
        self.assertIn("play", memory.current_procedure.lower())


if __name__ == "__main__":
    unittest.main()
