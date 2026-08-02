from pathlib import Path
from unittest.mock import patch

import tdarr_sync


def test_route_input_root_groups_source_then_flow():
    route = {"flow_name": "720p", "input_subdir": "720p"}
    with (
        patch.object(tdarr_sync, "TDARR_INPUT_DIR", Path("/input")),
        patch.dict(
            tdarr_sync.SOURCE_INPUT_FOLDERS,
            {"sonarr": "Sonarr", "radarr": "Radarr"},
            clear=True,
        ),
    ):
        assert tdarr_sync._route_input_root(route, "sonarr") == Path(
            "/input/Sonarr/720p"
        )
        assert tdarr_sync._route_input_root(route, "radarr") == Path(
            "/input/Radarr/720p"
        )


def test_route_input_root_derives_safe_flow_folder():
    route = {"flow_name": "TV to 1080p", "input_subdir": ""}
    with (
        patch.object(tdarr_sync, "TDARR_INPUT_DIR", Path("/input")),
        patch.dict(tdarr_sync.SOURCE_INPUT_FOLDERS, {"sonarr": "Sonarr"}),
    ):
        assert tdarr_sync._route_input_root(route, "sonarr") == Path(
            "/input/Sonarr/tv-to-1080p"
        )


def test_no_routes_does_not_guess_from_environment():
    with patch.object(tdarr_sync, "load_runtime_settings", return_value={"routes": []}):
        _, routes, legacy_mode = tdarr_sync.load_effective_routes()

    assert legacy_mode is False
    assert routes == []


def test_restore_destination_reads_new_source_flow_hierarchy():
    with (
        patch.object(tdarr_sync, "BASE_DIR", Path("/tv")),
        patch.object(tdarr_sync, "RADARR_LOCAL_MOUNT_BASE_PATH", Path("/movies")),
        patch.dict(
            tdarr_sync.SOURCE_INPUT_FOLDERS,
            {"sonarr": "Sonarr", "radarr": "Radarr"},
            clear=True,
        ),
    ):
        sonarr = tdarr_sync._resolve_restore_destination(
            Path("Sonarr/720p/Show/Season 01/Episode.mkv"), []
        )
        radarr = tdarr_sync._resolve_restore_destination(
            Path("Radarr/1080p/Movie (2024)/Movie.mkv"), []
        )

    assert sonarr == (Path("/tv"), Path("Show/Season 01/Episode.mkv"))
    assert radarr == (Path("/movies"), Path("Movie (2024)/Movie.mkv"))


def test_restore_destination_retains_legacy_layouts():
    routes = [
        {
            "source": "sonarr",
            "flow_name": "720p",
            "input_subdir": "720p",
        }
    ]
    with (
        patch.object(tdarr_sync, "BASE_DIR", Path("/tv")),
        patch.object(tdarr_sync, "RADARR_LOCAL_MOUNT_BASE_PATH", Path("/movies")),
    ):
        routed_sonarr = tdarr_sync._resolve_restore_destination(
            Path("720p/__sonarr_input__/Show/Episode.mkv"), routes
        )
        prefixed_radarr = tdarr_sync._resolve_restore_destination(
            Path("__radarr_input__/Movie/Movie.mkv"), routes
        )
        direct_sonarr = tdarr_sync._resolve_restore_destination(
            Path("Show/Episode.mkv"), routes
        )

    assert routed_sonarr == (Path("/tv"), Path("Show/Episode.mkv"))
    assert prefixed_radarr == (Path("/movies"), Path("Movie/Movie.mkv"))
    assert direct_sonarr == (Path("/tv"), Path("Show/Episode.mkv"))
