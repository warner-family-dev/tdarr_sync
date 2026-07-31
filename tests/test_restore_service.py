import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from api.restore_service import (
    RestoreAuthError,
    RestoreConfig,
    RestoreError,
    RestoreSelectionError,
    RestoreService,
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
            sonarr_tag_names=(),
            sonarr_base_path=Path("/tv"),
            local_mount_base_path=Path("/media"),
            admin_password="secret",
        )

    def test_fetch_series_matches_any_settings_route_tag(self):
        self.config.sonarr_tag_names = ("transcode", "kids")
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        def fake_sonarr_get(endpoint, params=None):
            del params
            if endpoint == "/tag":
                return [
                    {"id": 1, "label": "transcode"},
                    {"id": 2, "label": "Kids"},
                ]
            if endpoint == "/series":
                return [
                    {"id": 10, "tags": [1]},
                    {"id": 20, "tags": [2]},
                    {"id": 30, "tags": [3]},
                ]
            raise AssertionError(endpoint)

        with patch.object(service, "_sonarr_get", side_effect=fake_sonarr_get):
            series = service._fetch_series_list()

        self.assertEqual([item["id"] for item in series], [10, 20])

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

        with (
            patch.object(service, "_load_processed_map", return_value={}),
            patch.object(
                service,
                "_fetch_series_list",
                return_value=[{"id": 42, "title": "Example"}],
            ),
            patch.object(service, "_fetch_episode_files", return_value=[]),
            patch.object(service, "_build_entries", return_value=[dummy_entry]),
            self.assertRaises(RestoreSelectionError),
        ):
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

    def test_catalog_snapshot_does_not_resolve_episode_paths_on_disk(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        episode_path = "/tmp/base/Example/Season 01/episode.mkv"
        with (
            patch.object(
                service,
                "_fetch_episode_files",
                return_value=[{"path": episode_path, "seasonNumber": 1}],
            ),
            patch.object(
                service,
                "_resolve_under_base",
                side_effect=AssertionError("catalog touched the filesystem resolver"),
            ),
        ):
            snapshot = service._series_snapshot(
                {"id": 42, "title": "Example"}, {episode_path: 123}
            )

        self.assertEqual(snapshot.total, 1)
        self.assertEqual(snapshot.processed, 1)

    def test_catalog_path_normalization_rejects_parent_traversal(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        self.assertEqual(
            service._catalog_path_under_base(Path("Example/episode.mkv")),
            Path("/tmp/base/Example/episode.mkv"),
        )
        self.assertIsNone(
            service._catalog_path_under_base(Path("/tmp/base/../outside.mkv"))
        )

    def test_series_catalog_reuses_cache_while_database_is_unchanged(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()
        entries = [Mock(spec=SeriesEntry)]

        with (
            patch.object(service, "_state_database_mtime_ns", return_value=10),
            patch.object(service, "_load_processed_map", return_value={}) as load_map,
            patch.object(service, "_fetch_series_list", return_value=[]) as fetch,
            patch.object(service, "_build_entries", return_value=entries) as build,
        ):
            self.assertIs(service.series_catalog(), entries)
            self.assertIs(service.series_catalog(), entries)

        load_map.assert_called_once_with()
        fetch.assert_called_once_with()
        build.assert_called_once_with([], {})

    def test_series_catalog_cache_invalidates_when_database_changes(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        with (
            patch.object(service, "_state_database_mtime_ns", side_effect=[10, 11]),
            patch.object(service, "_load_processed_map", return_value={}) as load_map,
            patch.object(service, "_fetch_series_list", return_value=[]),
            patch.object(service, "_build_entries", side_effect=[[], []]),
        ):
            service.series_catalog()
            service.series_catalog()

        self.assertEqual(load_map.call_count, 2)

    def test_sonarr_api_key_is_sent_in_header_not_query_string(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()
        response = Mock(status_code=200)
        response.json.return_value = [{"id": 1}]

        with patch("api.restore_service.requests.get", return_value=response) as get:
            result = service._sonarr_get("/episodefile", {"seriesId": 42})

        self.assertEqual(result, [{"id": 1}])
        get.assert_called_once_with(
            "http://localhost:8989/api/v3/episodefile",
            params={"seriesId": 42},
            headers={"X-Api-Key": "abc123"},
            timeout=20,
            allow_redirects=False,
        )

    def test_sonarr_redirect_is_rejected_without_following_it(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()
        response = Mock(status_code=302)

        with (
            patch("api.restore_service.requests.get", return_value=response),
            self.assertRaisesRegex(RestoreError, "redirect responses are not allowed"),
        ):
            service._sonarr_get("/series")

        response.raise_for_status.assert_not_called()

    def test_sonarr_http_error_does_not_expose_api_key(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()
        response = Mock(status_code=401)
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 for http://localhost/api/v3/series?apikey=abc123",
            response=response,
        )

        with (
            patch("api.restore_service.requests.get", return_value=response),
            self.assertRaises(RestoreError) as caught,
        ):
            service._sonarr_get("/series")

        self.assertEqual(
            str(caught.exception), "Sonarr request failed with HTTP status 401."
        )
        self.assertNotIn("abc123", str(caught.exception))

    def test_sonarr_network_error_does_not_expose_request_url(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        with (
            patch(
                "api.restore_service.requests.get",
                side_effect=requests.ConnectionError("http://host?apikey=abc123"),
            ),
            self.assertRaises(RestoreError) as caught,
        ):
            service._sonarr_get("/series")

        self.assertEqual(
            str(caught.exception), "Sonarr request failed due to a network error."
        )
        self.assertNotIn("abc123", str(caught.exception))

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

        error_outcome = SeriesOutcome(
            series_id=99,
            title="Broken",
            errors=["failure"],
            _db_paths_to_remove=["/tmp/foo"],
        )

        with (
            patch.object(service, "_load_processed_map", return_value={}),
            patch.object(
                service,
                "_fetch_series_list",
                return_value=[{"id": 99, "title": "Broken"}],
            ),
            patch.object(service, "_fetch_episode_files", return_value=[]),
            patch.object(service, "_build_entries", return_value=[entry]),
            patch.object(service, "_restore_single_series", return_value=error_outcome),
            patch("api.restore_service.db.delete_processed_entries") as mock_delete,
        ):
            service.restore(
                password="secret", structured=[{"series_id": 99, "seasons": None}]
            )
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

        with (
            patch.object(service, "_load_processed_map", return_value={}),
            patch.object(
                service,
                "_fetch_series_list",
                return_value=[{"id": 7, "title": "Clean"}],
            ),
            patch.object(service, "_fetch_episode_files", return_value=[]),
            patch.object(service, "_build_entries", return_value=[entry]),
            patch.object(
                service, "_restore_single_series", return_value=success_outcome
            ),
            patch("api.restore_service.db.delete_processed_entries") as mock_delete,
        ):
            service.restore(
                password="secret", structured=[{"series_id": 7, "seasons": None}]
            )
            mock_delete.assert_called_once()

    def test_restore_handles_unexpected_exception(self):
        with patch.object(RestoreService, "_load_config", return_value=self.config):
            service = RestoreService()

        entry = SeriesEntry(
            index=1,
            series_id=55,
            title="Boom",
            processed=0,
            total=0,
            status="none",
            last_processed_at=None,
            last_processed_at_iso=None,
            seasons=[],
        )

        with (
            patch.object(service, "_load_processed_map", return_value={}),
            patch.object(
                service,
                "_fetch_series_list",
                return_value=[{"id": 55, "title": "Boom"}],
            ),
            patch.object(service, "_fetch_episode_files", return_value=[]),
            patch.object(service, "_build_entries", return_value=[entry]),
            patch.object(
                service, "_restore_single_series", side_effect=RuntimeError("boom")
            ),
            patch("api.restore_service.db.delete_processed_entries") as mock_delete,
        ):
            outcome = service.restore(
                password="secret", structured=[{"series_id": 55, "seasons": None}]
            )
            mock_delete.assert_not_called()
            self.assertTrue(outcome.results)
            self.assertTrue(outcome.results[0].errors)


if __name__ == "__main__":
    unittest.main()
