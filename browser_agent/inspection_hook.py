"""Compatibility hook that upgrades the existing exploration pipeline to DOM-first inspection.

The agent already imports ``inspect_page_for_requested_info`` from exploration.py.
Rather than rewriting the large legacy module in-place, this small hook swaps that
single inspection function for the generic structural inspector at package load.
No website-specific answers or selectors are introduced.
"""
from __future__ import annotations


def install_dom_first_inspection() -> None:
    from browser_agent import exploration
    from browser_agent.inspection import inspect_requested_information

    exploration.inspect_page_for_requested_info = inspect_requested_information
