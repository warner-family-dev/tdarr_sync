import tempfile
import unittest
from pathlib import Path

from runtime_settings import load_runtime_settings, normalize_runtime_settings_payload, save_runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_normalize_generates_subdir_from_flow_name(self):
        payload = normalize_runtime_settings_payload(
            {
                "tdarr_server_url": "http://tdarr.local:8266",
                "tdarr_api_key": "not-a-secret-test-value",
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

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_file = Path(tmp_dir) / "runtime_settings.json"
            saved = save_runtime_settings(
                {
                    "tdarr_server_url": "http://192.168.4.55:8266",
                    "tdarr_api_key": "not-a-secret-test-value",
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


if __name__ == "__main__":
    unittest.main()
