#!/usr/bin/env python3
"""Build a prioritized, privacy-safe queue for public/permissioned tracker matching.

This does not infer or scrape live locations. It only prioritizes California
paddler identities already in the master index for later verification against
public Garmin MapShare or organizer-authorized tracker references.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PRIORITY_CRAFT = {
    "SUP": 8,
    "PRONE/PADDLEBOARD": 8,
    "KAYAK": 6,
    "SURFSKI": 4,
    "OUTRIGGER": 3,
}


def candidate_score(p: dict) -> int:
    score = 0
    crafts = p.get("crafts") or []
    score += max((PRIORITY_CRAFT.get(c, 0) for c in crafts), default=0)
    score += min(12, int(p.get("source_count") or 0) * 3)
    if p.get("public_profiles"):
        score += 12
    if p.get("public_handles"):
        score += 10
    years = [int(y) for y in (p.get("years") or []) if str(y).isdigit()]
    if years:
        newest = max(years)
        if newest >= 2025:
            score += 6
        elif newest >= 2022:
            score += 4
        elif newest >= 2018:
            score += 2
    return score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="paddler-feed/data/california-paddlers-master.json")
    ap.add_argument("--output", default="paddler-feed/data/tracker-match-candidates.json")
    args = ap.parse_args()

    master = json.loads(Path(args.master).read_text(encoding="utf-8"))
    candidates = []
    skipped_team = skipped_unknown = skipped_no_public_reference = 0
    for p in master.get("paddlers", []):
        identity_type = p.get("identity_type", "UNKNOWN")
        if identity_type == "TEAM_OR_CREW":
            skipped_team += 1
            continue
        if identity_type != "LIKELY_PERSON":
            skipped_unknown += 1
            continue
        crafts = [c for c in (p.get("crafts") or []) if c in PRIORITY_CRAFT]
        if not crafts:
            continue
        handles = p.get("public_handles") or []
        profiles = p.get("public_profiles") or []
        if not handles and not profiles:
            skipped_no_public_reference += 1
            continue
        candidates.append({
            "name": p.get("name"),
            "crafts": crafts,
            "source_count": p.get("source_count", 0),
            "sources": p.get("sources") or [],
            "years": p.get("years") or [],
            "public_handles": handles,
            "public_profiles": profiles,
            "priority_score": candidate_score(p),
            "tracker_match_status": "UNMATCHED_CANDIDATE",
        })

    candidates.sort(key=lambda p: (-p["priority_score"], p["name"].lower()))
    output = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": "California public paddler identity research",
        "purpose": "Prioritized queue for later verification of reusable public or participant-authorized trackers.",
        "privacy": "No live GPS, private contact information, passwords or protected tracker data. A public handle/profile is not itself a verified tracker match.",
        "verification_rule": "A tracker becomes VERIFIED only after independent evidence ties the tracker identifier to the paddler and the feed is public or participant/organizer authorized.",
        "summary": {
            "master_identity_count": len(master.get("paddlers", [])),
            "candidates_with_public_reference": len(candidates),
            "skipped_obvious_team_or_crew": skipped_team,
            "skipped_unknown_identity_type": skipped_unknown,
            "likely_people_without_public_handle_or_profile": skipped_no_public_reference,
        },
        "candidates": candidates,
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
