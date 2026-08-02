import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from api.build_version import (
    _resolve_build_version_from_git_files,
    resolve_build_version,
)


class BuildVersionResolverTests(unittest.TestCase):
    def test_immutable_metadata_ignores_runtime_version_environment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            (repo_root / "build-metadata.json").write_text(
                json.dumps(
                    {
                        "image_tag": "latest",
                        "image_published_date": "2026-07-31",
                        "git_version": "dev/v2.3.8",
                        "commit_date": "2026-07-30",
                        "commit_sha": "abcdef1",
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "IMAGE_TAG": "user-selected-tag",
                "APP_IMAGE_TAG": "another-user-selected-tag",
                "APP_GIT_VERSION": "wrong-branch",
            }
            with patch.dict("os.environ", env, clear=False):
                resolved = resolve_build_version(repo_root)

        self.assertEqual(resolved["image_tag"], "latest")
        self.assertEqual(resolved["image_published_date"], "2026-07-31")
        self.assertEqual(resolved["git_version"], "v2.3.8")
        self.assertEqual(resolved["commit_date"], "2026-07-30")
        self.assertEqual(resolved["commit_sha"], "abcdef1")
        self.assertEqual(resolved["source"], "image")

    def test_main_branch_metadata_displays_main(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            (repo_root / "build-metadata.json").write_text(
                json.dumps(
                    {
                        "image_tag": "latest",
                        "image_published_date": "2026-07-31",
                        "git_version": "refs/heads/main",
                        "commit_date": "2026-07-30",
                        "commit_sha": "1234567",
                    }
                ),
                encoding="utf-8",
            )
            resolved = resolve_build_version(repo_root)

        self.assertEqual(resolved["git_version"], "main")
        self.assertEqual(resolved["commit_date"], "2026-07-30")

    def test_reads_branch_sha_and_commit_date_from_git_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            git_dir = repo_root / ".git"
            (git_dir / "refs" / "heads" / "dev").mkdir(parents=True, exist_ok=True)
            (git_dir / "logs").mkdir(parents=True, exist_ok=True)

            (git_dir / "HEAD").write_text(
                "ref: refs/heads/dev/v1.1.3\n", encoding="utf-8"
            )
            full_sha = "a1b2c3d4e5f678901234567890abcdef12345678"
            (git_dir / "refs" / "heads" / "dev" / "v1.1.3").write_text(
                f"{full_sha}\n", encoding="utf-8"
            )

            ts = 1737244800  # 2025-01-19 UTC
            (git_dir / "logs" / "HEAD").write_text(
                f"0000000000000000000000000000000000000000 {full_sha} Test User <test@example.com> {ts} -0600\tcommit: test\n",
                encoding="utf-8",
            )

            resolved = _resolve_build_version_from_git_files(repo_root)
            expected_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            self.assertEqual(resolved["git_version"], "v1.1.3")
            self.assertEqual(resolved["commit_date"], expected_date)
            self.assertEqual(resolved["commit_sha"], full_sha[:7])
            self.assertEqual(resolved["source"], "git")

    def test_reads_sha_from_packed_refs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            git_dir = repo_root / ".git"
            (git_dir / "logs").mkdir(parents=True, exist_ok=True)

            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            full_sha = "1234567890abcdef1234567890abcdef12345678"
            (git_dir / "packed-refs").write_text(
                "# pack-refs with: peeled fully-peeled sorted\n"
                f"{full_sha} refs/heads/main\n",
                encoding="utf-8",
            )

            ts = 1735689600  # 2025-01-01 UTC
            (git_dir / "logs" / "HEAD").write_text(
                f"0000000000000000000000000000000000000000 {full_sha} Test User <test@example.com> {ts} -0600\tcommit: packed\n",
                encoding="utf-8",
            )

            resolved = _resolve_build_version_from_git_files(repo_root)
            self.assertEqual(resolved["git_version"], "main")
            self.assertEqual(resolved["commit_sha"], full_sha[:7])
            self.assertEqual(
                resolved["commit_date"],
                datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            )


if __name__ == "__main__":
    unittest.main()
