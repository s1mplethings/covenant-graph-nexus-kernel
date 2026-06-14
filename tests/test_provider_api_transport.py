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

    def test_openai_compatible_endpoint_uses_chat_for_gptsapi(self) -> None:
        self.assertEqual(
            "https://api.gptsapi.net/v1/chat/completions",
            check_connectivity._openai_compatible_endpoint("https://api.gptsapi.net/v1"),
        )

    def test_openai_compatible_payload_converts_chat_to_responses_input(self) -> None:
        payload = check_connectivity._build_openai_compatible_payload(
            "https://api.openai.com/v1",
            {
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.1,
                "max_tokens": 12,
            },
        )

        self.assertEqual("gpt-test", payload["model"])
        self.assertEqual("user: hello", payload["input"])
        self.assertEqual(12, payload["max_output_tokens"])

    def test_retry_classifier_treats_key_limit_403_as_non_retryable(self) -> None:
        self.assertFalse(check_connectivity._error_is_retryable('HTTP 403: {"error":"Key usage limit exceeded"} [retryable=false]'))
        self.assertTrue(check_connectivity._error_is_retryable("HTTP 429: rate limited [retryable=true]"))

    def test_provider_error_type_classifies_transport_and_key_limit(self) -> None:
        self.assertEqual(
            "PROVIDER_TRANSPORT_UNSTABLE",
            check_connectivity._provider_error_type("request failed: SSLError: SSLV3_ALERT_BAD_RECORD_MAC"),
        )
        self.assertEqual(
            "PROVIDER_TRANSPORT_UNSTABLE",
            check_connectivity._provider_error_type("HTTP 520: web server returned unknown error [retryable=true]"),
        )
        self.assertEqual(
            "PROVIDER_TRANSPORT_UNSTABLE",
            check_connectivity._provider_error_type("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"),
        )
        self.assertEqual(
            "PROVIDER_KEY_USAGE_LIMIT",
            check_connectivity._provider_error_type('HTTP 403: {"error":"Key usage limit exceeded"} [retryable=false]'),
        )

    def test_openai_compatible_endpoint_and_payload_normalize_for_gptsapi(self) -> None:
        root = "https://api.gptsapi.net/v1"
        endpoint = check_connectivity._openai_compatible_endpoint(root)
        self.assertEqual("https://api.gptsapi.net/v1/chat/completions", endpoint)
        payload = check_connectivity._build_openai_compatible_payload(
            root,
            {"model": "gpt-5.4-nano", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10},
        )
        self.assertEqual({"model": "gpt-5.4-nano", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10,}, payload)

    def test_openai_compatible_endpoint_and_payload_normalize_for_responses(self) -> None:
        root = "https://api.example.com"
        endpoint = check_connectivity._openai_compatible_endpoint(root)
        self.assertEqual("https://api.example.com/responses", endpoint)
        payload = check_connectivity._build_openai_compatible_payload(
            root,
            {"model": "gpt-5.4-nano", "messages": [{"role": "user", "content": "ping"}], "temperature": 0.2, "max_tokens": 10},
        )
        self.assertEqual(
            {"model": "gpt-5.4-nano", "input": "user: ping", "temperature": 0.2, "max_output_tokens": 10},
            payload,
        )


if __name__ == "__main__":
    unittest.main()
