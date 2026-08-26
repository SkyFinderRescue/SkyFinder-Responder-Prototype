#!/usr/bin/env python3
"""Discover publicly listed SUP/prone paddlers from event roster/result pages.

Coverage index only: public event identity/category metadata and public handles are
stored. Precise live GPS is handled separately by tracker ingestion and privacy
rules.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

UA = "SkyFinder-Paddler-Prototype/1.1 (+public event discovery; rescue research)"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self._cell_text = []
        self._links = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = tag
            self._cell_text = []
            self._links = []
        elif tag == "a" and self._cell is not None:
            href = dict(attrs).get("href")
            if href:
                self._links.append(href)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = " ".join(" ".join(self._cell_text).split())
            self._row.append({"text": text, "links": list(self._links)})
            self._cell = None
            self._cell_text = []
            self._links = []
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def fetch(url: str, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.getcode() or 200, raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def unescape_clj(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    return s.replace('\\"', '"').replace('\\\\', '\\').strip()


def classify_craft(text: str) -> str | None:
    t = norm(text)
    if re.search(r"\bsup\b|stand up paddle|standup paddle", t):
        return "SUP"
    if "prone" in t or "paddleboard" in t or "paddle board" in t:
        return "PRONE/PADDLEBOARD"
    if "surfski" in t or "surf ski" in t:
        return "SURFSKI"
    if re.search(r"\boc[- ]?1\b|outrigger", t):
        return "OUTRIGGER"
    if "kayak" in t:
        return "KAYAK"
    if "paddle" in t:
        return "PADDLE"
    return None


def filter_matches(category: str, filters) -> bool:
    n = norm(category)
    return any(norm(f) in n for f in filters)


def row_matches(row, filters) -> bool:
    return filter_matches(" | ".join(c["text"] for c in row), filters)


def absolute(base: str, href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    m = re.match(r"^(https?://[^/]+)", base)
    if not m:
        return href
    root = m.group(1)
    if href.startswith("/"):
        return root + href
    return base.rsplit("/", 1)[0] + "/" + href


def base_record(source):
    return {
        "provider": source["provider"],
        "event": source["event"],
        "region": source.get("region"),
        "california": bool(source.get("california")),
        "source_url": source["url"],
    }


def extract_paddleguru_embedded(source, text):
    """Parse PaddleGuru's server-rendered Clojure/EDN-like race data.

    PaddleGuru does not render result rows as HTML <tr>. The page contains public
    entries such as {:athletes (...), :racer-number ..., :division {:category ...}}.
    Parse only the fields needed for identity/category matching and discard
    internal user IDs.
    """
    records = []
    # Each race entry starts with :athletes, followed by pending-athletes,
    # racer-number and division/category. DOTALL is required because minified
    # pages can still contain incidental line breaks.
    entry_re = re.compile(
        r"\{:athletes\s+(?P<athletes>\(.*?\)|nil),\s*"
        r":pending-athletes\s+.*?,\s*"
        r":racer-number\s+(?P<number>\d+),\s*"
        r":division\s+\{:category\s+\{.*?:name\s+\"(?P<category>(?:\\.|[^\"])*)\"\}",
        re.S,
    )
    athlete_re = re.compile(
        r":full-name\s+\"(?P<name>(?:\\.|[^\"])*)\""
        r"(?:.*?:username\s+\"(?P<username>(?:\\.|[^\"])*)\")?",
        re.S,
    )

    for match in entry_re.finditer(text):
        category = unescape_clj(match.group("category"))
        if not filter_matches(category, source.get("craft_filter", [])):
            continue
        craft = classify_craft(category)
        if not craft:
            continue
        athlete_blob = match.group("athletes")
        if athlete_blob == "nil":
            continue

        # A relay/team entry can contain more than one public athlete. Preserve
        # each person as a separate discovery record tied to the same race number.
        found = list(athlete_re.finditer(athlete_blob))
        if not found:
            # Fallback for entries without username ordering/field.
            names = re.findall(r':full-name\s+\"((?:\\.|[^\"])*)\"', athlete_blob, flags=re.S)
            found_data = [(unescape_clj(n), None) for n in names]
        else:
            found_data = [(unescape_clj(m.group("name")), unescape_clj(m.group("username") or "")) for m in found]

        for name, username in found_data:
            if not name:
                continue
            rec = base_record(source)
            rec.update({
                "name": name,
                "number": match.group("number"),
                "category": category,
                "craft": craft,
            })
            if username:
                rec["public_handle"] = username
            records.append(rec)
    return records


def extract_table_record(source, row):
    provider = source["provider"]
    cells = [c["text"] for c in row]
    if not cells:
        return None
    record = base_record(source)

    # Legacy/table fallback for PaddleGuru pages that may still expose HTML rows.
    if provider.lower() == "paddleguru":
        if len(cells) >= 7 and re.match(r"^\d+$", cells[0]):
            name, number, category = cells[2], cells[3], cells[6]
        elif len(cells) >= 5:
            name, number, category = cells[0], cells[1], cells[4]
        else:
            return None
        if norm(name) in {"name", "overall"} or not name.strip():
            return None
        record.update({"name": name.strip(), "number": number.strip(), "category": category.strip()})

    # RaceOwl roster commonly exposes boat number, team/boat, racers, division.
    elif provider.lower() == "raceowl":
        if len(cells) < 4:
            return None
        number, team, racers = cells[0], cells[1], cells[2]
        category = next((c for c in cells[3:] if classify_craft(c) == "SUP"), cells[3])
        name = racers or team
        if not name or norm(name) in {"racers", "name"}:
            return None
        record.update({"name": name.strip(), "number": number.strip(), "team": team.strip(), "category": category.strip()})
    else:
        return None

    craft = classify_craft(record.get("category", "") + " " + " ".join(cells))
    if not craft:
        return None
    record["craft"] = craft

    links = []
    for cell in row:
        for href in cell.get("links", []):
            if "RaceSplits" in href or "/athletes/" in href or "/races/" in href:
                links.append(absolute(source["url"], href))
    if links:
        record["public_detail_url"] = links[0]
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    cfg = json.load(open(args.sources, encoding="utf-8"))
    records = []
    source_results = []

    for source in cfg.get("sources", []):
        status = None
        text = ""
        error = None
        try:
            status, text = fetch(source["url"], args.timeout)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        parsed = 0
        matched = 0
        parser_mode = None
        if status == 200 and text:
            if source["provider"].lower() == "paddleguru":
                pg_records = extract_paddleguru_embedded(source, text)
                if pg_records:
                    records.extend(pg_records)
                    matched += len(pg_records)
                    parsed += len(pg_records)
                    parser_mode = "paddleguru-embedded"

            # Table parser remains useful for RaceOwl and as a fallback.
            if source["provider"].lower() != "paddleguru" or matched == 0:
                parser = TableParser()
                try:
                    parser.feed(text)
                except Exception as exc:
                    error = f"HTML parse error: {exc}"
                for row in parser.rows:
                    parsed += 1
                    if not row_matches(row, source.get("craft_filter", [])):
                        continue
                    rec = extract_table_record(source, row)
                    if rec:
                        records.append(rec)
                        matched += 1
                if parser.rows:
                    parser_mode = parser_mode or "html-table"

        source_results.append({
            "provider": source["provider"],
            "event": source["event"],
            "url": source["url"],
            "region": source.get("region"),
            "california": bool(source.get("california")),
            "http_status": status,
            "parser_mode": parser_mode,
            "rows_parsed": parsed,
            "paddler_rows": matched,
            "error": error,
        })
        if args.sleep:
            time.sleep(args.sleep)

    # Remove exact duplicates from the same event while preserving appearances
    # across different events. Public handles improve later tracker matching.
    seen = set()
    deduped = []
    for rec in records:
        key = (norm(rec.get("name", "")), rec["provider"], rec["event"], norm(rec.get("number", "")), rec["craft"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rec)

    athletes = {}
    for rec in deduped:
        k = norm(rec["name"])
        if not k:
            continue
        a = athletes.setdefault(k, {
            "name": rec["name"],
            "crafts": set(),
            "public_handles": set(),
            "california_events": set(),
            "events": [],
        })
        a["crafts"].add(rec["craft"])
        if rec.get("public_handle"):
            a["public_handles"].add(rec["public_handle"])
        if rec.get("california"):
            a["california_events"].add(rec["event"])
        a["events"].append({
            "provider": rec["provider"],
            "event": rec["event"],
            "region": rec.get("region"),
            "california": rec.get("california", False),
            "number": rec.get("number"),
            "team": rec.get("team"),
            "category": rec.get("category"),
            "craft": rec["craft"],
            "source_url": rec["source_url"],
            "public_detail_url": rec.get("public_detail_url"),
        })

    athlete_list = []
    for _, a in sorted(athletes.items(), key=lambda kv: kv[0]):
        item = {
            "name": a["name"],
            "crafts": sorted(a["crafts"]),
            "california_event_count": len(a["california_events"]),
            "events": a["events"],
        }
        if a["public_handles"]:
            item["public_handles"] = sorted(a["public_handles"])
        athlete_list.append(item)

    craft_counts = defaultdict(int)
    for a in athlete_list:
        for craft in a["crafts"]:
            craft_counts[craft] += 1

    out = {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "purpose": "Public paddler discovery index for source coverage. Not an operational live-location feed.",
        "privacy": "Stores public event roster/result metadata, public handles and source links only. Exact live GPS remains in the separate tracker ingestion path with opt-in/privacy controls.",
        "summary": {
            "source_count": len(source_results),
            "sources_http_200": sum(1 for x in source_results if x["http_status"] == 200),
            "event_records": len(deduped),
            "unique_paddlers": len(athlete_list),
            "unique_paddlers_with_california_event": sum(1 for a in athlete_list if a["california_event_count"] > 0),
            "craft_counts": dict(sorted(craft_counts.items())),
        },
        "source_results": source_results,
        "paddlers": athlete_list,
        "tracker_ecosystems": cfg.get("tracker_ecosystems", []),
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(json.dumps(out["summary"], indent=2))
    failed = [s for s in source_results if s["http_status"] not in (200, 404)]
    if failed:
        print("Non-200 source warnings:", file=sys.stderr)
        for s in failed:
            print(f"- {s['event']}: HTTP {s['http_status']} {s['error'] or ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
