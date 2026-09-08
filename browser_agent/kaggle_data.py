"""Kaggle-backed datasets for browser-agent development and evaluation.

Kaggle is intentionally an offline/development dependency. The live browser
agent never calls Kaggle during a user task.
"""
from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


BROWSECOMP_DATASET = "openai/browsecomp-a-benchmark-for-browsing-agents"
MIND2WEB_DATASET = "thedevastator/mind2web-generalist-agents-for-web-tasks"


@dataclass(frozen=True)
class KaggleTask:
    """Normalized task representation independent of the source dataset."""

    task: str
    source: str
    source_file: str = ""
    reference_answer: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def download_dataset(dataset: str, output_dir: str | Path, *, unzip: bool = True) -> Path:
    """Download a Kaggle dataset using the official Kaggle CLI.

    Authentication is handled by the user's Kaggle CLI configuration. No API
    key is accepted by this module and credentials are never written to the repo.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    command = ["kaggle", "datasets", "download", dataset, "--path", str(output)]
    if unzip:
        command.append("--unzip")
    subprocess.run(command, check=True)
    return output


def _read_records(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    if suffix in {".json", ".jsonl"}:
        with path.open("r", encoding="utf-8") as handle:
            if suffix == ".jsonl":
                for line in handle:
                    line = line.strip()
                    if line:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            yield value
            else:
                value = json.load(handle)
                if isinstance(value, list):
                    yield from (row for row in value if isinstance(row, dict))
                elif isinstance(value, dict):
                    yield value


def load_browse_tasks(data_dir: str | Path) -> list[KaggleTask]:
    """Load BrowseComp questions into the project's common task format.

    The loader deliberately discovers the file instead of assuming a fixed
    Kaggle filename/version.
    """
    root = Path(data_dir)
    tasks: list[KaggleTask] = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".csv", ".json", ".jsonl"}:
            continue
        for row in _read_records(path):
            question = next(
                (str(row[key]).strip() for key in ("question", "task", "prompt")
                 if key in row and row[key]),
                "",
            )
            if not question:
                continue
            answer = next(
                (str(row[key]).strip() for key in ("answer", "reference_answer", "target")
                 if key in row and row[key]),
                "",
            )
            tasks.append(KaggleTask(
                task=question,
                source="browsecomp",
                source_file=path.name,
                reference_answer=answer,
                metadata={k: v for k, v in row.items() if k not in {"question", "task", "prompt", "answer", "reference_answer", "target"}},
            ))
    return tasks


def load_mind2web_actions(data_dir: str | Path) -> list[dict[str, Any]]:
    """Load Mind2Web action representations for action-strategy analysis."""
    root = Path(data_dir)
    records: list[dict[str, Any]] = []
    for path in root.rglob("*.csv"):
        for row in _read_records(path):
            if row.get("action_reprs"):
                records.append({
                    "action": str(row["action_reprs"]),
                    "confirmed": row.get("confirmed_task"),
                    "subdomain": row.get("subdomain", ""),
                    "source": "mind2web",
                    "source_file": path.name,
                })
    return records


def write_jsonl(records: Iterable[dict[str, Any]], output_file: str | Path) -> Path:
    """Write normalized records as JSONL for reproducible local experiments."""
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return output
