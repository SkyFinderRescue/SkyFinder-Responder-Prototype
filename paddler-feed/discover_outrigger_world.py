#!/usr/bin/env python3
"""Index public Southern California paddlers from outrigger.world race results.

Only public result identity/craft/team/source metadata is stored. No contact data
or exact live location is collected.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

UA = "SkyFinder-Paddler-Prototype/1.0 (+public race-result coverage research)"
BASE = "https://outrigger.world"


def fetch(url: str, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception as exc:
        return int(getattr(exc, "code", 0) or 0), ""


def clean(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def race_links(text: str) -> set[str]:
    links = set()
    for href in re.findall(r'href=["\']([^"\']+)', text or "", flags=re.I):
        if re.match(r"^/race-results/\d{4}/southern-california/", href, re.I):
            links.add(href.split("?")[0])
    return links


def title_of(text: str, path: str) -> str:
    m = re.search(r"<title>(.*?)</title>", text or "", re.I | re.S)
    if m:
        value = clean(m.group(1)).replace(" - Race Results", "").strip()
        if value:
            return value
    return path.rsplit("/", 1)[-1]


def parse_rows(text: str, race_path: str) -> list[dict]:
    records = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text or "", flags=re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)
        if len(cells) < 8:
            continue
        place = clean(cells[0])
        if not re.match(r"^\d+$", place):
            continue
        time_value = clean(cells[1])
        team = clean(cells[3]) or None
        gender = clean(cells[4]) or None
        craft = clean(cells[5]) or None
        division = clean(cells[6]) or None
        bib = clean(cells[7]) or None
        paddlers = re.findall(r'<a[^>]+href=["\'](/paddlers/[^"\']+)["\'][^>]*>(.*?)</a>', cells[2], flags=re.I | re.S)
        if not paddlers:
            name = clean(cells[2])
            if name:
                paddlers = [(None, name)]
        for href, label in paddlers:
            name = clean(label)
            if not name:
                continue
            records.append({
                "name": name,
                "public_profile_url": BASE + href if href else None,
                "place": int(place),
                "time": time_value or None,
                "team": team,
                "gender": gender,
                "craft": craft,
                "division": division,
                "bib": bib,
                "race_path": race_path,
                "source_url": BASE + race_path,
            })
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=0.03)
    args = ap.parse_args()

    listing_url = BASE + "/race-results?location=Southern+California"
    status, listing = fetch(listing_url, args.timeout)
    paths = race_links(listing) if status == 200 else set()
    # Each race landing page may expose sub-races such as relay/iron/baby.
    queue = sorted(paths)
    fetched = set()
    audits = []
    appearances = []
    while queue:
        path = queue.pop(0)
        if path in fetched:
            continue
        fetched.add(path)
        st, text = fetch(BASE + path, args.timeout)
        if st == 200:
            for extra in sorted(race_links(text)):
                if extra not in fetched and extra not in queue:
                    queue.append(extra)
            rows = parse_rows(text, path)
        else:
            rows = []
        appearances.extend(rows)
        audits.append({
            "path": path,
            "title": title_of(text, path),
            "http_status": st,
            "paddler_rows": len(rows),
        })
        if args.sleep:
            time.sleep(args.sleep)

    # De-duplicate a paddler within a result row/sub-race while preserving appearances.
    seen = set()
    dedup = []
    for r in appearances:
        key = (norm(r["name"]), r["race_path"], r.get("bib"), r.get("craft"), r.get("place"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    people = {}
    for r in dedup:
        k = norm(r["name"])
        p = people.setdefault(k, {"name": r["name"], "crafts": set(), "races": set(), "profiles": set()})
        if r.get("craft"):
            p["crafts"].add(r["craft"])
        p["races"].add(r["race_path"])
        if r.get("public_profile_url"):
            p["profiles"].add(r["public_profile_url"])

    person_list = []
    craft_counts = defaultdict(int)
    for _, p in sorted(people.items()):
        item = {"name": p["name"], "crafts": sorted(p["crafts"]), "race_count": len(p["races"])}
        if p["profiles"]:
            item["public_profile_urls"] = sorted(p["profiles"])
        person_list.append(item)
        for c in item["crafts"]:
            craft_counts[c] += 1

    out = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "purpose": "Public outrigger.world Southern California paddler result index; not a live-location feed.",
        "privacy": "Public race identity/craft/team/profile metadata only. No private contact data or live GPS.",
        "summary": {
            "listing_http_status": status,
            "race_pages_discovered": len(fetched),
            "race_pages_with_paddlers": sum(1 for a in audits if a["paddler_rows"] > 0),
            "paddler_event_records": len(dedup),
            "unique_paddlers": len(person_list),
            "craft_counts": dict(sorted(craft_counts.items())),
        },
        "races": audits,
        "paddlers": person_list,
        "appearances": dedup,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(json.dumps(out["summary"], indent=2))


if __name__ == "__main__":
    main()
