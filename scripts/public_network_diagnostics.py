#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import sys
from typing import Any
from urllib.parse import urlsplit


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.capability_builder import (  # noqa: E402
    PublicNetworkClient,
    PublicNetworkMode,
    PublicNetworkPolicyError,
    PublicNetworkTransport,
    is_fake_ip_address,
    is_public_address,
)


def _resolve(host: str) -> tuple[str, ...]:
    try:
        return tuple(sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}))
    except OSError:
        return ()


def diagnose(url: str, *, smoke: bool = False) -> tuple[dict[str, Any], int]:
    host = urlsplit(url).hostname or ""
    addresses = _resolve(host) if host else ()
    fake_ip = any(is_fake_ip_address(address) for address in addresses)
    try:
        transport = PublicNetworkTransport.from_environment()
    except PublicNetworkPolicyError as exc:
        return ({
            "kind": "CGKNPublicNetworkDiagnostic",
            "schema_version": "1.0",
            "mode": "INVALID",
            "proxy_configured": False,
            "proxy_endpoint_class": "INVALID_OR_MISSING",
            "direct_dns_result": list(addresses),
            "fake_ip_detected": fake_ip,
            "public_fetch_possible": False,
            "safe_classification": exc.classification.value,
        }, 2)

    proxy_mode = transport.mode is PublicNetworkMode.TRUSTED_LOCAL_PROXY
    result: dict[str, Any] = {
        "kind": "CGKNPublicNetworkDiagnostic",
        "schema_version": "1.0",
        "mode": transport.mode.value,
        "proxy_configured": proxy_mode,
        "proxy_endpoint_class": "EXPLICIT_LOOPBACK" if proxy_mode else "NOT_CONFIGURED",
        "direct_dns_result": list(addresses),
        "fake_ip_detected": fake_ip,
        "public_fetch_possible": proxy_mode or bool(addresses and all(is_public_address(address) for address in addresses)),
        "safe_classification": "READY_FOR_EXPLICIT_SMOKE",
    }
    if not proxy_mode and fake_ip:
        result["public_fetch_possible"] = False
        result["safe_classification"] = "PUBLIC_NETWORK_BLOCKED_ENVIRONMENT"
        result["operator_action"] = "Set CGKN_PUBLIC_NETWORK_MODE=proxy and an explicit credential-free loopback CGKN_PUBLIC_HTTP_PROXY."
    elif not result["public_fetch_possible"]:
        result["safe_classification"] = "PUBLIC_DNS_FAILURE"

    if smoke:
        if not proxy_mode and fake_ip:
            result["smoke"] = {"status": "BLOCKED_ENVIRONMENT_PROXY_NOT_CONFIGURED"}
            return result, 3
        try:
            fetched = PublicNetworkClient(network_transport=transport).get(url)
            passed = 200 <= int(fetched["status_code"]) < 300 and bool(str(fetched["text"]).strip())
            result["smoke"] = {
                "status": "PASS" if passed else "PUBLIC_TARGET_FAILURE",
                "status_code": fetched["status_code"],
                "final_url": fetched["final_url"],
                "content_type": fetched["content_type"],
                "bytes_read": fetched["bytes_read"],
                "redirect_count": fetched["redirect_count"],
                "transport_mode": fetched["transport_mode"],
            }
            return result, 0 if passed else 4
        except PublicNetworkPolicyError as exc:
            result["smoke"] = {"status": exc.classification.value, "detail": str(exc)}
            return result, 4
    return result, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose CGKN's explicit public-network transport without discovering proxy settings.")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result, exit_code = diagnose(args.url, smoke=args.smoke)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
