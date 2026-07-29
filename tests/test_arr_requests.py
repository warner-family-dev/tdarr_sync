from unittest.mock import Mock, patch

import pytest

from tdarr_sync import _arr_get


def test_arr_api_key_is_sent_in_header_not_query_string():
    response = Mock(status_code=200)
    with patch("tdarr_sync.requests.get", return_value=response) as get:
        _arr_get(
            "http://arr.test",
            "sensitive-api-key",
            "/episodefile",
            {"seriesId": 42},
        )

    get.assert_called_once_with(
        "http://arr.test/api/v3/episodefile",
        params={"seriesId": 42},
        headers={"X-Api-Key": "sensitive-api-key"},
        timeout=20,
        allow_redirects=False,
    )
    response.raise_for_status.assert_called_once_with()


def test_arr_redirect_is_rejected_without_following_it():
    response = Mock(status_code=302)
    with (
        patch("tdarr_sync.requests.get", return_value=response),
        pytest.raises(RuntimeError, match="redirect responses are not allowed"),
    ):
        _arr_get("http://arr.test", "sensitive-api-key", "/series")

    response.raise_for_status.assert_not_called()
