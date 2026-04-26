import tempfile
import unittest
from pathlib import Path

from api.sync_runner import SyncRunner
from sync_progress import read_progress_file


class SyncRunnerTests(unittest.TestCase):
    def test_missing_script_marks_progress_failed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            progress_file = Path(tmp_dir) / "progress.json"
            runner = SyncRunner(Path(tmp_dir) / "missing.py", "python", progress_file, env={})
            runner._run("run-1", dry_run=False, selection=None)
            snapshot = read_progress_file(progress_file)
            self.assertEqual(snapshot["run_id"], "run-1")
            self.assertEqual(snapshot["state"], "failed")
            self.assertTrue(snapshot["error"])


if __name__ == "__main__":
    unittest.main()
