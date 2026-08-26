#!/usr/bin/env python3
"""Validate SkyFinder paddler test registry consent and privacy rules."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

CONSENT_VERSION = "paddler-field-test-v1"


def parse_utc(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value.endswith("Z")
    except ValueError:
        return False


def validate_entry(entry: dict) -> list[str]:
    errors: list[str] = []
    ident = entry.get("id", "<missing-id>")
    for required in ("id", "name", "activity", "feed_id"):
        if not str(entry.get(required) or "").strip():
            errors.append(f"{ident}: missing {required}")

    exact = entry.get("opt_in_exact") is True
    breadcrumbs = entry.get("opt_in_breadcrumbs") is True
    consent = entry.get("consent")

    if breadcrumbs and not exact:
        errors.append(f"{ident}: breadcrumbs require exact-location opt-in")

    if exact or breadcrumbs:
        if not isinstance(consent, dict):
            errors.append(f"{ident}: consent record required for exact location/breadcrumbs")
        else:
            if consent.get("version") != CONSENT_VERSION:
                errors.append(f"{ident}: consent version must be {CONSENT_VERSION}")
            if not parse_utc(consent.get("consented_at_utc")):
                errors.append(f"{ident}: valid UTC consent timestamp required")
            if consent.get("exact_location") is not exact:
                errors.append(f"{ident}: consent exact_location must match opt_in_exact")
            if consent.get("breadcrumbs") is not breadcrumbs:
                errors.append(f"{ident}: consent breadcrumbs must match opt_in_breadcrumbs")
            if consent.get("voluntary") is not True:
                errors.append(f"{ident}: voluntary consent must be explicit")
            if consent.get("removal_requested") is True and entry.get("enabled", True):
                errors.append(f"{ident}: removal-requested participant cannot remain enabled")

    forbidden = {"email", "phone", "address", "street_address", "imei", "device_imei"}
    for key in entry:
        if str(key).lower() in forbidden:
            errors.append(f"{ident}: private/unnecessary registry field not allowed: {key}")
    return errors


def validate_registry(data: dict) -> list[str]:
    errors: list[str] = []
    entries = data.get("paddlers")
    if not isinstance(entries, list):
        return ["registry paddlers must be a list"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("registry entry must be an object")
            continue
        ident = str(entry.get("id") or "")
        if ident in seen:
            errors.append(f"duplicate id: {ident}")
        seen.add(ident)
        errors.extend(validate_entry(entry))
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", nargs="?", default="paddler-feed/registry.json")
    args = ap.parse_args()
    data = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    errors = validate_registry(data)
    if errors:
        print("Registry validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(json.dumps({"registry": args.registry, "entries": len(data.get("paddlers", [])), "status": "valid"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
