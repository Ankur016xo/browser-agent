import json
from collections import Counter
from pathlib import Path

INPUT = Path(
    "data/kaggle/mind2web/processed/trajectories.jsonl"
)


def main():
    action_counts = Counter()
    first_actions = Counter()
    transitions = Counter()
    websites = Counter()
    domains = Counter()

    trajectories = 0
    total_actions = 0

    with INPUT.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            record = json.loads(line)
            trajectories += 1

            website = record.get("website", "")
            domain = record.get("domain", "")

            if website:
                websites[website] += 1

            if domain:
                domains[domain] += 1

            actions = record.get("actions", [])
            previous = None

            for i, action in enumerate(actions):
                action_type = action.get("action", "UNKNOWN")

                action_counts[action_type] += 1
                total_actions += 1

                if i == 0:
                    first_actions[action_type] += 1

                if previous:
                    transitions[(previous, action_type)] += 1

                previous = action_type

    print("=" * 60)
    print("MIND2WEB ANALYSIS")
    print("=" * 60)

    print(f"\nTrajectories: {trajectories}")
    print(f"Actions:      {total_actions}")

    print("\nACTION FREQUENCY")
    for action, count in action_counts.most_common():
        percentage = count / total_actions * 100
        print(f"{action:10} {count:6} ({percentage:5.1f}%)")

    print("\nFIRST ACTION")
    for action, count in first_actions.most_common():
        percentage = count / trajectories * 100
        print(f"{action:10} {count:6} ({percentage:5.1f}%)")

    print("\nCOMMON ACTION TRANSITIONS")
    for (a, b), count in transitions.most_common(20):
        print(f"{a:10} -> {b:10} : {count}")

    print("\nTOP WEBSITES")
    for website, count in websites.most_common(15):
        print(f"{website:25} {count}")

    print("\nDOMAINS")
    for domain, count in domains.most_common():
        print(f"{domain:25} {count}")


if __name__ == "__main__":
    main()