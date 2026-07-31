import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_settings import (
    load_runtime_settings,
    normalize_runtime_settings_payload,
    save_runtime_settings,
)


class RuntimeSettingsTests(unittest.TestCase):
    def test_job_error_count_display_defaults_off(self):
        payload = normalize_runtime_settings_payload({"routes": []})
        self.assertFalse(payload["show_job_error_count"])

    def test_normalize_generates_subdir_from_flow_name(self):
        payload = normalize_runtime_settings_payload(
            {
                "tdarr_server_url": "http://tdarr.local:8266",
                "tdarr_api_key": "not-a-secret-test-value",
                "show_job_error_count": True,
                "routes": [
                    {
                        "source": "sonarr",
                        "tag": "transcode",
                        "flow_name": "Reality TV to 720p",
                    }
                ],
            }
        )
        self.assertEqual(payload["routes"][0]["input_subdir"], "reality-tv-to-720p")
        self.assertTrue(payload["show_job_error_count"])

    def test_rejects_duplicate_source_tag(self):
        with self.assertRaises(ValueError):
            normalize_runtime_settings_payload(
                {
                    "routes": [
                        {"source": "sonarr", "tag": "transcode", "flow_name": "Flow A"},
                        {"source": "sonarr", "tag": "TRANSCODE", "flow_name": "Flow B"},
                    ]
                }
            )

    def test_rejects_unsafe_subdir(self):
        with self.assertRaises(ValueError):
            normalize_runtime_settings_payload(
                {
                    "routes": [
                        {
                            "source": "radarr",
                            "tag": "remux",
                            "flow_name": "REMUX to 1080p",
                            "input_subdir": "../bad",
                        }
                    ]
                }
            )

    def test_rejects_tdarr_url_with_unlisted_host(self):
        with self.assertRaisesRegex(ValueError, "TDARR_ALLOWED_HOSTS"):
            normalize_runtime_settings_payload(
                {"tdarr_server_url": "http://metadata.internal/latest", "routes": []}
            )

    def test_rejects_tdarr_url_with_unsafe_scheme_or_credentials(self):
        for url in (
            "file:///etc/passwd",
            "http://user:password@tdarr.local:8266",
            "http://tdarr.local:8266/?redirect=http://metadata.internal",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_runtime_settings_payload(
                    {"tdarr_server_url": url, "routes": []}
                )

    def test_exact_host_port_allowlist_is_supported(self):
        with patch.dict(
            "os.environ", {"TDARR_ALLOWED_HOSTS": "tdarr.local:8266"}
        ):
            payload = normalize_runtime_settings_payload(
                {"tdarr_server_url": "http://tdarr.local:8266/", "routes": []}
            )
            self.assertEqual(payload["tdarr_server_url"], "http://tdarr.local:8266")

            with self.assertRaises(ValueError):
                normalize_runtime_settings_payload(
                    {"tdarr_server_url": "http://tdarr.local:8267", "routes": []}
                )

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_file = Path(tmp_dir) / "runtime_settings.json"
            saved = save_runtime_settings(
                {
                    "tdarr_server_url": "http://192.168.4.55:8266",
                    "tdarr_api_key": "not-a-secret-test-value",
                    "show_job_error_count": True,
                    "routes": [
                        {
                            "source": "sonarr",
                            "tag": "transcode",
                            "flow_name": "Reality TV to 720p",
                            "input_subdir": "reality-tv-720",
                        }
                    ],
                },
                settings_file,
            )
            loaded = load_runtime_settings(settings_file)
            self.assertEqual(loaded, saved)


    def test_web_auth_bypass_defaults_off(self):
        payload = normalize_runtime_settings_payload({"routes": []})
        self.assertFalse(payload["web_auth_bypass_enabled"])
        self.assertFalse(payload["web_auth_trust_proxy_headers"])
        self.assertEqual(payload["web_auth_trusted_networks"], [])

    def test_normalizes_web_auth_trusted_networks(self):
        payload = normalize_runtime_settings_payload(
            {
                "web_auth_bypass_enabled": True,
                "web_auth_trust_proxy_headers": True,
                "web_auth_trusted_networks": [
                    "192.168.4.55/24",
                    "2001:db8::1/64",
                    "192.168.4.0/24",
                ],
                "routes": [],
            }
        )
        self.assertEqual(
            payload["web_auth_trusted_networks"],
            ["192.168.4.0/24", "2001:db8::/64"],
        )

    def test_rejects_unsafe_web_auth_bypass_settings(self):
        invalid_payloads = (
            {"web_auth_bypass_enabled": True, "routes": []},
            {
                "web_auth_bypass_enabled": True,
                "web_auth_trust_proxy_headers": True,
                "routes": [],
            },
            {
                "web_auth_trust_proxy_headers": True,
                "web_auth_trusted_networks": ["not-a-network"],
                "routes": [],
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                normalize_runtime_settings_payload(payload)


if __name__ == "__main__":
    unittest.main()
