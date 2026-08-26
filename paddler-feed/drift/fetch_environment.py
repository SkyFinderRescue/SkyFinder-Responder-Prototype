#!/usr/bin/env python3
"""Fetch public SAR-relevant environmental data for the maritime drift prototype.

Primary sources:
- NOAA/IOOS HF Radar West Coast near-real-time 2 km surface-current product.
- NOAA NDBC real-time standard meteorological observations for wind/waves.

The output records source age and quality. Stale data are never silently treated
as current.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "SkyFinder-Maritime-Drift-Prototype/1.0 (+public NOAA/IOOS SAR research)"
HFR_DATASET = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ucsdHfrW2.csv"
HFR_INFO = "https://coastwatch.pfeg.noaa.gov/erddap/info/ucsdHfrW2/index.html"
NDBC_REALTIME = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"

STATIONS = {
    "46053": {"name": "EAST SANTA BARBARA", "lat": 34.246, "lon": -119.842},
    "46054": {"name": "WEST SANTA BARBARA", "lat": 34.274, "lon": -120.459},
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt: datetime | None):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if dt else None


def fetch_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def age_hours(dt: datetime | None) -> float | None:
    if not dt:
        return None
    return max(0.0, (now_utc() - dt).total_seconds() / 3600.0)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except Exception:
        return None


def hfr_query_url(lat: float, lon: float) -> str:
    subset = f"[(last)][({lat:.5f})][({lon:.5f})]"
    variables = ["water_u", "water_v", "number_of_sites", "number_of_radials", "hdop"]
    return HFR_DATASET + "?" + ",".join(v + subset for v in variables)


def fetch_hfr(lat: float, lon: float, timeout: int) -> dict:
    url = hfr_query_url(lat, lon)
    base = {
        "provider": "NOAA/IOOS HF Radar Network via NOAA CoastWatch ERDDAP",
        "dataset": "ucsdHfrW2 — US West Coast hourly 2 km near-real-time surface currents",
        "query_url": url,
        "info_url": HFR_INFO,
        "usable": False,
    }
    try:
        text = fetch_text(url, timeout)
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return {**base, "quality": "NO_DATA", "error": "HF-radar query returned no rows."}
        row = rows[0]
        t = parse_iso(row.get("time"))
        u = float(row["water_u"])
        v = float(row["water_v"])
        if not (math.isfinite(u) and math.isfinite(v)):
            raise ValueError("non-finite current vector")
        speed_mps = math.hypot(u, v)
        bearing = (math.degrees(math.atan2(u, v)) + 360.0) % 360.0
        age = age_hours(t)
        # Hourly near-real-time product: >6h is not accepted as current for this prototype.
        usable = age is not None and age <= 6.0
        return {
            **base,
            "usable": usable,
            "quality": "CURRENT" if usable else "STALE",
            "observation_time_utc": iso(t),
            "age_hours": age,
            "grid_lat": float(row.get("latitude") or lat),
            "grid_lon": float(row.get("longitude") or lon),
            "u_mps": u,
            "v_mps": v,
            "speed_kts": speed_mps * 1.9438444924406048,
            "toward_deg_true": bearing,
            "number_of_sites": int(float(row["number_of_sites"])) if row.get("number_of_sites") not in (None, "", "NaN") else None,
            "number_of_radials": int(float(row["number_of_radials"])) if row.get("number_of_radials") not in (None, "", "NaN") else None,
            "hdop": float(row["hdop"]) if row.get("hdop") not in (None, "", "NaN") else None,
        }
    except urllib.error.HTTPError as exc:
        return {**base, "quality": "HTTP_ERROR", "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {**base, "quality": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def haversine_nm(lat1, lon1, lat2, lon2):
    r_nm = 3440.065
    a1, a2 = math.radians(lat1), math.radians(lat2)
    da = math.radians(lat2 - lat1)
    do = math.radians(lon2 - lon1)
    a = math.sin(da / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(do / 2) ** 2
    return 2 * r_nm * math.asin(math.sqrt(a))


def nearest_ndbc(lat: float, lon: float) -> tuple[str, dict]:
    return min(STATIONS.items(), key=lambda kv: haversine_nm(lat, lon, kv[1]["lat"], kv[1]["lon"]))


def parse_ndbc_datetime(row: dict) -> datetime | None:
    try:
        year = int(row["YY"])
        if year < 100:
            year += 2000
        return datetime(year, int(row["MM"]), int(row["DD"]), int(row["hh"]), int(row["mm"]), tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_ndbc(lat: float, lon: float, timeout: int) -> dict:
    station, meta = nearest_ndbc(lat, lon)
    url = NDBC_REALTIME.format(station=station)
    base = {
        "provider": "NOAA National Data Buoy Center",
        "station": station,
        "station_name": meta["name"],
        "station_lat": meta["lat"],
        "station_lon": meta["lon"],
        "distance_from_query_nm": haversine_nm(lat, lon, meta["lat"], meta["lon"]),
        "query_url": url,
        "usable": False,
    }
    try:
        text = fetch_text(url, timeout)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        header = None
        values = None
        for ln in lines:
            if ln.startswith("#YY"):
                header = ln.lstrip("#").split()
                continue
            if ln.startswith("#"):
                continue
            if header:
                values = ln.split()
                break
        if not header or not values:
            return {**base, "quality": "NO_DATA", "error": "NDBC real-time file had no parsable observation."}
        row = dict(zip(header, values))
        t = parse_ndbc_datetime(row)
        age = age_hours(t)

        def val(name):
            x = row.get(name)
            if x in (None, "", "MM"):
                return None
            try:
                y = float(x)
                return y if math.isfinite(y) else None
            except Exception:
                return None

        wind_dir = val("WDIR")
        wind_mps = val("WSPD")
        wave_m = val("WVHT")
        dpd = val("DPD")
        apd = val("APD")
        mwd = val("MWD")
        usable = age is not None and age <= 3.0 and wind_dir is not None and wind_mps is not None
        return {
            **base,
            "usable": usable,
            "quality": "CURRENT" if usable else "STALE_OR_INCOMPLETE",
            "observation_time_utc": iso(t),
            "age_hours": age,
            "wind_from_deg_true": wind_dir,
            "wind_speed_mps": wind_mps,
            "wind_speed_kts": wind_mps * 1.9438444924406048 if wind_mps is not None else None,
            "wind_speed_mph": wind_mps * 2.2369362920544 if wind_mps is not None else None,
            "wave_height_ft": wave_m * 3.2808398950131 if wave_m is not None else None,
            "dominant_period_sec": dpd,
            "average_period_sec": apd,
            "mean_wave_direction_deg_true": mwd,
        }
    except urllib.error.HTTPError as exc:
        return {**base, "quality": "HTTP_ERROR", "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {**base, "quality": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=25)
    args = ap.parse_args()

    if not (30.0 <= args.lat <= 50.5 and -130.5 <= args.lon <= -115.0):
        raise SystemExit("This v1 environmental adapter is intentionally limited to the U.S. West Coast HF-radar domain.")

    hfr = fetch_hfr(args.lat, args.lon, args.timeout)
    ndbc = fetch_ndbc(args.lat, args.lon, args.timeout)
    out = {
        "schema_version": 1,
        "generated_at_utc": iso(now_utc()),
        "operational_use": False,
        "scope": "Santa Barbara / U.S. West Coast research prototype",
        "query_point": {"lat": args.lat, "lon": args.lon},
        "surface_current": hfr,
        "wind_wave": ndbc,
        "sources": {
            "hf_radar": {
                "name": "NOAA/IOOS HF Radar US West Coast near-real-time 2 km",
                "dataset": "ucsdHfrW2",
                "official_upstream": "NOAA IOOS HF Radar Network / NDBC THREDDS",
            },
            "wind_wave": {
                "name": "NOAA NDBC real-time standard meteorological data",
                "station": ndbc.get("station"),
            },
        },
        "warning": "Environmental source ages must be checked. This prototype is not Coast Guard SAROPS and is not approved for operational SAR decisions.",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "hfr_quality": hfr.get("quality"),
        "hfr_usable": hfr.get("usable"),
        "hfr_age_hours": hfr.get("age_hours"),
        "ndbc_station": ndbc.get("station"),
        "ndbc_quality": ndbc.get("quality"),
        "ndbc_usable": ndbc.get("usable"),
        "ndbc_age_hours": ndbc.get("age_hours"),
    }, indent=2))


if __name__ == "__main__":
    main()
