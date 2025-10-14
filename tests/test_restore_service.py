import unittest
from pathlib import Path
from unittest.mock import patch

from api.restore_service import (
    RestoreAuthError,
    RestoreConfig,
    RestoreService,
    RestoreSelectionError,
    SeasonEntry,
    SeriesEntry,
    SeriesOutcome,
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
            service.restore(password="wrong", selection_expr="1")

    def test_restore_rejects_invalid_season_selection(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        dummy_entry = SeriesEntry(
            index=1,
            series_id=42,
            title="Example",
            processed=0,
            total=0,
            status="none",
            last_processed_at=None,
            last_processed_at_iso=None,
            seasons=[
                SeasonEntry(
                    number=1,
                    name="Season 01",
                    processed=0,
                    total=0,
                    status="none",
                    last_processed_at=None,
                    last_processed_at_iso=None,
                )
            ],
        )

        with patch.object(service, "_load_processed_map", return_value={}), patch.object(
            service, "_fetch_series_list", return_value=[{"id": 42, "title": "Example"}]
        ), patch.object(service, "_build_entries", return_value=[dummy_entry]):
            with self.assertRaises(RestoreSelectionError):
                service.restore(
                    password="secret",
                    structured=[{"series_id": 42, "seasons": [99]}],
                )

    def test_episode_season_number_handles_none(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        self.assertEqual(service._episode_season_number({}), 0)
        self.assertEqual(service._episode_season_number({"seasonNumber": None}), 0)
        self.assertEqual(service._episode_season_number({"seasonNumber": "3"}), 3)
        self.assertEqual(service._episode_season_number({"seasonNumber": "abc"}), 0)

    def test_restore_skips_db_cleanup_when_errors(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        entry = SeriesEntry(
            index=1,
            series_id=99,
            title="Broken",
            processed=0,
            total=0,
            status="none",
            last_processed_at=None,
            last_processed_at_iso=None,
            seasons=[],
        )

        error_outcome = SeriesOutcome(series_id=99, title="Broken", errors=["failure"], _db_paths_to_remove=["/tmp/foo"])

        with patch.object(service, "_load_processed_map", return_value={}), patch.object(
            service, "_fetch_series_list", return_value=[{"id": 99, "title": "Broken"}]
        ), patch.object(service, "_build_entries", return_value=[entry]), patch.object(
            service, "_restore_single_series", return_value=error_outcome
        ), patch("api.restore_service.db.delete_processed_entries") as mock_delete:
            service.restore(password="secret", structured=[{"series_id": 99, "seasons": None}])
            mock_delete.assert_not_called()

    def test_restore_cleans_db_on_success(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        entry = SeriesEntry(
            index=1,
            series_id=7,
            title="Clean",
            processed=0,
            total=0,
            status="none",
            last_processed_at=None,
            last_processed_at_iso=None,
            seasons=[],
        )

        success_outcome = SeriesOutcome(
            series_id=7,
            title="Clean",
            restored=["/tmp/foo"],
            _db_paths_to_remove=["/tmp/foo"],
        )

        with patch.object(service, "_load_processed_map", return_value={}), patch.object(
            service, "_fetch_series_list", return_value=[{"id": 7, "title": "Clean"}]
        ), patch.object(service, "_build_entries", return_value=[entry]), patch.object(
            service, "_restore_single_series", return_value=success_outcome
        ), patch("api.restore_service.db.delete_processed_entries") as mock_delete:
            service.restore(password="secret", structured=[{"series_id": 7, "seasons": None}])
            mock_delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
