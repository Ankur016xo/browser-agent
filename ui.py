"""
Desktop UI launcher for the Browser Agent.
"""
import tkinter as tk
from browser_agent.desktop_ui import BrowserAgentUI


def main():
    root = tk.Tk()
    app = BrowserAgentUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
