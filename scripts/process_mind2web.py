import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ZIP_PATH = Path(
    "data/kaggle/mind2web/raw/"
    "mind2web-generalist-agents-for-web-tasks.zip"
)

OUTPUT_PATH = Path(
    "data/kaggle/mind2web/processed/trajectories.jsonl"
)


def parse_action(action: str) -> dict:
    """Convert Mind2Web action representation into structured data."""

    action = action.strip()

    match = re.match(
        r"\[(?P<element>[^\]]+)\]\s*(?P<target>.*?)\s*->\s*"
        r"(?P<action>[A-Z]+)(?::\s*(?P<value>.*))?$",
        action,
    )

    if not match:
        return {
            "raw": action,
            "element": "",
            "target": "",
            "action": "UNKNOWN",
            "value": "",
        }

    return {
        "raw": action,
        "element": match.group("element").strip(),
        "target": match.group("target").strip(),
        "action": match.group("action").strip(),
        "value": (match.group("value") or "").strip(),
    }


def process():
    if not ZIP_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {ZIP_PATH}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    action_counts = {}

    with zipfile.ZipFile(ZIP_PATH) as archive:
        with archive.open("train.csv") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8")
            reader = csv.DictReader(text)

            with OUTPUT_PATH.open("w", encoding="utf-8") as out:
                for row in reader:
                    raw_actions = row.get("action_reprs", "")

                    try:
                        actions = json.loads(raw_actions)
                    except json.JSONDecodeError:
                        # Kaggle CSV representation can also look like:
                        # ['action 1' 'action 2']
                        actions = re.findall(
                            r"'([^']*)'",
                            raw_actions,
                        )

                    parsed_actions = [
                        parse_action(action)
                        for action in actions
                    ]

                    for action in parsed_actions:
                        action_type = action["action"]
                        action_counts[action_type] = (
                            action_counts.get(action_type, 0) + 1
                        )

                    record = {
                        "annotation_id": row.get("annotation_id", ""),
                        "task": row.get("confirmed_task", ""),
                        "website": row.get("website", ""),
                        "domain": row.get("domain", ""),
                        "subdomain": row.get("subdomain", ""),
                        "actions": parsed_actions,
                    }

                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1

    print(f"Processed trajectories: {count}")
    print(f"Output: {OUTPUT_PATH}")
    print("\nAction counts:")

    for action, total in sorted(
        action_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(f"  {action}: {total}")


if __name__ == "__main__":
    process()