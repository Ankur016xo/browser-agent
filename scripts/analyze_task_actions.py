import json
import re
from collections import Counter, defaultdict
from pathlib import Path

INPUT = Path(
    "data/kaggle/mind2web/processed/trajectories.jsonl"
)


TASK_PATTERNS = {
    "search": [
        r"\bsearch\b",
        r"\bfind\b",
        r"\blook\s+for\b",
    ],
    "enter": [
        r"\benter\b",
        r"\btype\b",
        r"\binput\b",
    ],
    "select": [
        r"\bselect\b",
        r"\bchoose\b",
        r"\bpick\b",
    ],
    "date": [
        r"\bdate\b",
        r"\bday\b",
        r"\bon\s+\w+\s+\d+\b",
    ],
    "time": [
        r"\btime\b",
        r"\b\d{1,2}:\d{2}\b",
        r"\b\d+\s*(?:am|pm)\b",
    ],
    "location": [
        r"\bin\s+\w+",
        r"\bfrom\s+\w+",
        r"\bto\s+\w+",
        r"\blocation\b",
    ],
    "price": [
        r"\bprice\b",
        r"\bcost\b",
        r"\bunder\s+\$?\d+",
        r"\bbelow\s+\$?\d+",
    ],
}


def task_categories(task):
    categories = []

    for category, patterns in TASK_PATTERNS.items():
        if any(
            re.search(pattern, task, re.IGNORECASE)
            for pattern in patterns
        ):
            categories.append(category)

    return categories


def main():
    category_actions = defaultdict(Counter)
    category_counts = Counter()

    with INPUT.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            record = json.loads(line)

            task = record.get("task", "")
            categories = task_categories(task)

            actions = record.get("actions", [])

            action_types = {
                action.get("action", "UNKNOWN")
                for action in actions
            }

            for category in categories:
                category_counts[category] += 1

                for action_type in action_types:
                    category_actions[category][action_type] += 1

    print("=" * 60)
    print("TASK → ACTION ANALYSIS")
    print("=" * 60)

    for category, count in category_counts.most_common():
        print(f"\n{category.upper()} ({count} trajectories)")

        for action, action_count in (
            category_actions[category].most_common()
        ):
            percentage = action_count / count * 100
            print(
                f"  {action:10} "
                f"{action_count:5} ({percentage:5.1f}%)"
            )


if __name__ == "__main__":
    main()