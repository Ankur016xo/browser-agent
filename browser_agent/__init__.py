"""
browser-agent: Lightweight on-device visual browser agent using local vision models.
"""
from browser_agent.config import get_config, load_config
from browser_agent.state import AgentMemory, AgentState, ElementInfo, ActionRecord
from browser_agent.perception import PerceptionEngine
from browser_agent.verifier import ActionVerifier
from browser_agent.loop_detector import LoopDetector

__version__ = "0.2.0"

def __getattr__(name: str):
    if name in ("BrowserAgent", "main"):
        from browser_agent.agent import BrowserAgent, main
        if name == "BrowserAgent":
            return BrowserAgent
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BrowserAgent",
    "main",
    "get_config",
    "load_config",
    "AgentState",
    "AgentMemory",
    "ElementInfo",
    "ActionRecord",
    "PerceptionEngine",
    "ActionVerifier",
    "LoopDetector",
]