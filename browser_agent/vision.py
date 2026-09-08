"""
Vision model client for Ollama VLM.
Handles image submission, prompt formatting, and JSON extraction.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ollama import chat

from browser_agent.config import get_config
from browser_agent.logging import get_logger
from browser_agent.prompts import ACTION_PROMPT, VERIFICATION_PROMPT
from browser_agent.state import ElementInfo

logger = get_logger(__name__)


def clean_json(text: str) -> dict[str, Any]:
    """
    Extract and parse JSON from model response text.
    Handles markdown code fences, surrounding conversational text, single quotes,
    trailing commas, and minor JSON malformations.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("AI returned an empty response.")

    # 1. Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    # 2. Try parsing the direct text
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 3. Find candidate JSON objects using regex (nested or outer)
    candidate_matches = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, re.DOTALL)
    if not candidate_matches:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            candidate_matches = [match.group(0)]

    for candidate in reversed(candidate_matches):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        # Attempt syntax repairs on the candidate
        repaired = candidate
        # Fix trailing commas before } or ]
        repaired = re.sub(r",\s*([\}\]])", r"\1", repaired)
        # Fix single quotes to double quotes if no double quotes present
        if "'" in repaired and '"' not in repaired:
            repaired = repaired.replace("'", '"')
        # Fix unquoted keys: {action: "click"} -> {"action": "click"}
        repaired = re.sub(r'(?<=[{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'"\1":', repaired)
        try:
            data = json.loads(repaired)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 4. Heuristic text fallback for actions
    text_lower = text.lower()
    if "done" in text_lower or "complete" in text_lower or "finish" in text_lower:
        return {"action": "done", "reasoning": text[:200] if text else "Task indicated complete", "confidence": 0.9}

    if "click" in text_lower or "close" in text_lower or "dismiss" in text_lower:
        elem_match = re.search(r"\b(?:element|id|badge|#)?\s*(\d+)\b", text, re.IGNORECASE)
        elem_id = int(elem_match.group(1)) if elem_match else None
        return {"action": "click", "element_id": elem_id, "reasoning": text[:200], "confidence": 0.8}

    if "type" in text_lower:
        elem_match = re.search(r"\b(?:element|id|badge|#)?\s*(\d+)\b", text, re.IGNORECASE)
        elem_id = int(elem_match.group(1)) if elem_match else None
        return {"action": "type", "element_id": elem_id, "text": "", "reasoning": text[:200], "confidence": 0.8}

    if "scroll" in text_lower:
        direction = "up" if "up" in text_lower else "down"
        return {"action": "scroll", "direction": direction, "reasoning": text[:200], "confidence": 0.8}

    if "press" in text_lower or "escape" in text_lower or "enter" in text_lower:
        key = "Escape" if "escape" in text_lower else "Enter"
        return {"action": "press_key", "key": key, "reasoning": text[:200], "confidence": 0.8}

    raise ValueError(f"AI did not return valid JSON:\n{text}")


def ask_vision_model(
    task: str,
    search_term: str,
    url: str,
    title: str,
    elements_text: str,
    screenshot_path: str | Path,
    action_history_summaries: list[str],
    loop_warning: str = "",
    target_page: str = "",
) -> dict[str, Any]:
    """
    Query the vision model for the next action.
    Returns structured action dictionary.
    """
    config = get_config()
    model = config.get("ollama", {}).get("model", "qwen2.5vl:3b")

    history_str = "\n".join(f"- {item}" for item in action_history_summaries[-6:])
    if not history_str:
        history_str = "No actions executed yet."

    prompt = ACTION_PROMPT.safe_substitute(
        task=task,
        target_page=target_page or "None specified",
        search_term=search_term or task,
        url=url,
        title=title,
        elements=elements_text or "None",
        history=history_str,
        loop_warning=f"WARNING / ADVICE:\n{loop_warning}\n" if loop_warning else "",
    )

    logger.debug("Sending vision model request (%s)", model)

    screenshot_str = str(screenshot_path)
    response = chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [screenshot_str],
            }
        ],
        options={
            "num_ctx": 8192,
            "temperature": 0.1,
            "repeat_penalty": 1.15,
            "top_p": 0.9,
        },
    )

    raw = response.message.content
    logger.debug("Raw model response: %r", raw)
    try:
        action = clean_json(raw)
    except Exception as exc:
        logger.warning("Primary VLM JSON parsing failed (%s); retrying with strict JSON request.", exc)
        # Retry with a strict prompt asking for JSON only
        strict_prompt = prompt + "\n\nPlease respond ONLY with a valid JSON object, no explanatory text or code fences."
        retry_response = chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": strict_prompt,
                    "images": [screenshot_str],
                }
            ],
            options={
                "num_ctx": 8192,
                "temperature": 0.0,
                "repeat_penalty": 1.15,
                "top_p": 0.9,
            },
        )
        raw_retry = retry_response.message.content
        logger.debug("Retry VLM response: %r", raw_retry)
        try:
            action = clean_json(raw_retry)
        except Exception as exc2:
            logger.error("Retry VLM JSON parsing also failed (%s). Falling back to safe wait action.", exc2)
            action = {"action": "wait", "confidence": 0.5, "reasoning": "Unable to parse VLM response; proceeding cautiously."}
    # Ensure required action fields have defaults
    if "action" not in action:
        action["action"] = "wait"
    if "confidence" not in action:
        action["confidence"] = 0.9
    if "reasoning" not in action:
        action["reasoning"] = f"Decided to {action.get('action')}"

    return action


def verify_task_completion(task: str, page: Any, screenshot_path: str | Path) -> dict[str, Any]:
    """
    Ask the vision model to verify if the overall user task was accomplished.
    """
    config = get_config()
    model = config.get("ollama", {}).get("model", "qwen2.5vl:3b")

    prompt = VERIFICATION_PROMPT.substitute(
        task=task,
        url=page.url,
        title=getattr(page, "title", lambda: "")(),
    )

    screenshot_str = str(screenshot_path)
    try:
        response = chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [screenshot_str],
                }
            ],
            options={
                "num_ctx": 8192,
                "temperature": 0.1,
                "repeat_penalty": 1.15,
                "top_p": 0.9,
            },
        )
        raw = response.message.content
        data = clean_json(raw)
        return {
            "verified": bool(data.get("verified", False)),
            "reason": data.get("reason", "No verification reason provided"),
            "confidence": float(data.get("confidence", 0.9)),
        }
    except Exception as exc:
        logger.warning("Visual task verification query failed: %s", exc)
        return {
            "verified": False,
            "reason": f"Visual task verification failed: {exc}",
            "confidence": 0.0,
        }


def summarize_task_result(
    task: str,
    page: Any,
    screenshot_path: str | Path,
    extracted_result: dict[str, Any] | None = None,
) -> str:
    """Summarize the final result of the task, incorporating any extracted facts."""
    config = get_config()
    model = config.get("ollama", {}).get("model", "qwen2.5vl:3b")

    extracted_context = ""
    if extracted_result:
        extracted_lines = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in extracted_result.items()]
        extracted_context = "\nEXTRACTED DATA FROM PAGE:\n" + "\n".join(extracted_lines)

    prompt = f"""
Summarize the outcome of this browser task for the user based on the screenshot and extracted data:
TASK: {task}
FINAL URL: {getattr(page, 'url', '')}
FINAL TITLE: {getattr(page, 'title', lambda: '')()}{extracted_context}

State the extracted answers and findings clearly and concisely in 1-3 bullet points.
If specific values (e.g., version numbers, titles, prices, headings) were requested in the task, state them prominently.
""".strip()

    try:
        active_img = str(screenshot_path) if Path(screenshot_path).exists() else None
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        if active_img:
            messages[0]["images"] = [active_img]

        response = chat(
            model=model,
            messages=messages,
            options={
                "num_ctx": 8192,
                "temperature": 0.1,
                "repeat_penalty": 1.15,
                "top_p": 0.9,
            },
        )
        content = response.message.content.strip()
        if not content or set(content) <= set("@#-*/=\\ \n\t"):
            raise ValueError("Model produced repetitive or empty tokens")
        return content
    except Exception as exc:
        logger.warning("VLM task summary failed, using fallback summary: %s", exc)
        if extracted_result:
            return "\n".join(f"- **{k.replace('_', ' ').title()}**: {v}" for k, v in extracted_result.items())
        url_str = getattr(page, "url", "")
        title_str = getattr(page, "title", lambda: "")()
        return f"- Completed task: {task}\n- URL: {url_str}\n- Title: {title_str}"


def take_screenshot(page: Any, path: str | Path, quality: int = 80, retries: int = 3) -> Path:
    """Take a screenshot of the page and save to disk with retry on transient navigation errors."""
    import time
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    last_error = None
    for attempt in range(retries):
        try:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass

            if str(path).lower().endswith((".jpg", ".jpeg")):
                page.screenshot(path=str(path), quality=quality, timeout=5000)
            else:
                page.screenshot(path=str(path), timeout=5000)
            return path_obj
        except Exception as exc:
            last_error = exc
            logger.warning("Screenshot attempt %d failed: %s. Retrying...", attempt + 1, exc)
            time.sleep(0.8)

    if last_error:
        raise last_error
    return path_obj
