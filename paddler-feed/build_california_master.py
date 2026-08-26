#!/usr/bin/env python3
"""Build a California-only public paddler identity index from prototype sources.

This intentionally excludes live GPS and private contact information. It is an
identity/source coverage index used to measure California discovery progress and
prioritize later matching to public/permissioned live trackers. Displayed race
identities are conservatively classified so obvious teams/crews are not counted
as verified individual people.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def normalize_craft(value: str) -> str | None:
    raw = " ".join(str(value or "").split()).upper()
    n = norm(raw)
    if not n:
        return None
    if n in {"oc 1", "oc 2", "oc 3", "oc 4", "oc 6", "v 1", "v 3", "v 6"} or "outrigger" in n:
        return "OUTRIGGER"
    if n in {"ss 1", "ss 2"} or "surfski" in n or "surf ski" in n:
        return "SURFSKI"
    if "prone" in n or "paddleboard" in n or "paddle board" in n:
        return "PRONE/PADDLEBOARD"
    if n == "sup" or "stand up paddle" in n or "standup paddle" in n or n.startswith("sup "):
        return "SUP"
    if "kayak" in n or n == "k1" or n == "k 1":
        return "KAYAK"
    return raw


def classify_identity(name: str) -> str:
    """Conservative display-identity classification; never claims verified residency/personhood."""
    cleaned = " ".join((name or "").split())
    n = norm(cleaned)
    if not n:
        return "UNKNOWN"
    group_markers = (
        " team ", " crew ", " canoe club ", " paddling club ", " paddle club ",
        " outrigger club ", " yacht club ", " racing team ", " relay team ",
    )
    padded = f" {n} "
    if any(marker in padded for marker in group_markers) or n.startswith("team ") or n.endswith(" team"):
        return "TEAM_OR_CREW"
    tokens = cleaned.split()
    if 2 <= len(tokens) <= 5 and all(re.fullmatch(r"[A-Za-z][A-Za-z'’.-]*", token) for token in tokens):
        return "LIKELY_PERSON"
    return "UNKNOWN"


def load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def add_person(master, name, source, crafts=None, years=None, handles=None, profiles=None, evidence=None):
    name = " ".join((name or "").split())
    key = norm(name)
    if not key or len(key) < 3:
        return
    item = master.setdefault(key, {
        "name": name,
        "crafts": set(),
        "sources": set(),
        "years": set(),
        "public_handles": set(),
        "public_profiles": set(),
        "evidence": [],
    })
    if item["name"].islower() and not name.islower():
        item["name"] = name
    item["sources"].add(source)
    for c in crafts or []:
        c = normalize_craft(c)
        if c:
            item["crafts"].add(c)
    for y in years or []:
        try:
            y = int(y)
        except Exception:
            continue
        if 1900 <= y <= 2100:
            item["years"].add(y)
    for h in handles or []:
        if h:
            item["public_handles"].add(str(h))
    for u in profiles or []:
        if u:
            item["public_profiles"].add(str(u))
    if evidence and len(item["evidence"]) < 12:
        item["evidence"].append(evidence)


def source_summary(data):
    return (data or {}).get("summary", {}) if isinstance(data, dict) else {}


def ingest_discovered(master, data):
    included = excluded = 0
    for p in (data or {}).get("paddlers", []):
        if int(p.get("california_event_count") or 0) <= 0:
            excluded += 1
            continue
        ca_events = [e for e in p.get("events", []) if e.get("california")]
        evidence = None
        if ca_events:
            e = ca_events[0]
            evidence = {"source": "PaddleGuru seed crawl", "event": e.get("event"), "region": e.get("region"), "url": e.get("source_url")}
        add_person(master, p.get("name"), "PaddleGuru seed crawl", p.get("crafts"), handles=p.get("public_handles"), evidence=evidence)
        included += 1
    return included, excluded


def ingest_paddleguru_graph(master, data):
    included = excluded = 0
    for p in (data or {}).get("athletes", []):
        if int(p.get("california_event_count") or 0) <= 0:
            excluded += 1
            continue
        add_person(master, p.get("name"), "PaddleGuru graph", p.get("crafts"), handles=p.get("public_handles"), evidence={"source": "PaddleGuru graph", "california_event_count": p.get("california_event_count")})
        included += 1
    return included, excluded


def ingest_webscorer(master, data):
    included = excluded = 0
    for p in (data or {}).get("paddlers", []):
        if int(p.get("california_race_count") or 0) <= 0:
            excluded += 1
            continue
        add_person(master, p.get("name"), "Webscorer California", p.get("crafts"), evidence={"source": "Webscorer California", "california_race_count": p.get("california_race_count")})
        included += 1
    return included, excluded


def ingest_simple(master, data, source, craft_override=None):
    included = 0
    for p in (data or {}).get("paddlers", []):
        crafts = craft_override or p.get("crafts") or ([p.get("craft")] if p.get("craft") else [])
        profiles = p.get("public_profile_urls") or p.get("public_profiles") or []
        add_person(master, p.get("name"), source, crafts, years=p.get("years"), handles=p.get("public_handles"), profiles=profiles, evidence={"source": source})
        included += 1
    return included, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="paddler-feed/data")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    definitions = [
        ("discovered-paddlers.json", "PaddleGuru seed crawl", ingest_discovered),
        ("paddleguru-graph.json", "PaddleGuru graph", ingest_paddleguru_graph),
        ("webscorer-paddlers.json", "Webscorer California", ingest_webscorer),
        ("supracer-ca-paddlers.json", "SUP Racer California", None),
        ("outrigger-world-paddlers.json", "Outrigger World Southern California", None),
        ("misc-ca-archive-paddlers.json", "Independent California archives", None),
        ("catalina-classic-archive.json", "Catalina Classic archive", None),
        ("paddlesplash-paddlers.json", "PaddleSplash California", None),
    ]

    master = {}
    audit = []
    for filename, label, adapter in definitions:
        path = data_dir / filename
        data = load(path)
        if data is None:
            audit.append({"file": filename, "source": label, "status": "MISSING_OR_UNREADABLE", "included": 0, "excluded_non_california": 0})
            continue
        if adapter:
            included, excluded = adapter(master, data)
        elif filename == "catalina-classic-archive.json":
            included, excluded = ingest_simple(master, data, label, craft_override=["PRONE/PADDLEBOARD"])
        else:
            included, excluded = ingest_simple(master, data, label)
        audit.append({"file": filename, "source": label, "status": "OK", "included": included, "excluded_non_california": excluded, "source_summary": source_summary(data)})

    people = []
    craft_counts = defaultdict(int)
    source_overlap = defaultdict(int)
    identity_counts = defaultdict(int)
    for _, p in sorted(master.items()):
        identity_type = classify_identity(p["name"])
        out = {
            "name": p["name"],
            "identity_type": identity_type,
            "crafts": sorted(p["crafts"]),
            "source_count": len(p["sources"]),
            "sources": sorted(p["sources"]),
        }
        if p["years"]:
            out["years"] = sorted(p["years"])
        if p["public_handles"]:
            out["public_handles"] = sorted(p["public_handles"])
        if p["public_profiles"]:
            out["public_profiles"] = sorted(p["public_profiles"])
        if p["evidence"]:
            out["california_evidence"] = p["evidence"]
        people.append(out)
        identity_counts[identity_type] += 1
        source_overlap[str(len(p["sources"]))] += 1
        for c in p["crafts"]:
            craft_counts[c] += 1

    identity_total = len(people)
    out = {
        "schema_version": 3,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": "California only",
        "purpose": "Deduplicated California public paddler identity/source coverage index for SkyFinder research. Not an operational live-location feed.",
        "privacy": "Public race/event identity, craft, year, public handle/profile and source evidence only. No private contact data or exact live GPS.",
        "identity_note": "LIKELY_PERSON is a conservative name-shape classification, not verified identity or California residency. TEAM_OR_CREW is only applied to obvious group labels.",
        "summary": {
            "sources_configured": len(definitions),
            "sources_available": sum(1 for a in audit if a["status"] == "OK"),
            "unique_california_paddlers": identity_total,
            "unique_california_paddler_identities": identity_total,
            "identity_type_counts": dict(sorted(identity_counts.items())),
            "craft_counts": dict(sorted(craft_counts.items())),
            "source_overlap_counts": dict(sorted(source_overlap.items(), key=lambda kv: int(kv[0]))),
            "multi_source_confirmed": sum(1 for p in people if p["source_count"] >= 2),
            "public_handle_or_profile_count": sum(1 for p in people if p.get("public_handles") or p.get("public_profiles")),
        },
        "source_audit": audit,
        "paddlers": people,
    }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], indent=2))


if __name__ == "__main__":
    main()
