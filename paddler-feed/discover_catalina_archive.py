#!/usr/bin/env python3
"""Index the public Catalina Classic paddleboard results archive.

The archive spans modern HTML/PDF results plus historical scanned-image pages.
This crawler captures every accessible result document/page, extracts displayed
racer names where machine-readable text exists, and explicitly audits image-only
sources instead of pretending they were parsed.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

UA = "SkyFinder-Paddler-Prototype/1.0 (+public Catalina results research)"
HOSTS = {"catalinaclassicpaddleboardrace.com", "www.catalinaclassicpaddleboardrace.com", "catalinaclassicpaddleboardrace.org", "www.catalinaclassicpaddleboardrace.org"}
SEEDS = [
    "https://catalinaclassicpaddleboardrace.com/classic-results/",
    "https://catalinaclassicpaddleboardrace.com/2010s/",
    "https://catalinaclassicpaddleboardrace.com/results-2000-2009/",
    "https://catalinaclassicpaddleboardrace.com/early-races/1990s/",
    "https://catalinaclassicpaddleboardrace.com/early-races/1980s/",
    "https://catalinaclassicpaddleboardrace.com/early-races/1960s/",
    "https://catalinaclassicpaddleboardrace.com/early-races/1950s/",
    "https://catalinaclassicpaddleboardrace.com/2025-race-results/",
    "https://catalinaclassicpaddleboardrace.com/2024-race-results/",
    "https://catalinaclassicpaddleboardrace.com/2023-race-results/",
    "https://catalinaclassicpaddleboardrace.com/2022-race-results/",
    "https://catalinaclassicpaddleboardrace.com/2021-race-results/"
]


def fetch(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,image/*,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get_content_type(), r.read(), r.geturl()
    except Exception as exc:
        return int(getattr(exc, "code", 0) or 0), None, b"", url


def clean_html(raw: str) -> str:
    raw = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", raw or "", flags=re.I | re.S)
    return "\n".join(" ".join(unescape(re.sub(r"<[^>]+>", " ", x)).split()) for x in re.split(r"(?:</tr>|</p>|<br\s*/?>|</li>|</h\d>)", raw, flags=re.I) if " ".join(unescape(re.sub(r"<[^>]+>", " ", x)).split()))


def year_from(url: str, text: str = "") -> int | None:
    vals = re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", url + " " + (text[:1000] if text else ""))
    if vals:
        # URL year is normally most specific; last match handles page titles well.
        return int(vals[0])
    return None


def links_from_html(base: str, text: str) -> set[str]:
    out = set()
    for href in re.findall(r'href=["\']([^"\']+)', text or "", flags=re.I):
        href = unescape(href.strip())
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        u = urllib.parse.urljoin(base, href)
        p = urllib.parse.urlparse(u)
        if p.hostname and p.hostname.lower() in HOSTS:
            out.add(u.split("#")[0])
        elif p.path.lower().endswith(".pdf"):
            out.add(u.split("#")[0])
    for src in re.findall(r'(?:src|href)=["\']([^"\']+\.(?:jpg|jpeg|png|pdf)(?:\?[^"\']*)?)["\']', text or "", flags=re.I):
        out.add(urllib.parse.urljoin(base, unescape(src)).split("#")[0])
    return out


def likely_result_link(url: str) -> bool:
    low = url.lower()
    return any(k in low for k in ("result", "2010s", "2000", "1990", "1980", "1960", "1950")) or re.search(r"/(?:19[5-9]\d|20[0-2]\d)[^/]*[/._-]", low) is not None


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def candidate_names(text: str) -> list[str]:
    """Conservative display-name extraction from result text.

    We intentionally prefer undercounting to fabricating identities from headers,
    sponsors or addresses. Most Catalina tables use place/name/time or name/time.
    """
    bad = {
        "catalina classic", "paddleboard race", "overall results", "race results",
        "unlimited", "stock", "women", "men", "place", "time", "finish", "division",
        "manhattan beach", "catalina island", "board of directors", "classic records"
    }
    out = []
    seen = set()
    for line in (text or "").splitlines():
        s = " ".join(line.split()).strip()
        if not s or len(s) > 180:
            continue
        # Strip leading place/bib and trailing time/year/age columns.
        s2 = re.sub(r"^\s*(?:\d{1,3}|DNF|DQ)\s+[.#-]?\s*", "", s, flags=re.I)
        s2 = re.sub(r"\s+(?:\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?|\d{1,3}\.?\d*|M|F|Male|Female)\s*$", "", s2, flags=re.I)
        # Search one normal two-to-four-token human name near the front.
        m = re.match(r"^([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3})(?:\s|$)", s2)
        if not m:
            continue
        name = m.group(1).strip()
        n = re.sub(r"[^a-z]+", " ", name.lower()).strip()
        if n in bad or any(b in n for b in bad) or len(name) < 5:
            continue
        if n not in seen:
            seen.add(n)
            out.append(name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=0.03)
    ap.add_argument("--max-docs", type=int, default=300)
    args = ap.parse_args()

    queue = deque(SEEDS)
    queued = set(SEEDS)
    visited = set()
    docs = []
    identities = defaultdict(lambda: {"name": None, "years": set(), "sources": set()})

    while queue and len(visited) < args.max_docs:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        st, ctype, data, final_url = fetch(url, args.timeout)
        entry = {"url": url, "final_url": final_url, "http_status": st, "content_type": ctype}
        text = ""
        mode = None
        year = year_from(url)

        if st == 200 and data:
            if ctype == "text/html" or url.lower().split("?")[0].endswith(("/", ".html", ".htm")):
                html_text = data.decode("utf-8", "replace")
                text = clean_html(html_text)
                mode = "html-text"
                discovered = links_from_html(final_url, html_text)
                for u in discovered:
                    if u not in queued and u not in visited and likely_result_link(u):
                        queued.add(u); queue.append(u)
            elif ctype == "application/pdf" or url.lower().split("?")[0].endswith(".pdf"):
                text = pdf_text(data)
                mode = "pdf-text" if text.strip() else "pdf-image-or-unreadable"
            elif (ctype or "").startswith("image/") or url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                mode = "image-only-unparsed"

        if year is None:
            year = year_from(final_url, text)
        names = candidate_names(text) if mode in {"html-text", "pdf-text"} else []
        entry.update({"year": year, "parse_mode": mode, "machine_text_chars": len(text), "candidate_names": len(names)})
        docs.append(entry)
        for name in names:
            key = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            identities[key]["name"] = identities[key]["name"] or name
            if year: identities[key]["years"].add(year)
            identities[key]["sources"].add(url)
        if args.sleep: time.sleep(args.sleep)

    people = []
    for _, v in sorted(identities.items()):
        people.append({"name": v["name"], "years": sorted(v["years"]), "source_count": len(v["sources"])})
    modes = defaultdict(int)
    years = defaultdict(int)
    for d in docs:
        modes[d.get("parse_mode") or "unparsed/error"] += 1
        if d.get("year"): years[str(d["year"])] += 1

    out = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "purpose": "Public Catalina Classic historical result coverage index; not a live-location feed.",
        "privacy": "Only public race-result identities/year/source metadata. Image-only historical documents are audited but not OCR'd or guessed.",
        "summary": {
            "documents_checked": len(docs),
            "documents_http_200": sum(1 for d in docs if d["http_status"] == 200),
            "unique_candidate_paddlers": len(people),
            "parse_modes": dict(sorted(modes.items())),
            "years_seen": dict(sorted(years.items())),
            "unparsed_or_image_docs": sum(1 for d in docs if d.get("parse_mode") in {None, "image-only-unparsed", "pdf-image-or-unreadable"})
        },
        "documents": docs,
        "paddlers": people
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False); f.write("\n")
    print(json.dumps(out["summary"], indent=2))


if __name__ == "__main__":
    main()
