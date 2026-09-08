import json
import tempfile
import unittest
from pathlib import Path

from browser_agent.kaggle_data import load_browse_tasks, load_mind2web_actions, write_jsonl


class TestKaggleData(unittest.TestCase):
    def test_load_browse_tasks_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks.csv").write_text(
                "question,answer,extra\nFind the price of shoes,1299,x\n",
                encoding="utf-8",
            )
            tasks = load_browse_tasks(root)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task, "Find the price of shoes")
            self.assertEqual(tasks[0].reference_answer, "1299")
            self.assertEqual(tasks[0].metadata, {"extra": "x"})

    def test_load_mind2web_actions_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "actions.csv").write_text(
                "action_reprs,confirmed_task,subdomain\nclick(1),Find shoes,shopping\n",
                encoding="utf-8",
            )
            records = load_mind2web_actions(root)
            self.assertEqual(records[0]["action"], "click(1)")
            self.assertEqual(records[0]["confirmed"], "Find shoes")

    def test_write_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = write_jsonl([{"task": "Find shoes"}], Path(tmp) / "out.jsonl")
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows, [{"task": "Find shoes"}])


if __name__ == "__main__":
    unittest.main()
