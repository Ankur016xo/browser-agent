import tkinter as tk
from tkinter import ttk
from pathlib import Path
import subprocess
import threading
import queue
import sys
import os
import time

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

APP_DIR = Path(__file__).resolve().parent
AGENT_MODULE = "browser_agent.agent"

SCREENSHOTS = [
    "agent_screen.png",
    "screen.png",
    "screen_after_typing.png",
    "results.png",
    "final.png",
    "screenshot.png",
    "screenshot_0.png",
    "screenshot_1.png",
    "screenshot_2.png",
    "screenshot_3.png",
    "screenshot_4.png",
    "step_1.png",
    "step_2.png",
    "step_3.png",
    "step_4.png",
    "step_5.png",
    "step_6.png",
    "step_7.png",
    "step_8.png",
]


# ============================================================
# COLORS
# ============================================================

BG = "#080B12"
SIDEBAR = "#0C1018"
PANEL = "#101620"
PANEL_2 = "#151C27"
PANEL_3 = "#1A2230"

BORDER = "#222C3B"

WHITE = "#F5F7FA"
TEXT = "#D8DEE9"
MUTED = "#8995A7"
DIM = "#596577"

BLUE = "#5B8CFF"
BLUE_HOVER = "#709BFF"

GREEN = "#36D399"
RED = "#FF647C"
YELLOW = "#F4C95D"


# ============================================================
# HELPERS
# ============================================================

def font(size, weight="normal"):
    return ("Segoe UI", size, weight)


# ============================================================
# MAIN UI
# ============================================================

class BrowserAgentUI:

    def __init__(self, root):

        self.root = root

        self.root.title("Browser Agent")
        self.root.geometry("1400x850")
        self.root.minsize(1100, 700)

        self.root.configure(bg=BG)

        self.process = None
        self.queue = queue.Queue()

        self.current_state = "IDLE"
        self.current_screenshot = None
        self.last_screenshot_time = 0

        self.build_styles()
        self.build_ui()

        self.root.after(100, self.process_queue)
        self.root.after(400, self.refresh_screenshot)

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

    # ========================================================
    # STYLES
    # ========================================================

    def build_styles(self):

        style = ttk.Style()

        style.theme_use("clam")

        style.configure(
            "Agent.Horizontal.TProgressbar",
            troughcolor=PANEL_3,
            background=BLUE,
            borderwidth=0,
            thickness=3
        )

    # ========================================================
    # ROOT
    # ========================================================

    def build_ui(self):

        self.root.grid_rowconfigure(
            0,
            weight=1
        )

        self.root.grid_columnconfigure(
            1,
            weight=1
        )

        self.create_sidebar()

        self.main = tk.Frame(
            self.root,
            bg=BG
        )

        self.main.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        self.main.grid_rowconfigure(
            1,
            weight=1
        )

        self.main.grid_columnconfigure(
            0,
            weight=1
        )

        self.create_header()
        self.create_workspace()
        self.create_command_bar()

    # ========================================================
    # SIDEBAR
    # ========================================================

    def create_sidebar(self):

        sidebar = tk.Frame(
            self.root,
            bg=SIDEBAR,
            width=240
        )

        sidebar.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        sidebar.grid_propagate(False)

        # ----------------------------------------------------
        # LOGO
        # ----------------------------------------------------

        logo = tk.Frame(
            sidebar,
            bg=SIDEBAR
        )

        logo.pack(
            fill="x",
            padx=20,
            pady=(24, 28)
        )

        icon = tk.Canvas(
            logo,
            width=34,
            height=34,
            bg=SIDEBAR,
            highlightthickness=0
        )

        icon.pack(
            side="left"
        )

        icon.create_oval(
            3,
            3,
            31,
            31,
            fill=BLUE,
            outline=""
        )

        icon.create_oval(
            10,
            10,
            24,
            24,
            fill=SIDEBAR,
            outline=""
        )

        icon.create_oval(
            14,
            14,
            20,
            20,
            fill=BLUE,
            outline=""
        )

        tk.Label(
            logo,
            text="Browser Agent",
            bg=SIDEBAR,
            fg=WHITE,
            font=font(14, "bold")
        ).pack(
            side="left",
            padx=10
        )

        # ----------------------------------------------------
        # NEW TASK
        # ----------------------------------------------------

        tk.Button(
            sidebar,
            text="+   New task",
            command=self.focus_task,
            bg=BLUE,
            fg="white",
            activebackground=BLUE_HOVER,
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            font=font(10, "bold"),
            cursor="hand2",
            padx=12,
            pady=11
        ).pack(
            fill="x",
            padx=16,
            pady=(0, 28)
        )

        # ----------------------------------------------------
        # SECTION
        # ----------------------------------------------------

        self.sidebar_section(
            sidebar,
            "WORKSPACE"
        )

        self.sidebar_item(
            sidebar,
            "⌂   Overview",
            True
        )

        self.sidebar_item(
            sidebar,
            "◷   Recent tasks",
            False
        )

        self.sidebar_section(
            sidebar,
            "RECENT"
        )

        self.recent_task(
            sidebar,
            "Search for Elden Ring"
        )

        self.recent_task(
            sidebar,
            "Open Wikipedia"
        )

        self.recent_task(
            sidebar,
            "Google search"
        )

        # ----------------------------------------------------
        # SYSTEM
        # ----------------------------------------------------

        system = tk.Frame(
            sidebar,
            bg=SIDEBAR
        )

        system.pack(
            side="bottom",
            fill="x",
            padx=18,
            pady=20
        )

        self.system_status(
            system,
            "QWEN 2.5 VL",
            "Ollama",
            GREEN
        )

        self.system_status(
            system,
            "BROWSER",
            "Chromium",
            GREEN
        )

        self.system_status(
            system,
            "RUNTIME",
            "Local",
            GREEN
        )

    def sidebar_section(
        self,
        parent,
        text
    ):

        tk.Label(
            parent,
            text=text,
            bg=SIDEBAR,
            fg=DIM,
            font=font(8, "bold")
        ).pack(
            anchor="w",
            padx=22,
            pady=(8, 8)
        )

    def sidebar_item(
        self,
        parent,
        text,
        active=False
    ):

        frame = tk.Frame(
            parent,
            bg=PANEL_2 if active else SIDEBAR
        )

        frame.pack(
            fill="x",
            padx=10,
            pady=2
        )

        tk.Label(
            frame,
            text=text,
            bg=frame["bg"],
            fg=WHITE if active else MUTED,
            font=font(
                10,
                "bold" if active else "normal"
            ),
            anchor="w",
            padx=12,
            pady=9
        ).pack(
            fill="x"
        )

    def recent_task(
        self,
        parent,
        text
    ):

        tk.Label(
            parent,
            text=text,
            bg=SIDEBAR,
            fg=MUTED,
            font=font(9),
            anchor="w"
        ).pack(
            fill="x",
            padx=22,
            pady=5
        )

    def system_status(
        self,
        parent,
        title,
        value,
        color
    ):

        row = tk.Frame(
            parent,
            bg=SIDEBAR
        )

        row.pack(
            fill="x",
            pady=4
        )

        tk.Label(
            row,
            text="●",
            bg=SIDEBAR,
            fg=color,
            font=font(8)
        ).pack(
            side="left"
        )

        tk.Label(
            row,
            text=title,
            bg=SIDEBAR,
            fg=TEXT,
            font=font(8, "bold")
        ).pack(
            side="left",
            padx=6
        )

        tk.Label(
            row,
            text=value,
            bg=SIDEBAR,
            fg=DIM,
            font=font(8)
        ).pack(
            side="right"
        )

    # ========================================================
    # HEADER
    # ========================================================

    def create_header(self):

        header = tk.Frame(
            self.main,
            bg=BG,
            height=72
        )

        header.grid(
            row=0,
            column=0,
            sticky="ew"
        )

        header.grid_propagate(False)

        tk.Label(
            header,
            text="Agent Workspace",
            bg=BG,
            fg=WHITE,
            font=font(20, "bold")
        ).pack(
            side="left",
            padx=28,
            pady=20
        )

        status = tk.Frame(
            header,
            bg=BG
        )

        status.pack(
            side="right",
            padx=26
        )

        self.connection_chip(
            status,
            "● Ollama",
            GREEN
        )

        self.connection_chip(
            status,
            "● Browser",
            GREEN
        )

    def connection_chip(
        self,
        parent,
        text,
        color
    ):

        frame = tk.Frame(
            parent,
            bg=PANEL
        )

        frame.pack(
            side="left",
            padx=4
        )

        tk.Label(
            frame,
            text=text,
            bg=PANEL,
            fg=color,
            font=font(8, "bold"),
            padx=11,
            pady=7
        ).pack()

    # ========================================================
    # WORKSPACE
    # ========================================================

    def create_workspace(self):

        workspace = tk.Frame(
            self.main,
            bg=BG
        )

        workspace.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=28,
            pady=5
        )

        workspace.grid_rowconfigure(
            0,
            weight=1
        )

        workspace.grid_columnconfigure(
            0,
            weight=1
        )

        # ====================================================
        # BROWSER CARD
        # ====================================================

        browser = tk.Frame(
            workspace,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        browser.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 8)
        )

        browser.grid_rowconfigure(
            1,
            weight=1
        )

        browser.grid_columnconfigure(
            0,
            weight=1
        )

        # Browser top bar

        top = tk.Frame(
            browser,
            bg=PANEL,
            height=52
        )

        top.grid(
            row=0,
            column=0,
            sticky="ew"
        )

        top.grid_propagate(False)

        tk.Label(
            top,
            text="BROWSER",
            bg=PANEL,
            fg=MUTED,
            font=font(9, "bold")
        ).pack(
            side="left",
            padx=16
        )

        live = tk.Frame(
            top,
            bg="#10271E"
        )

        live.pack(
            side="right",
            padx=15,
            pady=11
        )

        self.live_label = tk.Label(
            live,
            text="● LIVE",
            bg="#10271E",
            fg=GREEN,
            font=font(8, "bold"),
            padx=9,
            pady=4
        )

        self.live_label.pack()

        # Browser viewport

        viewport = tk.Frame(
            browser,
            bg="#05070A"
        )

        viewport.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=14,
            pady=(0, 14)
        )

        viewport.grid_rowconfigure(
            0,
            weight=1
        )

        viewport.grid_columnconfigure(
            0,
            weight=1
        )

        self.browser_preview = tk.Label(
            viewport,
            text="",
            bg="#05070A",
            fg=MUTED,
            font=font(12)
        )

        self.browser_preview.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        # ====================================================
        # AGENT CARD
        # ====================================================

        agent = tk.Frame(
            workspace,
            bg=PANEL,
            width=330,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        agent.grid(
            row=0,
            column=1,
            sticky="ns"
        )

        agent.grid_propagate(False)

        tk.Label(
            agent,
            text="AGENT",
            bg=PANEL,
            fg=MUTED,
            font=font(9, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 10)
        )

        # Current state card

        state = tk.Frame(
            agent,
            bg=PANEL_2
        )

        state.pack(
            fill="x",
            padx=14
        )

        self.state_dot = tk.Label(
            state,
            text="●",
            bg=PANEL_2,
            fg=DIM,
            font=font(18)
        )

        self.state_dot.pack(
            side="left",
            padx=(14, 8),
            pady=13
        )

        state_text = tk.Frame(
            state,
            bg=PANEL_2
        )

        state_text.pack(
            side="left"
        )

        tk.Label(
            state_text,
            text="CURRENT STATE",
            bg=PANEL_2,
            fg=DIM,
            font=font(7, "bold")
        ).pack(
            anchor="w"
        )

        self.state_label = tk.Label(
            state_text,
            text="IDLE",
            bg=PANEL_2,
            fg=WHITE,
            font=font(12, "bold")
        )

        self.state_label.pack(
            anchor="w"
        )

        # Action

        tk.Label(
            agent,
            text="CURRENT ACTION",
            bg=PANEL,
            fg=DIM,
            font=font(8, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(22, 7)
        )

        self.action_label = tk.Label(
            agent,
            text="Waiting for a task...",
            bg=PANEL,
            fg=TEXT,
            font=font(10),
            wraplength=285,
            justify="left",
            anchor="w"
        )

        self.action_label.pack(
            fill="x",
            padx=18
        )

        # Progress

        tk.Label(
            agent,
            text="PROGRESS",
            bg=PANEL,
            fg=DIM,
            font=font(8, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(23, 6)
        )

        self.progress_text = tk.Label(
            agent,
            text="Ready",
            bg=PANEL,
            fg=MUTED,
            font=font(9)
        )

        self.progress_text.pack(
            anchor="w",
            padx=18
        )

        self.progress = ttk.Progressbar(
            agent,
            style="Agent.Horizontal.TProgressbar",
            mode="indeterminate"
        )

        self.progress.pack(
            fill="x",
            padx=18,
            pady=(7, 0)
        )

        # Activity

        tk.Label(
            agent,
            text="ACTIVITY",
            bg=PANEL,
            fg=DIM,
            font=font(8, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(23, 7)
        )

        self.activity = tk.Text(
            agent,
            bg="#070A0F",
            fg=MUTED,
            relief="flat",
            borderwidth=0,
            font=("Consolas", 8),
            wrap="word",
            padx=11,
            pady=11
        )

        self.activity.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14)
        )

        self.activity.configure(
            state="disabled"
        )

    # ========================================================
    # COMMAND BAR
    # ========================================================

    def create_command_bar(self):

        container = tk.Frame(
            self.main,
            bg=BG,
            height=92
        )

        container.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=28,
            pady=(7, 18)
        )

        container.grid_propagate(False)

        command = tk.Frame(
            container,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        command.pack(
            fill="both",
            expand=True
        )

        self.task_entry = tk.Entry(
            command,
            bg=PANEL,
            fg=WHITE,
            insertbackground=WHITE,
            relief="flat",
            borderwidth=0,
            font=font(11)
        )

        self.task_entry.pack(
            side="left",
            fill="both",
            expand=True,
            padx=18
        )

        self.task_entry.insert(
            0,
            "Search for Elden Ring and open its Wikipedia article"
        )

        self.task_entry.bind(
            "<Return>",
            lambda event: self.start_agent()
        )

        # Stop

        self.stop_button = tk.Button(
            command,
            text="STOP",
            command=self.stop_agent,
            bg="#29151B",
            fg=RED,
            activebackground="#3B1B24",
            activeforeground=RED,
            relief="flat",
            borderwidth=0,
            font=font(9, "bold"),
            padx=17,
            pady=10,
            state="disabled",
            cursor="hand2"
        )

        self.stop_button.pack(
            side="right",
            padx=6
        )

        # Run

        self.run_button = tk.Button(
            command,
            text="RUN AGENT  →",
            command=self.start_agent,
            bg=BLUE,
            fg="white",
            activebackground=BLUE_HOVER,
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            font=font(9, "bold"),
            padx=19,
            pady=10,
            cursor="hand2"
        )

        self.run_button.pack(
            side="right",
            padx=6
        )

    # ========================================================
    # FOCUS TASK
    # ========================================================

    def focus_task(self):

        self.task_entry.focus_set()

        self.task_entry.selection_range(
            0,
            tk.END
        )

    # ========================================================
    # START AGENT
    # ========================================================

    def start_agent(self):

        if (
            self.process
            and self.process.poll() is None
        ):
            return

        task = self.task_entry.get().strip()

        if not task:

            self.set_action(
                "Enter a task first."
            )

            return

        if not (APP_DIR / "browser_agent" / "agent.py").exists():

            self.add_activity(
                "✕ browser_agent/agent.py was not found."
            )

            return

        self.clear_activity()

        self.add_activity(
            "✓ Task received"
        )

        self.add_activity(
            "  " + task
        )

        self.set_state(
            "STARTING",
            BLUE
        )

        self.set_action(
            "Starting browser agent..."
        )

        self.progress_text.configure(
            text="Agent running..."
        )

        self.run_button.configure(
            state="disabled"
        )

        self.stop_button.configure(
            state="normal"
        )

        self.task_entry.configure(
            state="disabled"
        )

        self.progress.start(
            10
        )

        threading.Thread(
            target=self.run_agent,
            args=(task,),
            daemon=True
        ).start()

    # ========================================================
    # RUN PYTHON AGENT
    # ========================================================

    def run_agent(
        self,
        task
    ):

        try:

            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    AGENT_MODULE,
                    task,
                ],
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in iter(
                self.process.stdout.readline,
                ""
            ):

                if line:

                    self.queue.put(
                        line.rstrip()
                    )

            self.process.stdout.close()

            code = self.process.wait()

            self.queue.put(
                f"__EXIT__:{code}"
            )

        except Exception as e:

            self.queue.put(
                f"__ERROR__:{e}"
            )

        finally:

            self.process = None

            self.queue.put(
                "__FINISHED__"
            )

    # ========================================================
    # STOP AGENT
    # ========================================================

    def stop_agent(self):

        if not self.process:
            return

        try:

            self.process.terminate()

            self.add_activity(
                "■ Agent stopped"
            )

            self.set_state(
                "STOPPED",
                RED
            )

            self.set_action(
                "Agent execution stopped."
            )

        except Exception as e:

            self.add_activity(
                f"✕ {e}"
            )

    # ========================================================
    # QUEUE
    # ========================================================

    def process_queue(self):

        try:

            while True:

                message = self.queue.get_nowait()

                self.handle_message(
                    message
                )

        except queue.Empty:
            pass

        self.root.after(
            100,
            self.process_queue
        )

    # ========================================================
    # HANDLE AGENT OUTPUT
    # ========================================================

    def handle_message(
        self,
        message
    ):

        if message == "__FINISHED__":

            self.progress.stop()

            self.run_button.configure(
                state="normal"
            )

            self.stop_button.configure(
                state="disabled"
            )

            self.task_entry.configure(
                state="normal"
            )

            return

        if message.startswith(
            "__EXIT__:"
        ):

            code = message.split(
                ":",
                1
            )[1]

            self.add_activity(
                f"Process exited: {code}"
            )

            return

        if message.startswith(
            "__ERROR__:"
        ):

            error = message.split(
                ":",
                1
            )[1]

            self.set_state(
                "ERROR",
                RED
            )

            self.set_action(
                error
            )

            self.add_activity(
                "✕ " + error
            )

            return

        if not message.strip():
            return

        text = message.strip()

        lower = text.lower()

        # ----------------------------------------------------
        # OBSERVE
        # ----------------------------------------------------

        if "agent step" in lower:

            self.set_state(
                "OBSERVING",
                BLUE
            )

            self.set_action(
                "Observing the current browser state..."
            )

            self.add_activity(
                "◉ " + text
            )

        # ----------------------------------------------------
        # THINK
        # ----------------------------------------------------

        elif "raw qwen response" in lower or "analyzing screen with qwen" in lower:

            self.set_state(
                "THINKING",
                BLUE
            )

            self.set_action(
                "Qwen is analyzing the browser..."
            )

            self.add_activity(
                "◆ Qwen analyzing browser"
            )

        # ----------------------------------------------------
        # ACTION
        # ----------------------------------------------------

        elif "ai action" in lower:

            self.set_state(
                "ACTING",
                BLUE
            )

            self.set_action(
                text
            )

            self.add_activity(
                "→ " + text
            )

        elif "typing" in lower:

            self.set_state(
                "ACTING",
                BLUE
            )

            self.set_action(
                text
            )

            self.add_activity(
                "→ " + text
            )

        elif "click" in lower:

            self.set_state(
                "ACTING",
                BLUE
            )

            self.set_action(
                text
            )

            self.add_activity(
                "→ " + text
            )

        elif "scroll" in lower:

            self.set_state(
                "ACTING",
                BLUE
            )

            self.set_action(
                text
            )

            self.add_activity(
                "→ " + text
            )

        # ----------------------------------------------------
        # VERIFY
        # ----------------------------------------------------

        elif "final verification" in lower:

            self.set_state(
                "VERIFYING",
                YELLOW
            )

            self.set_action(
                "Verifying the final browser state..."
            )

            self.add_activity(
                "◆ Verifying task"
            )

        elif "task completed successfully" in lower:

            self.set_state(
                "COMPLETED",
                GREEN
            )

            self.set_action(
                "Task completed successfully."
            )

            self.progress_text.configure(
                text="Complete"
            )

            self.add_activity(
                "✓ Task completed"
            )

        elif "task may not" in lower:

            self.set_state(
                "FAILED",
                RED
            )

            self.set_action(
                "Task could not be verified."
            )

            self.add_activity(
                "✕ Verification failed"
            )

        elif "action failed" in lower:

            self.add_activity(
                "⚠ Action failed — reassessing"
            )

    # ========================================================
    # STATE
    # ========================================================

    def set_state(
        self,
        state,
        color
    ):

        self.current_state = state

        self.state_label.configure(
            text=state,
            fg=color
        )

        self.state_dot.configure(
            fg=color
        )

        if state == "COMPLETED":

            self.live_label.configure(
                text="● COMPLETE",
                fg=GREEN
            )

        elif state == "FAILED":

            self.live_label.configure(
                text="● FAILED",
                fg=RED
            )

        else:

            self.live_label.configure(
                text="● LIVE",
                fg=GREEN
            )

    # ========================================================
    # ACTION
    # ========================================================

    def set_action(
        self,
        text
    ):

        self.action_label.configure(
            text=text
        )

    # ========================================================
    # ACTIVITY
    # ========================================================

    def add_activity(
        self,
        text
    ):

        self.activity.configure(
            state="normal"
        )

        self.activity.insert(
            "end",
            text + "\n"
        )

        self.activity.see(
            "end"
        )

        self.activity.configure(
            state="disabled"
        )

    def clear_activity(self):

        self.activity.configure(
            state="normal"
        )

        self.activity.delete(
            "1.0",
            "end"
        )

        self.activity.configure(
            state="disabled"
        )

    # ========================================================
    # SCREENSHOT
    # ========================================================

    def latest_screenshot(self):

        candidates = []

        for name in SCREENSHOTS:

            path = APP_DIR / name

            if path.exists():

                try:

                    candidates.append(
                        path
                    )

                except Exception:
                    pass

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda p: p.stat().st_mtime
        )

    def refresh_screenshot(self):

        screenshot = (
            self.latest_screenshot()
        )

        if screenshot:

            try:

                modified = screenshot.stat().st_mtime

                if modified != self.last_screenshot_time:

                    self.last_screenshot_time = modified

                    self.display_screenshot(
                        screenshot
                    )

            except Exception:
                pass

        self.root.after(
            400,
            self.refresh_screenshot
        )

    # ========================================================
    # DISPLAY SCREENSHOT
    # ========================================================

    def display_screenshot(
        self,
        path
    ):

        try:

            if PIL_AVAILABLE:

                image = Image.open(
                    path
                )

                image.thumbnail(
                    (900, 600),
                    Image.Resampling.LANCZOS
                )

                photo = ImageTk.PhotoImage(
                    image
                )

                self.browser_preview.configure(
                    image=photo,
                    text=""
                )

                self.browser_preview.image = photo

            else:

                image = tk.PhotoImage(
                    file=str(path)
                )

                self.browser_preview.configure(
                    image=image,
                    text=""
                )

                self.browser_preview.image = image

        except Exception:
            pass

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):

        if self.process:

            try:
                self.process.terminate()
            except Exception:
                pass

        self.root.destroy()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    root = tk.Tk()

    app = BrowserAgentUI(
        root
    )

    root.mainloop()
