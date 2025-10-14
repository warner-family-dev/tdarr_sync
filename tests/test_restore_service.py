import unittest
from pathlib import Path
from unittest.mock import patch

from api.restore_service import (
    RestoreAuthError,
    RestoreConfig,
    RestoreService,
    RestoreSelectionError,
    parse_selection,
)


class ParseSelectionTests(unittest.TestCase):
    def test_all_keyword(self):
        self.assertEqual(parse_selection("all", 4), [1, 2, 3, 4])

    def test_ranges_and_lists(self):
        self.assertEqual(parse_selection("1,3,5-7", 8), [1, 3, 5, 6, 7])

    def test_duplicates_removed(self):
        self.assertEqual(parse_selection("2,2,3,1", 3), [2, 3, 1])

    def test_invalid_token_raises(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("a,b", 5)

    def test_out_of_range_raises(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("6", 5)

    def test_empty_expression_raises(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("", 3)

    def test_zero_max_index_raises(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("1", 0)


class RestoreServiceAuthTests(unittest.TestCase):
    def setUp(self):
        self.config = RestoreConfig(
            base_dir=Path("/tmp/base"),
            archive_dir=Path("/tmp/archive"),
            backup_suffix=".orig",
            rename_originals=True,
            move_originals=True,
            state_db_file=Path("/tmp/state.db"),
            tdarr_output_dir=Path("/tmp/output"),
            sonarr_url="http://localhost:8989",
            sonarr_api_key="abc123",
            sonarr_tag_name=None,
            sonarr_base_path=Path("/tv"),
            local_mount_base_path=Path("/media"),
            admin_password="secret",
        )

    def test_restore_rejects_invalid_password(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()
        with self.assertRaises(RestoreAuthError):
            service.restore("1", "wrong")


if __name__ == "__main__":
    unittest.main()
