#!/usr/bin/env python3
"""SkyFinder Garmin paddler-feed prototype collector.

Reads a small registry of public Garmin MapShare identifiers, fetches their Raw
KML feeds, and emits a privacy-minimized normalized JSON feed.

Prototype safety choices:
- no Garmin IMEI/internal IDs/message text are retained
- exact coordinates are only published when registry opt_in_exact is true
- otherwise positions are rounded to 3 decimals (~360 ft latitude)
- Garmin SOS fields are intentionally not used as an emergency-alert source
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KPH_TO_MPH = 0.6213711922
M_TO_FT = 3.280839895
DEFAULT_FEED = "https://share.garmin.com/Feed/Share/{feed_id}"
USER_AGENT = "SkyFinder-Paddler-Feed-Prototype/0.1 (+https://github.com/SkyFinderRescue/)"

@dataclass
class FetchResult:
    state: str
    http_status: int | None
    body: bytes | None
    error: str | None = None

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def parse_time_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    fmts = (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    )
    for fmt in fmts:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def number_prefix(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None

def boolish(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None

def _text(elem: ET.Element | None) -> str:
    return "" if elem is None or elem.text is None else elem.text.strip()

def parse_kml(body: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    points: list[dict[str, Any]] = []
    for placemark in root.findall(".//{*}Placemark"):
        point = placemark.find(".//{*}Point")
        if point is None:
            continue

        fields: dict[str, str] = {}
        extended = placemark.find("./{*}ExtendedData")
        if extended is not None:
            for data in extended.findall("./{*}Data"):
                name = data.attrib.get("name", "").strip()
                if not name:
                    continue
                fields[name] = _text(data.find("./{*}value"))

        coords = _text(point.find("./{*}coordinates"))
        if coords:
            first = coords.split()[0].split(",")
            if len(first) >= 2:
                fields.setdefault("Longitude", first[0])
                fields.setdefault("Latitude", first[1])
            if len(first) >= 3:
                fields.setdefault("ElevationRaw", first[2])

        if not fields.get("Name"):
            name_node = placemark.find("./{*}name")
            name_text = _text(name_node)
            if name_text:
                fields["Name"] = name_text
        points.append(fields)
    return points

def newest_point(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not points:
        return None
    ranked = []
    for idx, point in enumerate(points):
        when = parse_time_utc(point.get("Time UTC"))
        ranked.append((when or datetime.min.replace(tzinfo=timezone.utc), idx, point))
    return max(ranked, key=lambda item: (item[0], item[1]))[2]

def fetch_feed(url: str, timeout: float) -> FetchResult:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.google-earth.kml+xml, application/xml, text/xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return FetchResult("ok", getattr(response, "status", 200), response.read())
    except urllib.error.HTTPError as exc:
        state = "protected" if exc.code in (401, 403) else "http_error"
        return FetchResult(state, exc.code, None, f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return FetchResult("network_error", None, None, str(exc.reason))
    except TimeoutError:
        return FetchResult("network_error", None, None, "timeout")

def freshness_status(point: dict[str, Any], collected_at: datetime) -> tuple[str, float | None]:
    event = (point.get("Event") or "").strip().lower()
    when = parse_time_utc(point.get("Time UTC"))
    age_min = None
    if when:
        age_min = max(0.0, (collected_at - when).total_seconds() / 60.0)

    if "tracking turned off" in event:
        return "STOPPED", age_min
    if boolish(point.get("Valid GPS Fix")) is False:
        return "INVALID_GPS", age_min
    if age_min is None:
        return "UNKNOWN_TIME", None
    if age_min <= 15:
        return "LIVE", age_min
    if age_min <= 60:
        return "AGING", age_min
    return "STALE", age_min

def public_position(point: dict[str, Any], exact: bool) -> tuple[float | None, float | None, str]:
    lat = number_prefix(point.get("Latitude"))
    lng = number_prefix(point.get("Longitude"))
    if lat is None or lng is None:
        return None, None, "missing"
    if exact:
        return round(lat, 6), round(lng, 6), "exact-opt-in"
    return round(lat, 3), round(lng, 3), "coarse-prototype"

def normalize(entry: dict[str, Any], point: dict[str, Any], collected_at: datetime) -> dict[str, Any]:
    status, age_min = freshness_status(point, collected_at)
    lat, lng, precision = public_position(point, bool(entry.get("opt_in_exact", False)))

    elevation_m = number_prefix(point.get("Elevation"))
    if elevation_m is None:
        elevation_m = number_prefix(point.get("ElevationRaw"))
    velocity_kph = number_prefix(point.get("Velocity"))
    course = number_prefix(point.get("Course"))

    when = parse_time_utc(point.get("Time UTC"))
    display_name = (point.get("Map Display Name") or point.get("Name") or entry.get("name") or "").strip()

    return {
        "id": entry["id"],
        "name": entry["name"],
        "garmin_display_name": display_name or None,
        "activity": entry.get("activity"),
        "california_relevance": entry.get("california_relevance"),
        "test_only": bool(entry.get("test_only", False)),
        "status": status,
        "last_update_utc": iso_z(when) if when else None,
        "age_minutes": round(age_min, 1) if age_min is not None else None,
        "lat": lat,
        "lng": lng,
        "position_precision": precision,
        "elevation_ft": round(elevation_m * M_TO_FT) if elevation_m is not None else None,
        "speed_mph": round(velocity_kph * KPH_TO_MPH, 1) if velocity_kph is not None else None,
        "heading_deg_true": round(course, 1) if course is not None else None,
        "gps_fix_valid": boolish(point.get("Valid GPS Fix")),
        "device_type": (point.get("Device Type") or "").strip() or None,
        "last_event": (point.get("Event") or "").strip() or None,
        "mapshare_url": f"https://share.garmin.com/{entry['feed_id']}",
    }

def collect_entry(entry: dict[str, Any], collected_at: datetime, timeout: float) -> dict[str, Any]:
    feed_url = entry.get("feed_url") or DEFAULT_FEED.format(feed_id=entry["feed_id"])
    result = fetch_feed(feed_url, timeout)
    base = {
        "id": entry["id"],
        "name": entry["name"],
        "activity": entry.get("activity"),
        "california_relevance": entry.get("california_relevance"),
        "test_only": bool(entry.get("test_only", False)),
        "mapshare_url": f"https://share.garmin.com/{entry['feed_id']}",
        "http_status": result.http_status,
    }

    if result.state == "protected":
        return {**base, "status": "PROTECTED", "error": "MapShare feed requires authorization."}
    if result.state != "ok" or result.body is None:
        return {**base, "status": "UNAVAILABLE", "error": result.error or result.state}

    try:
        points = parse_kml(result.body)
    except ET.ParseError:
        return {**base, "status": "INVALID_KML", "error": "Feed returned malformed XML/KML."}

    point = newest_point(points)
    if point is None:
        return {**base, "status": "NO_DATA", "placemark_points": 0}

    normalized = normalize(entry, point, collected_at)
    return {**normalized, "http_status": result.http_status, "placemark_points": len(points)}

def build_output(registry: dict[str, Any], timeout: float = 15.0, collected_at: datetime | None = None) -> dict[str, Any]:
    collected_at = collected_at or utc_now()
    entries = [e for e in registry.get("paddlers", []) if e.get("enabled", True)]
    paddlers = [collect_entry(entry, collected_at, timeout) for entry in entries]
    counts: dict[str, int] = {}
    for paddler in paddlers:
        status = paddler.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema_version": 1,
        "generated_at_utc": iso_z(collected_at),
        "source": "Garmin MapShare Raw KML",
        "operational_use": False,
        "privacy_note": (
            "Prototype republishes only coarse positions for non-opted-in public test feeds. "
            "Garmin IMEI/internal identifiers/message text are discarded."
        ),
        "sos_note": "Garmin KML is treated as a location source, not as an SOS alert source.",
        "counts": counts,
        "paddlers": paddlers,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="paddler-feed/registry.json")
    parser.add_argument("--output", default="paddler-feed/data/paddlers-live.json")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    output = build_output(registry, args.timeout)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    if args.print_summary:
        print(json.dumps({
            "generated_at_utc": output["generated_at_utc"],
            "counts": output["counts"],
            "paddlers": [
                {
                    "id": p["id"],
                    "status": p["status"],
                    "http_status": p.get("http_status"),
                    "last_update_utc": p.get("last_update_utc"),
                    "age_minutes": p.get("age_minutes"),
                    "device_type": p.get("device_type"),
                    "speed_mph": p.get("speed_mph"),
                    "position_precision": p.get("position_precision"),
                } for p in output["paddlers"]
            ],
        }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
