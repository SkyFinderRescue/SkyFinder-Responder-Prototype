#!/usr/bin/env python3
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "paddler-feed/data/paddlers-live.json")
data = json.loads(path.read_text(encoding="utf-8"))
assert data["schema_version"] == 2
assert data["operational_use"] is False
assert isinstance(data["paddlers"], list) and data["paddlers"]
allowed = {"LIVE","AGING","STALE","STOPPED","INVALID_GPS","UNKNOWN_TIME","PROTECTED","UNAVAILABLE","INVALID_KML","NO_DATA"}
for p in data["paddlers"]:
    assert p["status"] in allowed, p
    assert "IMEI" not in p and "Text" not in p and "In Emergency" not in p
    if p.get("position_precision") == "coarse-prototype":
        assert p.get("lat") is not None and p.get("lng") is not None
        assert round(p["lat"], 3) == p["lat"]
        assert round(p["lng"], 3) == p["lng"]
    track_points = p.get("track_points", [])
    if track_points:
        assert p.get("position_precision") == "exact-opt-in", p
        assert p.get("breadcrumbs_available") is True, p
        assert p.get("breadcrumb_count") == len(track_points), p
print("validated", len(data["paddlers"]), "paddler records", data["counts"])
