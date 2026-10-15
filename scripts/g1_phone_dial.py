#!/usr/bin/env python3
"""Request one preconfigured Android phone contact to place a real call."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


SCHEMA_VERSION = "g1_android_phone_dial_v1"
CONFIRM = "--confirm-g1-phone-dial"
REQUEST_TIMEOUT_SECONDS = 3.0


class DialError(RuntimeError):
    """A stable reason why the local dial bridge was not used."""


def parse_phone_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise DialError("phone_endpoint_invalid")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise DialError("phone_endpoint_invalid")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as error:
        raise DialError("phone_endpoint_not_ip_literal") from error
    if not (address.is_private or address.is_loopback):
        raise DialError("phone_endpoint_not_private")
    try:
        port = parsed.port
    except ValueError as error:
        raise DialError("phone_endpoint_invalid") from error
    if port is None:
        raise DialError("phone_endpoint_port_missing")
    return value.rstrip("/")


def _valid_token(value: str | None) -> bool:
    return value is not None and len(value) >= 32 and not any(character.isspace() for character in value)


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dial the Android phone's one local owner contact; never accepts a phone number."
    )
    parser.add_argument("--phone-url", required=True, help="Private Android bridge URL, e.g. http://192.168.43.1:8765")
    parser.add_argument("--token", help="One-time pairing token displayed by the Android app")
    parser.add_argument("--output-dir", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--preflight", action="store_true")
    action.add_argument(CONFIRM, dest="confirmed", action="store_true")
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        if error.code == 0:
            raise
        raise SystemExit(64) from error
    if arguments.confirmed and not _valid_token(arguments.token):
        parser.print_usage(sys.stderr)
        raise SystemExit(64)
    return arguments


def _request_json(
    opener: Callable[..., Any], request: Request
) -> tuple[int, dict[str, Any]]:
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.status if hasattr(response, "status") else response.getcode()
            raw = response.read()
    except HTTPError as error:
        raise DialError(f"phone_http_{error.code}") from error
    except (TimeoutError, URLError, OSError) as error:
        raise DialError("phone_unreachable") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DialError("phone_invalid_json") from error
    if not isinstance(payload, dict):
        raise DialError("phone_invalid_json")
    return status, payload


def _write_result(output: Path, result: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def _result(mode: str, endpoint: str, state: str, dial_requested: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "contact_id": "owner",
        "phone_endpoint": endpoint,
        "operation_state": state,
        "external_dial_requested": dial_requested,
    }


def run(arguments: argparse.Namespace, opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    mode = "dry_run" if arguments.dry_run else "preflight" if arguments.preflight else "dial"
    endpoint = "unvalidated"
    try:
        endpoint = parse_phone_url(arguments.phone_url)
        opener = urlopen if opener is None else opener
        if arguments.dry_run:
            result = _result(mode, endpoint, "planned", False)
        elif arguments.preflight:
            status, payload = _request_json(opener, Request(endpoint + "/health", method="GET"))
            if status != 200 or payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != "health":
                raise DialError("phone_health_invalid")
            if payload.get("configured") is not True or payload.get("permission_granted") is not True:
                raise DialError("phone_not_ready")
            result = _result(mode, endpoint, "preflight_ok", False)
        else:
            if not _valid_token(arguments.token):
                raise DialError("phone_token_invalid")
            request = Request(
                endpoint + "/dial",
                data=json.dumps({"contact_id": "owner"}).encode("utf-8"),
                method="POST",
                headers={"Authorization": f"Bearer {arguments.token}", "Content-Type": "application/json"},
            )
            status, payload = _request_json(opener, request)
            if (
                status != 202
                or payload.get("schema_version") != SCHEMA_VERSION
                or payload.get("kind") != "dial"
                or payload.get("status") != "accepted"
                or payload.get("contact_id") != "owner"
            ):
                raise DialError("phone_dial_rejected")
            result = _result(mode, endpoint, "accepted", True)
    except DialError as error:
        result = _result(mode, endpoint, "failed", arguments.confirmed)
        result["error_code"] = str(error)
        _write_result(arguments.output_dir, result)
        raise
    _write_result(arguments.output_dir, result)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parse_arguments(sys.argv[1:] if argv is None else argv))
    except DialError as error:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "operation_state": "failed", "error_code": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
