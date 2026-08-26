#!/usr/bin/env python3
"""Discover public California paddling identities from Webscorer results.

Only public race-result fields are indexed: displayed name, craft/category, race,
location/sport metadata and source URL. No contact information is collected.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
import urllib.request

UA = "SkyFinder-Paddler-Prototype/1.0 (+public result coverage research)"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "tr":
            self._row = []
        elif t in ("td", "th") and self._row is not None:
            self._cell = t
            self._buf = []

    def handle_data(self, data):
        if self._cell is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join(" ".join(self._buf).split()))
            self._cell = None
            self._buf = []
        elif t == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def fetch(url: str, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        return int(code), ""


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def classify(text: str) -> str | None:
    t = norm(text)
    if re.search(r"\bsup\b|stand up paddle|standup paddle", t):
        return "SUP"
    if "prone" in t or "paddleboard" in t or "paddle board" in t or "waterman" in t or "waterwoman" in t:
        return "PRONE/PADDLEBOARD"
    if "surfski" in t or "surf ski" in t or re.search(r"\bski\b", t):
        return "SURFSKI"
    if re.search(r"\boc\s*[12346]\b|outrigger|\bv1\b|\bv 1\b", t):
        return "OUTRIGGER"
    if re.search(r"\bk1\b|\bkayak\b", t):
        return "KAYAK"
    return None


def strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").split())


def meta(text: str, race_id: int) -> dict:
    title = None
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.I | re.S)
    if m:
        title = strip_tags(m.group(1))
    if not title:
        mt = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        title = strip_tags(mt.group(1)) if mt else f"Webscorer race {race_id}"

    plain = strip_tags(text)
    sport = None
    ms = re.search(r"Sport:\s*([^\n]{0,80}?)(?:Location:|Start type:|Racers:|$)", plain, re.I)
    if ms:
        sport = " ".join(ms.group(1).split())
    location = None
    ml = re.search(r"Location:\s*([^\n]{0,120}?)(?:View on map|Start type:|Racers:|$)", plain, re.I)
    if ml:
        location = " ".join(ml.group(1).split())
    california = bool(re.search(r"\bCA\b.*?United States", plain, re.I) or re.search(r"\bCalifornia\b", plain, re.I))
    return {"race_id": race_id, "title": title, "sport": sport, "location": location, "california": california}


def parse_result_rows(text: str, race_meta: dict) -> list[dict]:
    parser = TableParser()
    parser.feed(text)
    results = []
    seen = set()
    event_craft = classify(race_meta.get("sport") or "")

    for row in parser.rows:
        if len(row) < 4:
            continue
        # Webscorer result rows begin with place then bib then displayed name.
        place = row[0].strip()
        if not (re.match(r"^\d+$", place) or place in {"-", "--"}):
            continue
        bib = row[1].strip()
        name = row[2].strip()
        if not name or norm(name) in {"name", "name affiliation"}:
            continue
        category = row[3].strip()
        craft = classify(category) or event_craft
        if not craft:
            continue
        # Reject obvious category-summary rows rather than individual racer rows.
        if norm(name) in {"overall", "female", "male", "winner"}:
            continue
        key = (norm(name), norm(category), bib)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "name": name,
            "bib": bib or None,
            "category": category or None,
            "craft": craft,
            "place": place,
        })
    return results


def organizer_race_ids(text: str) -> set[int]:
    ids = set()
    for pat in [r"raceid=(\d+)", r"/race/(\d+)"]:
        ids.update(int(x) for x in re.findall(pat, text or "", flags=re.I))
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=0.03)
    ap.add_argument("--max-races", type=int, default=400)
    args = ap.parse_args()

    cfg = json.load(open(args.sources, encoding="utf-8"))
    race_ids = set(int(x) for x in cfg.get("direct_race_ids", []))
    organizer_audit = []

    for organizer in cfg.get("organizers", []):
        status, text = fetch(organizer["url"], args.timeout)
        found = organizer_race_ids(text) if status == 200 else set()
        race_ids.update(found)
        organizer_audit.append({
            "name": organizer["name"],
            "url": organizer["url"],
            "http_status": status,
            "race_ids_discovered": len(found),
        })
        if args.sleep:
            time.sleep(args.sleep)

    race_audit = []
    appearances = []
    for race_id in sorted(race_ids)[:args.max_races]:
        url = f"https://www.webscorer.com/racealldetails?raceid={race_id}"
        status, text = fetch(url, args.timeout)
        rm = meta(text, race_id) if status == 200 else {"race_id": race_id, "title": f"Webscorer race {race_id}", "sport": None, "location": None, "california": False}
        rows = parse_result_rows(text, rm) if status == 200 else []
        # Sources are California-focused; if metadata extraction misses CA on an
        # organizer-derived race, public source lineage still remains in audit.
        race_audit.append({**rm, "url": url, "http_status": status, "paddler_rows": len(rows)})
        for r in rows:
            appearances.append({
                **r,
                "provider": "Webscorer",
                "race_id": race_id,
                "event": rm["title"],
                "location": rm.get("location"),
                "california": rm.get("california", False),
                "source_url": url,
            })
        if args.sleep:
            time.sleep(args.sleep)

    # Deduplicate same public result row; keep cross-race appearances.
    dedup = []
    seen = set()
    for r in appearances:
        key = (r["race_id"], norm(r["name"]), norm(r.get("category") or ""), r.get("bib"))
        if key not in seen:
            seen.add(key)
            dedup.append(r)

    people = {}
    for r in dedup:
        k = norm(r["name"])
        p = people.setdefault(k, {"name": r["name"], "crafts": set(), "race_ids": set(), "california_races": set()})
        p["crafts"].add(r["craft"])
        p["race_ids"].add(r["race_id"])
        if r.get("california"):
            p["california_races"].add(r["race_id"])

    person_list = []
    craft_counts = defaultdict(int)
    for _, p in sorted(people.items()):
        item = {
            "name": p["name"],
            "crafts": sorted(p["crafts"]),
            "race_count": len(p["race_ids"]),
            "california_race_count": len(p["california_races"]),
        }
        person_list.append(item)
        for c in item["crafts"]:
            craft_counts[c] += 1

    out = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "purpose": "Public Webscorer paddler result coverage index; not a live-location feed.",
        "privacy": "Public displayed race-result identity/category metadata only. No email, phone, address or private participant API data.",
        "summary": {
            "organizers_checked": len(organizer_audit),
            "race_ids_discovered": len(race_ids),
            "race_pages_fetched": len(race_audit),
            "races_with_paddler_rows": sum(1 for x in race_audit if x["paddler_rows"] > 0),
            "paddler_event_records": len(dedup),
            "unique_paddlers": len(person_list),
            "craft_counts": dict(sorted(craft_counts.items())),
        },
        "organizers": organizer_audit,
        "races": race_audit,
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
