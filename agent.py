from ollama import chat
from playwright.sync_api import sync_playwright
import json
import re
import time


# ============================================================
# SETTINGS
# ============================================================

MODEL = "qwen2.5vl:3b"

MAX_STEPS = 10

SCREENSHOT_PATH = "agent_screen.png"


# ============================================================
# CLEAN AI JSON
# ============================================================

def clean_json(text):

    text = text.strip()

    # Remove markdown code fences
    text = re.sub(r"```(?:json)?", "", text)
    text = text.replace("```", "").strip()

    # Find the first JSON object
    match = re.search(
        r"\{.*\}",
        text,
        re.DOTALL
    )

    if not match:

        raise ValueError(
            f"AI did not return JSON:\n{text}"
        )

    return json.loads(
        match.group(0)
    )


# ============================================================
# GET VISIBLE PAGE INFORMATION
# ============================================================

def get_page_links(page):

    links = []

    try:

        elements = page.locator(
            "a:visible"
        ).all()

        for element in elements:

            try:

                text = element.inner_text().strip()

                href = element.get_attribute(
                    "href"
                )

                if not text:
                    continue

                if len(text) > 150:
                    continue

                links.append(
                    {
                        "text": text,
                        "href": href
                    }
                )

            except Exception:

                pass

    except Exception:

        pass

    # Remove duplicates
    unique = []

    seen = set()

    for link in links:

        key = (
            link["text"],
            link["href"]
        )

        if key in seen:
            continue

        seen.add(key)

        unique.append(link)

    return unique[:30]


# ============================================================
# GET VISIBLE BUTTONS
# ============================================================

def get_page_buttons(page):

    buttons = []

    try:

        elements = page.locator(
            "button:visible"
        ).all()

        for element in elements:

            try:

                text = element.inner_text().strip()

                if not text:
                    continue

                if len(text) > 100:
                    continue

                buttons.append(text)

            except Exception:

                pass

    except Exception:

        pass

    return buttons[:20]


# ============================================================
# BUILD PAGE CONTEXT
# ============================================================

def get_page_context(page):

    links = get_page_links(page)

    buttons = get_page_buttons(page)

    link_text = "\n".join(
        f"{i}. {link['text']}"
        for i, link in enumerate(
            links,
            start=1
        )
    )

    button_text = "\n".join(
        f"- {button}"
        for button in buttons
    )

    context = f"""
CURRENT URL:
{page.url}

CURRENT PAGE TITLE:
{page.title()}

VISIBLE LINKS:
{link_text}

VISIBLE BUTTONS:
{button_text}
"""

    return context, links


# ============================================================
# ASK QWEN FOR NEXT ACTION
# ============================================================

def ask_qwen(
    task,
    page,
    screenshot
):

    context, links = get_page_context(
        page
    )

    response = chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": f"""
You are controlling a web browser.

USER TASK:
{task}

CURRENT BROWSER STATE:
{context}

Look at the screenshot carefully.

Decide the SINGLE best action to perform next.

You may ONLY return one of these actions.

--------------------------------------------------

TYPE

Use this when text needs to be entered.

Example:

{{"action":"type","target":"search box","text":"Elden Ring"}}

--------------------------------------------------

CLICK

Use this when a visible button, link, menu,
or other clickable element should be clicked.

Example:

{{"action":"click","target":"Elden Ring"}}

The target should describe the visible element
as accurately as possible.

--------------------------------------------------

SCROLL

Use this when the required element is not currently
visible.

Example:

{{"action":"scroll","direction":"down","amount":600}}

Allowed directions:

"up"
"down"

--------------------------------------------------

PRESS_KEY

Use this for keyboard actions.

Example:

{{"action":"press_key","key":"Enter"}}

Other examples:

{{"action":"press_key","key":"Escape"}}

{{"action":"press_key","key":"Tab"}}

--------------------------------------------------

WAIT

Use this when the page is loading or needs time.

Example:

{{"action":"wait","seconds":2}}

--------------------------------------------------

DONE

Use this ONLY when the user's task is clearly complete.

Example:

{{"action":"done"}}

--------------------------------------------------

IMPORTANT RULES

1. Return ONLY ONE JSON object.

2. Do not explain your reasoning.

3. Do not invent elements that are not visible.

4. If a visible link matches the task, prefer clicking it.

5. If the page needs scrolling before the target is visible,
   use scroll.

6. Do not claim DONE merely because the page looks relevant.

7. The task must actually be completed.

8. Use the actual visible text when possible.

9. For clicks, choose an element that exists in the
   visible page.

10. If the current page is a search-results page,
    inspect the visible results before choosing.

Return ONLY JSON.
""",
                "images": [
                    screenshot
                ]
            }
        ]
    )

    print()
    print(
        "RAW QWEN RESPONSE:"
    )

    print(
        repr(
            response.message.content
        )
    )

    return clean_json(
        response.message.content
    ), links


# ============================================================
# FIND CLICKABLE ELEMENT
# ============================================================

def find_click_target(
    page,
    target
):

    target = target.strip()

    # --------------------------------------------------------
    # Exact link match
    # --------------------------------------------------------

    locator = page.get_by_role(
        "link",
        name=target,
        exact=True
    ).first

    try:

        if locator.is_visible(
            timeout=1000
        ):

            return locator

    except Exception:

        pass

    # --------------------------------------------------------
    # Exact button match
    # --------------------------------------------------------

    locator = page.get_by_role(
        "button",
        name=target,
        exact=True
    ).first

    try:

        if locator.is_visible(
            timeout=1000
        ):

            return locator

    except Exception:

        pass

    # --------------------------------------------------------
    # Text match
    # --------------------------------------------------------

    locator = page.get_by_text(
        target,
        exact=True
    ).first

    try:

        if locator.is_visible(
            timeout=1000
        ):

            return locator

    except Exception:

        pass

    # --------------------------------------------------------
    # Case-insensitive fallback
    # --------------------------------------------------------

    locator = page.get_by_text(
        re.compile(
            re.escape(target),
            re.IGNORECASE
        )
    ).first

    try:

        if locator.is_visible(
            timeout=1000
        ):

            return locator

    except Exception:

        pass

    return None


# ============================================================
# EXECUTE ACTION
# ============================================================

def execute_action(
    page,
    action
):

    action_type = action.get(
        "action"
    )

    # ========================================================
    # TYPE
    # ========================================================

    if action_type == "type":

        target = action.get(
            "target",
            ""
        )

        text = action.get(
            "text",
            ""
        )

        print()
        print(
            "Typing into:",
            target
        )

        print(
            "Text:",
            text
        )

        # ----------------------------------------------------
        # Search boxes
        # ----------------------------------------------------

        search_inputs = page.locator(
            "input:visible"
        )

        count = search_inputs.count()

        if count == 1:

            try:

                search_inputs.first.fill(
                    text
                )

                print(
                    "Typed using visible input."
                )

                return True

            except Exception:

                pass

        # ----------------------------------------------------
        # Find input based on target
        # ----------------------------------------------------

        possible_inputs = [
            "input[placeholder*='Search' i]",
            "input[name*='search' i]",
            "input[type='search']",
            "input[type='text']",
            "textarea"
        ]

        for selector in possible_inputs:

            locator = page.locator(
                selector
            ).first

            try:

                if locator.is_visible(
                    timeout=500
                ):

                    locator.fill(
                        text
                    )

                    print(
                        "Typed using:",
                        selector
                    )

                    return True

            except Exception:

                pass

        # ----------------------------------------------------
        # Contenteditable
        # ----------------------------------------------------

        locator = page.locator(
            "[contenteditable='true']:visible"
        ).first

        try:

            if locator.is_visible(
                timeout=500
            ):

                locator.fill(
                    text
                )

                print(
                    "Typed into contenteditable."
                )

                return True

        except Exception:

            pass

        print(
            "Could not find a text input."
        )

        return False

    # ========================================================
    # CLICK
    # ========================================================

    elif action_type == "click":

        target = action.get(
            "target",
            ""
        )

        print()
        print(
            "Click target:",
            target
        )

        element = find_click_target(
            page,
            target
        )

        if element is None:

            print(
                "Could not find clickable target."
            )

            return False

        try:

            element.click(
                timeout=5000
            )

            print(
                "Clicked:",
                target
            )

            return True

        except Exception as e:

            print(
                "Click failed:",
                e
            )

            return False

    # ========================================================
    # SCROLL
    # ========================================================

    elif action_type == "scroll":

        direction = action.get(
            "direction",
            "down"
        )

        amount = action.get(
            "amount",
            600
        )

        try:

            amount = int(
                amount
            )

        except Exception:

            amount = 600

        if direction == "up":

            amount = -abs(
                amount
            )

        else:

            amount = abs(
                amount
            )

        print()
        print(
            "Scrolling:",
            direction,
            abs(amount),
            "pixels"
        )

        page.mouse.wheel(
            0,
            amount
        )

        page.wait_for_timeout(
            1000
        )

        return True

    # ========================================================
    # PRESS KEY
    # ========================================================

    elif action_type == "press_key":

        key = action.get(
            "key",
            ""
        )

        print()
        print(
            "Pressing key:",
            key
        )

        try:

            page.keyboard.press(
                key
            )

            page.wait_for_timeout(
                500
            )

            return True

        except Exception as e:

            print(
                "Key press failed:",
                e
            )

            return False

    # ========================================================
    # WAIT
    # ========================================================

    elif action_type == "wait":

        seconds = action.get(
            "seconds",
            2
        )

        try:

            seconds = float(
                seconds
            )

        except Exception:

            seconds = 2

        seconds = max(
            0.5,
            min(
                seconds,
                10
            )
        )

        print()
        print(
            "Waiting:",
            seconds,
            "seconds"
        )

        time.sleep(
            seconds
        )

        return True

    # ========================================================
    # DONE
    # ========================================================

    elif action_type == "done":

        print()
        print(
            "Qwen believes the task is complete."
        )

        return True

    # ========================================================
    # UNKNOWN ACTION
    # ========================================================

    else:

        print()
        print(
            "Unknown action:",
            action
        )

        return False


# ============================================================
# FINAL VERIFICATION
# ============================================================

def verify_task(
    task,
    page
):

    page.screenshot(
        path="final.png"
    )

    response = chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": f"""
The user's task was:

{task}

CURRENT URL:
{page.url}

CURRENT PAGE TITLE:
{page.title()}

Look carefully at the screenshot.

Determine whether the user's task has ACTUALLY been completed.

IMPORTANT:

- Do not say true merely because the page is related
  to the task.
- The requested action must actually have happened.
- If the task asks to open something, it must be open.
- If the task asks to search for something, the search
  must actually have happened.
- If the task asks to click something, that action must
  actually have occurred.
- If the result is uncertain, return false.

Return ONLY:

{{"verified":true}}

or:

{{"verified":false}}

Do not explain anything.
""",
                "images": [
                    "final.png"
                ]
            }
        ]
    )

    print()
    print(
        "FINAL VERIFICATION RESPONSE:"
    )

    print(
        repr(
            response.message.content
        )
    )

    return clean_json(
        response.message.content
    )


# ============================================================
# USER TASK
# ============================================================

task = input(
    "What should I do? > "
)


# ============================================================
# START BROWSER
# ============================================================

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    page = browser.new_page(
        viewport={
            "width": 1280,
            "height": 800
        }
    )

    # ========================================================
    # STARTING PAGE
    # ========================================================

    page.goto(
        "https://www.google.com"
    )

    page.wait_for_timeout(
        2000
    )

    # ========================================================
    # AGENT LOOP
    # ========================================================

    task_completed = False

    for step in range(
        1,
        MAX_STEPS + 1
    ):

        print()
        print("=" * 60)
        print(
            f"AGENT STEP {step}/{MAX_STEPS}"
        )
        print("=" * 60)

        print(
            "Current URL:",
            page.url
        )

        print(
            "Current title:",
            page.title()
        )

        # ----------------------------------------------------
        # Screenshot current state
        # ----------------------------------------------------

        page.screenshot(
            path=SCREENSHOT_PATH
        )

        # ----------------------------------------------------
        # Ask Qwen what to do
        # ----------------------------------------------------

        try:

            action, links = ask_qwen(
                task,
                page,
                SCREENSHOT_PATH
            )

        except Exception as e:

            print()
            print(
                "Qwen decision failed:"
            )

            print(
                e
            )

            break

        print()
        print(
            "AI ACTION:",
            action
        )

        # ----------------------------------------------------
        # DONE action
        # ----------------------------------------------------

        if action.get(
            "action"
        ) == "done":

            print()
            print(
                "AI says the task is complete."
            )

            task_completed = True

            break

        # ----------------------------------------------------
        # Execute action
        # ----------------------------------------------------

        success = execute_action(
            page,
            action
        )

        if not success:

            print()
            print(
                "ACTION FAILED."
            )

            print(
                "The agent will continue and"
                " allow Qwen to reassess."
            )

        else:

            print()
            print(
                "ACTION COMPLETED."
            )

        # ----------------------------------------------------
        # Wait for page updates
        # ----------------------------------------------------

        page.wait_for_timeout(
            1000
        )

    # ========================================================
    # MAX STEPS
    # ========================================================

    if not task_completed:

        print()
        print(
            "=" * 60
        )

        print(
            "Maximum number of agent steps reached."
        )

    # ========================================================
    # FINAL VERIFICATION
    # ========================================================

    print()
    print(
        "=" * 60
    )

    print(
        "FINAL VERIFICATION"
    )

    print(
        "=" * 60
    )

    try:

        verification = verify_task(
            task,
            page
        )

        print()
        print(
            "Verification:",
            verification
        )

        if (
            verification.get(
                "verified"
            )
            is True
        ):

            print()
            print(
                "TASK COMPLETED SUCCESSFULLY."
            )

        else:

            print()
            print(
                "TASK MAY NOT HAVE BEEN COMPLETED."
            )

    except Exception as e:

        print()
        print(
            "Verification failed:"
        )

        print(
            e
        )

    input(
        "Press Enter to close..."
    )
