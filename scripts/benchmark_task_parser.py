"""Measure task-parser quality on Kaggle browsing tasks plus local regression cases.

This is a structural benchmark, not a claim of ground-truth intent labels for
BrowseComp. BrowseComp is a browsing benchmark, so we use it to measure whether
our parser preserves meaningful task text rather than inventing generic queries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from browser_agent.kaggle_data import load_browse_tasks
from browser_agent.planner import GENERIC_TARGETS, parse_task_plan

REGRESSION_TASKS = [
    "what is the average price of basketball shoes in india",
    "go to flipkart and find the price of basketball shoes",
    "find cheap running shoes",
    "what is the average price of laptops in india",
    "search for headphones under 5000",
]


def _quality(task: str) -> tuple[bool, list[str]]:
    plan = parse_task_plan(task)
    problems: list[str] = []
    query = plan.search_query.strip()
    if not query:
        problems.append("empty_query")
    if query.lower() in GENERIC_TARGETS or query.lower() in {"product", "item", "result"}:
        problems.append("generic_query")
    if query.lower() == task.strip().lower():
        problems.append("un-normalized_query")
    return not problems, problems


def benchmark(tasks: list[str]) -> dict[str, object]:
    results = []
    passed = 0
    for task in tasks:
        ok, problems = _quality(task)
        if ok:
            passed += 1
        plan = parse_task_plan(task)
        results.append({
            "task": task,
            "passed": ok,
            "problems": problems,
            "destination": plan.destination,
            "query": plan.search_query,
            "intent": plan.intent,
            "target": plan.target,
        })
    return {
        "tasks": len(tasks),
        "passed": passed,
        "quality_rate": round(passed / len(tasks), 4) if tasks else 0.0,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browsecomp", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    tasks = list(REGRESSION_TASKS)
    if args.browsecomp:
        kaggle_tasks = load_browse_tasks(args.browsecomp)
        tasks.extend(item.task for item in kaggle_tasks[: args.limit])

    report = benchmark(tasks)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    for result in report["results"]:
        if not result["passed"]:
            print(json.dumps(result, ensure_ascii=False))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
