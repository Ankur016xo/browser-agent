"""Download and normalize browser-agent datasets from Kaggle.

Usage:
    python scripts/download_kaggle_data.py --dataset browsecomp
    python scripts/download_kaggle_data.py --dataset mind2web

Requires the Kaggle CLI to be configured locally. Credentials are never stored
in this repository.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from browser_agent.kaggle_data import (
    BROWSECOMP_DATASET,
    MIND2WEB_DATASET,
    download_dataset,
    load_browse_tasks,
    load_mind2web_actions,
    write_jsonl,
)


DATA_ROOT = Path("data/kaggle")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["browsecomp", "mind2web"], required=True)
    parser.add_argument("--output", type=Path, default=DATA_ROOT)
    args = parser.parse_args()

    dataset_id = BROWSECOMP_DATASET if args.dataset == "browsecomp" else MIND2WEB_DATASET
    raw_dir = args.output / args.dataset / "raw"
    processed_dir = args.output / args.dataset / "processed"
    download_dataset(dataset_id, raw_dir)

    if args.dataset == "browsecomp":
        records = [task.to_dict() for task in load_browse_tasks(raw_dir)]
        write_jsonl(records, processed_dir / "tasks.jsonl")
        print(f"Normalized {len(records)} BrowseComp tasks.")
    else:
        records = load_mind2web_actions(raw_dir)
        write_jsonl(records, processed_dir / "actions.jsonl")
        print(f"Normalized {len(records)} Mind2Web action records.")


if __name__ == "__main__":
    main()
