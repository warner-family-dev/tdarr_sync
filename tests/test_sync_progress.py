import tempfile
import time
import unittest
from pathlib import Path

from sync_progress import (
    build_progress_snapshot,
    calculate_eta_seconds,
    read_progress_file,
    write_progress_file,
)


class SyncProgressTests(unittest.TestCase):
    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertIsNone(read_progress_file(Path(tmp_dir) / "missing.json"))

    def test_write_and_read_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "progress.json"
            snapshot = build_progress_snapshot(
                run_id="run-1",
                state="running",
                phase="copy_sonarr",
                action="copying",
                completed_items=2,
                total_items=10,
                started_at=100,
                phase_started_at=100,
                updated_at=105,
            )
            write_progress_file(path, snapshot)
            loaded = read_progress_file(path)
            self.assertEqual(loaded["run_id"], "run-1")
            self.assertEqual(loaded["phase"], "copy_sonarr")
            self.assertEqual(loaded["percent"], 20.0)

    def test_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "progress.json"
            path.write_text("{not-json", encoding="utf-8")
            self.assertIsNone(read_progress_file(path))

    def test_stale_snapshot_returns_none_when_max_age_is_set(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "progress.json"
            snapshot = build_progress_snapshot(
                run_id="run-1",
                state="running",
                phase="copy_sonarr",
                updated_at=int(time.time()) - 3600,
            )
            write_progress_file(path, snapshot)
            self.assertIsNone(read_progress_file(path, max_age_seconds=10))

    def test_eta_thresholds(self):
        self.assertIsNone(calculate_eta_seconds(2, 10, 100, now=120))
        self.assertIsNone(calculate_eta_seconds(3, 10, 100, now=105))
        self.assertEqual(calculate_eta_seconds(5, 10, 100, now=120), 20)
        self.assertEqual(calculate_eta_seconds(10, 10, 100, now=120), 0)


if __name__ == "__main__":
    unittest.main()
