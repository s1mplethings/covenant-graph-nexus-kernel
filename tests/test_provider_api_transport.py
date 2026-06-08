from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.check_connectivity as check_connectivity


class ProviderApiTransportTests(unittest.TestCase):
    def test_gptsapi_v1_base_url_is_preserved(self) -> None:
        self.assertEqual("https://gptsapi.net/v1", check_connectivity._normalize_base_url("https://gptsapi.net/v1/"))
        self.assertTrue(check_connectivity._is_gptsapi_base_url("https://gptsapi.net/v1"))
        self.assertEqual(
            "https://gptsapi.net/v1/chat/completions",
            check_connectivity._chat_completions_endpoint("https://gptsapi.net/v1"),
        )

    def test_gptsapi_endpoint_does_not_duplicate_v1(self) -> None:
        self.assertEqual(
            "https://api.gptsapi.net/v1/chat/completions",
            check_connectivity._join_endpoint("https://api.gptsapi.net/v1", "/v1/chat/completions"),
        )
        self.assertNotIn(
            "/v1/v1/",
            check_connectivity._chat_completions_endpoint("https://api.gptsapi.net/v1"),
        )

    def test_gptsapi_base_without_v1_gets_openai_compatible_path(self) -> None:
        self.assertEqual(
            "https://api.gptsapi.net/v1/chat/completions",
            check_connectivity._chat_completions_endpoint("https://api.gptsapi.net"),
        )

    def test_retry_classifier_treats_key_limit_403_as_non_retryable(self) -> None:
        self.assertFalse(check_connectivity._error_is_retryable('HTTP 403: {"error":"Key usage limit exceeded"} [retryable=false]'))
        self.assertTrue(check_connectivity._error_is_retryable("HTTP 429: rate limited [retryable=true]"))


if __name__ == "__main__":
    unittest.main()
