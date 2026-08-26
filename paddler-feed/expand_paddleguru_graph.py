#!/usr/bin/env python3
"""Expand public PaddleGuru paddle-racer coverage by crawling athlete/event links.

This is a public identity/event discovery index only. It does not collect private
contact data and it does not republish exact live GPS positions.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from discover_public_sources import extract_paddleguru_embedded, fetch, norm

BASE = "https://paddleguru.com"
CRAFT_FILTER = [
    "sup", "stand up paddle", "standup paddle", "prone", "paddleboard",
    "paddle board", "surfski", "surf ski", "oc-1", "oc1", "outrigger", "kayak"
]

# PaddleGuru athlete histories are largely rendered from embedded application data,
# not ordinary anchor tags. Support both forms so we can discover the full public
# California event graph without storing any embedded private registration fields.
EVENT_LINK_RE = re.compile(
    r'href=["\'](?:https?://(?:www\.)?paddleguru\.com)?/races/([^/"\'?#]+)',
    re.I,
)
EMBEDDED_EVENT_RE = re.compile(
    r'https?://(?:www\.)?paddleguru\.com/races/([^/"\'?#\\\s]+)',
    re.I,
)
RELATIVE_EMBEDDED_RE = re.compile(
    r'(?:[:=]\s*["\']|["\'])/races/([^/"\'?#\\\s]+)',
    re.I,
)


def california_page(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(r"\bCalifornia\b", text, re.I)
        or re.search(r",\s*CA(?:\s+\d{5}(?:-\d{4})?)?(?:\s*,|\s+USA\b|\s+United States\b|\s*<)", text)
    )


def display_title(text: str, slug: str) -> str:
    for tag in ("h4", "h3", "h2"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text or "", re.I | re.S)
        if m:
            raw = re.sub(r"<[^>]+>", " ", m.group(1))
            value = " ".join(html.unescape(raw).split())
            if value and value.lower() not in {"results", "startlist", "general info", "contact race"}:
                return value[:180]
    return slug


def event_slugs_from_text(text: str) -> set[str]:
    text = text or ""
    found = set(EVENT_LINK_RE.findall(text))
    found.update(EMBEDDED_EVENT_RE.findall(text))
    found.update(RELATIVE_EMBEDDED_RE.findall(text))
    cleaned = set()
    for slug in found:
        slug = html.unescape(slug).strip().strip("\\")
        if slug and slug.lower() not in {"past", "upcoming", "results", "startlist"}:
            cleaned.add(slug)
    return cleaned


def discover_events_for_handle(handle: str, timeout: int) -> tuple[set[str], list[dict]]:
    slugs: set[str] = set()
    audit = []
    for section in ("past", "upcoming"):
        url = f"{BASE}/athletes/{handle}/races/{section}"
        status, text = fetch(url, timeout)
        found = event_slugs_from_text(text) if status == 200 else set()
        slugs.update(found)
        audit.append({
            "handle": handle,
            "section": section,
            "url": url,
            "http_status": status,
            "event_links": len(found),
        })
    return slugs, audit


def fetch_event_records(slug: str, timeout: int) -> tuple[list[dict], dict]:
    attempts = []
    all_records = []
    seen = set()
    page_text_for_meta = ""

    for suffix in ("results", "startlist", ""):
        url = f"{BASE}/races/{slug}" + (f"/{suffix}" if suffix else "")
        status, text = fetch(url, timeout)
        attempts.append({"url": url, "http_status": status, "bytes": len(text or "")})
        if status != 200 or not text:
            continue
        if not page_text_for_meta:
            page_text_for_meta = text
        source = {
            "provider": "PaddleGuru",
            "event": slug,
            "url": url,
            "region": None,
            "california": california_page(text),
            "craft_filter": CRAFT_FILTER,
        }
        records = extract_paddleguru_embedded(source, text)
        for rec in records:
            key = (norm(rec.get("name", "")), rec.get("number"), rec.get("craft"))
            if key in seen:
                continue
            seen.add(key)
            all_records.append(rec)
        if suffix == "results" and all_records:
            break
        if suffix == "startlist" and all_records:
            break

    california = any(r.get("california") for r in all_records) or california_page(page_text_for_meta)
    for rec in all_records:
        rec["california"] = bool(california)

    audit = {
        "slug": slug,
        "title": display_title(page_text_for_meta, slug),
        "california": bool(california),
        "paddler_records": len(all_records),
        "attempts": attempts,
    }
    return all_records, audit


def merge_athletes(records: list[dict]):
    athletes = {}
    for rec in records:
        name = (rec.get("name") or "").strip()
        key = norm(name)
        if not key:
            continue
        item = athletes.setdefault(key, {
            "name": name,
            "crafts": set(),
            "public_handles": set(),
            "events": set(),
            "california_events": set(),
        })
        if rec.get("craft"):
            item["crafts"].add(rec["craft"])
        if rec.get("public_handle"):
            item["public_handles"].add(rec["public_handle"])
        if rec.get("event"):
            item["events"].add(rec["event"])
            if rec.get("california"):
                item["california_events"].add(rec["event"])

    result = []
    for _, item in sorted(athletes.items()):
        out = {
            "name": item["name"],
            "crafts": sorted(item["crafts"]),
            "event_count": len(item["events"]),
            "california_event_count": len(item["california_events"]),
        }
        if item["public_handles"]:
            out["public_handles"] = sorted(item["public_handles"])
        result.append(out)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--prior-index")
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=0.05)
    ap.add_argument("--max-athlete-pages", type=int, default=250)
    ap.add_argument("--max-events", type=int, default=600)
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    seeds = json.load(open(args.seeds, encoding="utf-8"))
    queue = deque()
    queued = set()

    def enqueue(handle):
        handle = (handle or "").strip()
        if handle and handle not in queued:
            queued.add(handle)
            queue.append(handle)

    for handle in seeds.get("athlete_handles", []):
        enqueue(handle)

    if args.prior_index and Path(args.prior_index).exists():
        prior = json.load(open(args.prior_index, encoding="utf-8"))
        for person in prior.get("paddlers", []):
            for handle in person.get("public_handles", []):
                enqueue(handle)

    event_slugs = set(seeds.get("event_slugs", []))
    crawled_handles = set()
    event_audit = {}
    athlete_page_audit = []
    records = []
    record_seen = set()
    events_fetched = set()
    round_stats = []

    for round_no in range(1, args.rounds + 1):
        handles_before = len(crawled_handles)
        events_before = len(event_slugs)

        while queue and len(crawled_handles) < args.max_athlete_pages:
            handle = queue.popleft()
            if handle in crawled_handles:
                continue
            crawled_handles.add(handle)
            try:
                found, audit = discover_events_for_handle(handle, args.timeout)
                event_slugs.update(found)
                athlete_page_audit.extend(audit)
            except Exception as exc:
                athlete_page_audit.append({"handle": handle, "error": f"{type(exc).__name__}: {exc}"})
            if args.sleep:
                time.sleep(args.sleep)
            if round_no == 1 and len(crawled_handles) >= max(20, len(seeds.get("athlete_handles", []))):
                break

        new_event_slugs = [s for s in sorted(event_slugs) if s not in events_fetched]
        remaining = max(0, args.max_events - len(events_fetched))
        for slug in new_event_slugs[:remaining]:
            events_fetched.add(slug)
            try:
                event_records, audit = fetch_event_records(slug, args.timeout)
            except Exception as exc:
                event_records = []
                audit = {"slug": slug, "error": f"{type(exc).__name__}: {exc}", "paddler_records": 0}
            event_audit[slug] = audit
            for rec in event_records:
                key = (norm(rec.get("name", "")), rec.get("event"), rec.get("number"), rec.get("craft"))
                if key in record_seen:
                    continue
                record_seen.add(key)
                records.append(rec)
                if rec.get("public_handle"):
                    enqueue(rec["public_handle"])
            if args.sleep:
                time.sleep(args.sleep)

        round_stats.append({
            "round": round_no,
            "handles_crawled_total": len(crawled_handles),
            "handles_added_this_round": len(crawled_handles) - handles_before,
            "events_known_total": len(event_slugs),
            "events_added_this_round": len(event_slugs) - events_before,
            "events_fetched_total": len(events_fetched),
            "paddler_event_records_total": len(records),
            "queued_handles_remaining": len(queue),
        })

        if len(crawled_handles) == handles_before and len(event_slugs) == events_before and not new_event_slugs:
            break

    athletes = merge_athletes(records)
    ca_athletes = [a for a in athletes if a["california_event_count"] > 0]
    craft_counts = defaultdict(int)
    ca_craft_counts = defaultdict(int)
    for person in athletes:
        for craft in person["crafts"]:
            craft_counts[craft] += 1
            if person["california_event_count"] > 0:
                ca_craft_counts[craft] += 1

    successful_events = [a for a in event_audit.values() if a.get("paddler_records", 0) > 0]
    ca_successful_events = [a for a in successful_events if a.get("california")]

    out = {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "purpose": "Broad public PaddleGuru paddle-racer graph discovery for SkyFinder California coverage research; not a live-location feed.",
        "privacy": "Public athlete names, public PaddleGuru handles, craft categories, event slugs and source audit only. No private contact data or exact live GPS.",
        "summary": {
            "athlete_history_handles_crawled": len(crawled_handles),
            "event_slugs_discovered": len(event_slugs),
            "events_fetched": len(events_fetched),
            "events_with_paddler_records": len(successful_events),
            "california_events_with_paddler_records": len(ca_successful_events),
            "paddler_event_records": len(records),
            "unique_paddlers": len(athletes),
            "unique_paddlers_with_california_event": len(ca_athletes),
            "craft_counts": dict(sorted(craft_counts.items())),
            "california_craft_counts": dict(sorted(ca_craft_counts.items())),
        },
        "rounds": round_stats,
        "athletes": athletes,
        "events": sorted(event_audit.values(), key=lambda x: x.get("slug", "")),
        "athlete_page_audit": athlete_page_audit,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(json.dumps(out["summary"], indent=2))
    print(json.dumps({"rounds": round_stats}, indent=2))


if __name__ == "__main__":
    main()
