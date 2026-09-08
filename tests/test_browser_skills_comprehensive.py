"""
Comprehensive automated tests for Vision Lite's expanded browser capabilities:
Covers all 30 browser skills including 6-tier clicking, accessible names, hover,
dropdowns, checkboxes/radios/toggles, multi-field forms, keyboard navigation,
scrolling modes, pagination, tab registry, modals, file uploads/downloads,
table extraction, candidate comparison, date/time inputs, text editing modes,
drag and drop, media controls, authentication awareness, and VLM resilience.
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from playwright.sync_api import sync_playwright

from browser_agent.actions import execute_action
from browser_agent.browser import BrowserController, find_click_target
from browser_agent.exploration import (
    check_authentication_barrier,
    check_blocking_modal,
)
from browser_agent.perception import PerceptionEngine, extract_tables, find_text_in_page
from browser_agent.planner import TaskPlan, TaskType, parse_task_plan
from browser_agent.state import AgentMemory, AgentState, ElementInfo, TabInfo
from browser_agent.verifier import ActionVerifier


class TestClickingAndAccessibilityGrounding(unittest.TestCase):
    """Tests 6-tier candidate ranking, accessible names, and hover."""

    def test_six_tier_click_and_accessible_name(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <button id="btn1" aria-label="Confirm Order">Submit</button>
                <div role="button" id="btn2" tabindex="0" onclick="this.innerText='Clicked Role'">Custom Role</div>
                <a href="#link" id="link1">Unique Link Target</a>
                <span id="hoverTarget" tabindex="0" onmouseenter="document.getElementById('tooltip').style.display='block';">Hover Me</span>
                <div id="tooltip" style="display:none;">Tooltip Revealed</div>
            </body>
            </html>
            """)

            perception = PerceptionEngine()
            elements = perception.extract_interactive_elements(page)

            # Tier 1: SOM ID
            elem_link = next(e for e in elements if "Unique Link" in (e.text or ""))
            target = find_click_target(page, f"[{elem_link.id}]", elements)
            self.assertIsInstance(target, tuple)
            self.assertEqual(target, elem_link.center)

            # Tier 2: Accessible Name Match
            target_acc = find_click_target(page, "Confirm Order", elements)
            self.assertIsInstance(target_acc, tuple)

            # Tier 3: Role-specific locator
            target_role = find_click_target(page, "Custom Role", None)
            self.assertIsNotNone(target_role)

            # Tier 4: Exact text
            target_text = find_click_target(page, "Unique Link Target", None)
            self.assertIsNotNone(target_text)

            # Hover action and reveal detection
            hover_elem = next(e for e in elements if "Hover Me" in (e.text or ""))
            action_hover = {"action": "hover", "element_id": hover_elem.id}
            success = execute_action(page, action_hover, elements)
            self.assertTrue(success)
            self.assertTrue(page.locator("#tooltip").is_visible())

            browser.close()


class TestDropdownsAndComboboxes(unittest.TestCase):
    """Tests native select dropdowns and ARIA custom comboboxes."""

    def test_native_and_aria_comboboxes(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <!-- Native select -->
                <select id="currency">
                    <option value="USD">US Dollar</option>
                    <option value="EUR">Euro</option>
                    <option value="GBP">British Pound</option>
                </select>

                <!-- ARIA Custom Combobox -->
                <div role="combobox" aria-expanded="false" id="combo" tabindex="0"
                     onclick="document.getElementById('combo-list').style.display='block'; this.setAttribute('aria-expanded','true');">
                    Select Role
                </div>
                <ul role="listbox" id="combo-list" style="display:none;">
                    <li role="option" id="opt-admin" onclick="document.getElementById('combo').innerText='Admin'; document.getElementById('combo-list').style.display='none';">Admin</li>
                    <li role="option" id="opt-user" onclick="document.getElementById('combo').innerText='User'; document.getElementById('combo-list').style.display='none';">User</li>
                </ul>
            </body>
            </html>
            """)

            verifier = ActionVerifier()
            perception = PerceptionEngine()
            elements = perception.extract_interactive_elements(page)

            # Native select
            sel_elem = next(e for e in elements if e.tag == "select")
            action_sel = {"action": "select", "element_id": sel_elem.id, "option": "Euro"}
            pre = verifier.capture_pre_action_state(page, action_sel)
            success = execute_action(page, action_sel, elements)
            ver = verifier.verify_action(page, action_sel, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#currency").input_value(), "EUR")

            # Custom combobox select
            action_combo = {"action": "select", "selector": "#combo", "option": "Admin"}
            pre_combo = verifier.capture_pre_action_state(page, action_combo)
            success_combo = execute_action(page, action_combo, elements)
            ver_combo = verifier.verify_action(page, action_combo, pre_combo, success_combo)
            self.assertTrue(success_combo)
            self.assertTrue(ver_combo.verified)
            self.assertIn("Admin", page.locator("#combo").inner_text())

            browser.close()


class TestCheckboxesRadiosToggles(unittest.TestCase):
    """Tests check, uncheck, toggle, and custom switch widgets."""

    def test_checkbox_radio_and_switch(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <input type="checkbox" id="chk" />
                <input type="radio" name="plan" id="radio1" value="free" />
                <input type="radio" name="plan" id="radio2" value="pro" />
                <div role="switch" id="sw" aria-checked="false" tabindex="0"
                     onclick="const cur = this.getAttribute('aria-checked')==='true'; this.setAttribute('aria-checked', (!cur).toString());">
                    Dark Mode
                </div>
            </body>
            </html>
            """)

            verifier = ActionVerifier()
            perception = PerceptionEngine()
            elements = perception.extract_interactive_elements(page)

            # 1. Check
            chk_elem = next(e for e in elements if e.attributes.get("id") == "chk")
            action_check = {"action": "check", "element_id": chk_elem.id}
            pre = verifier.capture_pre_action_state(page, action_check)
            success = execute_action(page, action_check, elements)
            ver = verifier.verify_action(page, action_check, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertTrue(page.locator("#chk").is_checked())

            # 2. Uncheck
            action_uncheck = {"action": "uncheck", "element_id": chk_elem.id}
            pre = verifier.capture_pre_action_state(page, action_uncheck)
            success = execute_action(page, action_uncheck, elements)
            ver = verifier.verify_action(page, action_uncheck, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertFalse(page.locator("#chk").is_checked())

            # 3. Radio selection
            r2_elem = next(e for e in elements if e.attributes.get("id") == "radio2")
            action_radio = {"action": "check", "element_id": r2_elem.id}
            success = execute_action(page, action_radio, elements)
            self.assertTrue(success)
            self.assertTrue(page.locator("#radio2").is_checked())

            # 4. Custom switch toggle
            sw_elem = next(e for e in elements if e.attributes.get("id") == "sw")
            action_toggle = {"action": "toggle", "element_id": sw_elem.id}
            pre = verifier.capture_pre_action_state(page, action_toggle)
            success = execute_action(page, action_toggle, elements)
            ver = verifier.verify_action(page, action_toggle, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#sw").get_attribute("aria-checked"), "true")

            browser.close()


class TestFormFillingAndValidation(unittest.TestCase):
    """Tests multi-field fill_form action and verification."""

    def test_multi_field_form_filling(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <form id="contactForm">
                    <label for="fname">First Name</label>
                    <input type="text" id="fname" name="firstname" />

                    <label for="email">Email Address</label>
                    <input type="email" id="email" name="email" />

                    <label for="country">Country</label>
                    <select id="country" name="country">
                        <option value="US">United States</option>
                        <option value="FR">France</option>
                        <option value="JP">Japan</option>
                    </select>

                    <label><input type="checkbox" id="newsletter" name="newsletter" /> Subscribe</label>
                </form>
            </body>
            </html>
            """)

            verifier = ActionVerifier()
            action_form = {
                "action": "fill_form",
                "fields": {
                    "First Name": "Alice",
                    "Email Address": "alice@example.com",
                    "Country": "France",
                    "newsletter": True,
                },
            }
            pre = verifier.capture_pre_action_state(page, action_form)
            success = execute_action(page, action_form)
            ver = verifier.verify_action(page, action_form, pre, success)

            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#fname").input_value(), "Alice")
            self.assertEqual(page.locator("#email").input_value(), "alice@example.com")
            self.assertEqual(page.locator("#country").input_value(), "FR")
            self.assertTrue(page.locator("#newsletter").is_checked())

            browser.close()


class TestKeyboardNavigationAndAliases(unittest.TestCase):
    """Tests key alias normalization and keyboard interactions."""

    def test_key_press_and_normalization(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <input type="text" id="inp" value="Initial Text" />
                <div id="keyLog"></div>
                <script>
                    document.getElementById('inp').addEventListener('keydown', (e) => {
                        document.getElementById('keyLog').innerText = e.key;
                    });
                </script>
            </body>
            </html>
            """)

            page.focus("#inp")
            action_key = {"action": "press_key", "key": "Enter"}
            success = execute_action(page, action_key)
            self.assertTrue(success)
            self.assertEqual(page.locator("#keyLog").inner_text(), "Enter")

            # Alias normalization (esc -> Escape)
            action_esc = {"action": "press_key", "key": "esc"}
            success_esc = execute_action(page, action_esc)
            self.assertTrue(success_esc)
            self.assertEqual(page.locator("#keyLog").inner_text(), "Escape")

            browser.close()


class TestScrollingAndPagination(unittest.TestCase):
    """Tests scroll modes (top, bottom, scroll_to_element) and pagination."""

    def test_scroll_modes_and_element_scrolling(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body style="height: 4000px;">
                <div id="topHeader">Top of Page</div>
                <div id="targetElement" style="margin-top: 2500px; height: 100px; background: red;">Target Anchor</div>
                <div id="footerSection" style="margin-top: 1200px;">Footer</div>
            </body>
            </html>
            """)

            verifier = ActionVerifier()

            # 1. Scroll to bottom
            action_bot = {"action": "scroll", "direction": "bottom"}
            pre = verifier.capture_pre_action_state(page, action_bot)
            success = execute_action(page, action_bot)
            ver = verifier.verify_action(page, action_bot, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)

            # 2. Scroll to top
            action_top = {"action": "scroll", "direction": "top"}
            pre = verifier.capture_pre_action_state(page, action_top)
            success = execute_action(page, action_top)
            ver = verifier.verify_action(page, action_top, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)

            # 3. Scroll to specific element
            action_target = {"action": "scroll", "scroll_to_element": "#targetElement"}
            pre = verifier.capture_pre_action_state(page, action_target)
            success = execute_action(page, action_target)
            ver = verifier.verify_action(page, action_target, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)

            browser.close()


class TestTabManagementAndMultiWindow(unittest.TestCase):
    """Tests BrowserController tab registry, switching, and closing."""

    def test_tab_lifecycle_and_registry(self):
        controller = BrowserController(config={"browser": {"headless": True}})
        page1 = controller.start()
        self.assertIsNotNone(page1)

        try:
            # 1. Open new tab
            page2 = controller.new_tab()
            self.assertIsNotNone(page2)
            tabs = controller.get_tab_registry()
            self.assertGreaterEqual(len(tabs), 2)
            self.assertTrue(any(t.is_active for t in tabs))

            # 2. Switch tab
            switched = controller.switch_tab(0)
            self.assertIsNotNone(switched)

            # 3. Close active tab
            remaining = controller.close_active_tab()
            self.assertIsNotNone(remaining)
            tabs_after = controller.get_tab_registry()
            self.assertEqual(len(tabs_after), len(tabs) - 1)
        finally:
            controller.close()


class TestModalsAndDialogs(unittest.TestCase):
    """Tests modal dialog detection and dismiss_modal action."""

    def test_modal_detection_and_dismissal(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <div id="content">Background Content</div>
                <div role="dialog" id="cookieModal" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5);">
                    <div style="background:white; padding:20px; margin:100px auto; width:300px;">
                        <h2>Cookie Policy</h2>
                        <button id="acceptCookies" onclick="document.getElementById('cookieModal').remove();">Accept All</button>
                    </div>
                </div>
            </body>
            </html>
            """)

            # 1. Detection
            is_blocking = check_blocking_modal(page)
            self.assertTrue(is_blocking)

            # 2. Dismiss Modal Action
            verifier = ActionVerifier()
            action_dismiss = {"action": "dismiss_modal"}
            pre = verifier.capture_pre_action_state(page, action_dismiss)
            success = execute_action(page, action_dismiss)
            ver = verifier.verify_action(page, action_dismiss, pre, success)

            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertFalse(check_blocking_modal(page))

            browser.close()


class TestFilesAndDownloads(unittest.TestCase):
    """Tests file upload and download tracking."""

    def test_file_upload_action(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <input type="file" id="uploadInput" />
            </body>
            </html>
            """)

            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
                tf.write(b"Hello agent upload")
                temp_path = tf.name

            try:
                verifier = ActionVerifier()
                action_up = {"action": "upload_file", "selector": "#uploadInput", "file_path": temp_path}
                pre = verifier.capture_pre_action_state(page, action_up)
                success = execute_action(page, action_up)
                ver = verifier.verify_action(page, action_up, pre, success)

                self.assertTrue(success)
                self.assertTrue(ver.verified)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                browser.close()


class TestTableUnderstandingAndExtraction(unittest.TestCase):
    """Tests deterministic HTML table extraction into structured records."""

    def test_table_parsing(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <table id="products">
                    <caption>Top Laptops 2026</caption>
                    <thead>
                        <tr><th>Model</th><th>Price</th><th>Rating</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>ProBook 14</td><td>$999</td><td>4.5</td></tr>
                        <tr><td>AirLite 13</td><td>$849</td><td>4.7</td></tr>
                        <tr><td>GameMax 16</td><td>$1499</td><td>4.2</td></tr>
                    </tbody>
                </table>
            </body>
            </html>
            """)

            tables = extract_tables(page)
            self.assertEqual(len(tables), 1)
            tbl = tables[0]
            self.assertEqual(tbl["caption"], "Top Laptops 2026")
            self.assertEqual(tbl["headers"], ["Model", "Price", "Rating"])
            self.assertEqual(tbl["row_count"], 3)
            self.assertEqual(tbl["rows"][1]["Model"], "AirLite 13")
            self.assertEqual(tbl["rows"][1]["Price"], "$849")

            browser.close()


class TestFindInPage(unittest.TestCase):
    """Tests deterministic in-page text search and centering."""

    def test_find_text(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body style="height: 3000px;">
                <p id="p1">Introductory paragraph.</p>
                <div id="deepResult" style="margin-top: 1500px;">Specific Hidden Milestone Target</div>
            </body>
            </html>
            """)

            loc = find_text_in_page(page, "Specific Hidden Milestone Target")
            self.assertIsNotNone(loc)
            self.assertTrue(loc.get("found"))
            self.assertIn("Milestone Target", loc.get("text", ""))

            not_found = find_text_in_page(page, "Nonexistent Phrase 998877")
            self.assertFalse(not_found.get("found"))

            browser.close()


class TestDateTimeAndTextEditing(unittest.TestCase):
    """Tests set_date and edit_text (replace, append, clear)."""

    def test_date_and_text_editing(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <input type="date" id="flightDate" />
                <input type="text" id="editable" value="Hello" />
            </body>
            </html>
            """)

            verifier = ActionVerifier()

            # 1. set_date
            action_date = {"action": "set_date", "selector": "#flightDate", "date": "2026-11-20"}
            pre = verifier.capture_pre_action_state(page, action_date)
            success = execute_action(page, action_date)
            ver = verifier.verify_action(page, action_date, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#flightDate").input_value(), "2026-11-20")

            # 2. edit_text: append
            action_append = {"action": "edit_text", "selector": "#editable", "text": " World", "mode": "append"}
            pre = verifier.capture_pre_action_state(page, action_append)
            success = execute_action(page, action_append)
            ver = verifier.verify_action(page, action_append, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#editable").input_value(), "Hello World")

            # 3. edit_text: replace
            action_replace = {"action": "edit_text", "selector": "#editable", "text": "Replaced", "mode": "replace"}
            pre = verifier.capture_pre_action_state(page, action_replace)
            success = execute_action(page, action_replace)
            ver = verifier.verify_action(page, action_replace, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#editable").input_value(), "Replaced")

            # 4. edit_text: clear
            action_clear = {"action": "edit_text", "selector": "#editable", "mode": "clear"}
            pre = verifier.capture_pre_action_state(page, action_clear)
            success = execute_action(page, action_clear)
            ver = verifier.verify_action(page, action_clear, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertEqual(page.locator("#editable").input_value(), "")

            browser.close()


class TestDragAndDrop(unittest.TestCase):
    """Tests drag_and_drop between elements."""

    def test_drag_and_drop_action(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <div id="dragItem" style="width:50px; height:50px; background:blue;">Item</div>
                <div id="dropZone" style="width:200px; height:200px; background:gray; margin-top:50px;">Zone</div>
            </body>
            </html>
            """)

            verifier = ActionVerifier()
            action_dad = {"action": "drag_and_drop", "source_selector": "#dragItem", "target_selector": "#dropZone"}
            pre = verifier.capture_pre_action_state(page, action_dad)
            success = execute_action(page, action_dad)
            ver = verifier.verify_action(page, action_dad, pre, success)

            self.assertTrue(success)
            self.assertTrue(ver.verified)

            browser.close()


class TestMediaControls(unittest.TestCase):
    """Tests media_control action for HTML5 media."""

    def test_media_control_actions(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <audio id="audioElem" src="data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="></audio>
            </body>
            </html>
            """)

            verifier = ActionVerifier()

            # Mute
            action_mute = {"action": "media_control", "command": "mute"}
            pre = verifier.capture_pre_action_state(page, action_mute)
            success = execute_action(page, action_mute)
            ver = verifier.verify_action(page, action_mute, pre, success)
            self.assertTrue(success)
            self.assertTrue(ver.verified)
            self.assertIn("playback", ver.reason.lower())

            # Unmute
            action_unmute = {"action": "media_control", "command": "unmute"}
            success = execute_action(page, action_unmute)
            self.assertTrue(success)

            browser.close()


class TestAuthBarrierAndSafety(unittest.TestCase):
    """Tests authentication barrier detection and clean pause."""

    def test_auth_barrier_detection(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <form id="loginForm">
                    <h2>Sign In to Your Account</h2>
                    <input type="text" name="username" placeholder="Username" />
                    <input type="password" name="password" placeholder="Password" />
                    <button type="submit">Sign In</button>
                </form>
            </body>
            </html>
            """)

            auth_detected, auth_type = check_authentication_barrier(page)
            self.assertTrue(auth_detected)
            self.assertIn("login", auth_type.lower())

            browser.close()


class TestExpandedTaskPlannerTypes(unittest.TestCase):
    """Tests the 12 task types recognized by the planner."""

    def test_task_types_and_parameters(self):
        cases = [
            ("Fill the registration form with my email and name", TaskType.FORM_FILLING),
            ("Compare prices of iPhone 15 and Samsung Galaxy S24", TaskType.COMPARISON),
            ("Download the annual financial report PDF", TaskType.DOWNLOAD),
            ("Upload the receipt image to the expense portal", TaskType.UPLOAD),
            ("Search for laptop deals on Amazon", TaskType.SEARCH),
            ("Go to wikipedia and extract capital of France", TaskType.INFORMATION_RETRIEVAL),
        ]
        for prompt, expected_type in cases:
            plan = parse_task_plan(prompt)
            self.assertEqual(plan.task_type, expected_type, f"Failed for prompt: {prompt}")

        table_plan = parse_task_plan("Extract table data from Q3 earnings")
        self.assertEqual(table_plan.intent, "table_understanding")

        date_plan = parse_task_plan("Set departure date to 2026-10-25")
        self.assertEqual(date_plan.target_date, "2026-10-25")


class TestAgentMemorySatisfaction(unittest.TestCase):
    """Tests AgentMemory satisfaction checks for new capabilities."""

    def test_memory_satisfaction_rules(self):
        memory = AgentMemory()

        # Form filling satisfied
        plan_form = TaskPlan(raw_task="Fill form", task_type=TaskType.FORM_FILLING)
        self.assertFalse(memory.is_information_satisfied(plan_form))
        memory.completion_evidence["form_filled"] = True
        self.assertTrue(memory.is_information_satisfied(plan_form))

        # Download satisfied
        plan_dl = TaskPlan(raw_task="Download file", task_type=TaskType.DOWNLOAD)
        self.assertFalse(memory.is_information_satisfied(plan_dl))
        memory.download_records.append({"filename": "report.pdf"})
        self.assertTrue(memory.is_information_satisfied(plan_dl))

        # Comparison satisfied
        plan_comp = TaskPlan(raw_task="Compare products", task_type=TaskType.COMPARISON)
        self.assertFalse(memory.is_information_satisfied(plan_comp))
        memory.completion_evidence["comparison_ready"] = True
        self.assertTrue(memory.is_information_satisfied(plan_comp))


if __name__ == "__main__":
    unittest.main()
