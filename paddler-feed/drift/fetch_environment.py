#!/usr/bin/env python3
"""Fetch public SAR-relevant environmental data for the maritime drift prototype.

Primary sources:
- NOAA/NDBC THREDDS US West Coast 2 km near-real-time HF-radar surface currents.
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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "SkyFinder-Maritime-Drift-Prototype/1.0 (+public NOAA/IOOS SAR research)"
HFR_NCSS = "https://dods.ndbc.noaa.gov/thredds/ncss/grid/hfradar_uswc_2km"
HFR_CATALOG = "https://dods.ndbc.noaa.gov/thredds/catalog/hfradar.html?dataset=hfradar_uswc_2km"
HFR_COASTWATCH_FALLBACK = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ucsdHfrW2.csv"
NDBC_REALTIME = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"

STATIONS = {
    "46053": {"name": "EAST SANTA BARBARA", "lat": 34.246, "lon": -119.842},
    "46054": {"name": "WEST SANTA BARBARA", "lat": 34.274, "lon": -120.459},
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if dt else None


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        return None


def age_hours(dt):
    return max(0.0, (now_utc() - dt).total_seconds() / 3600.0) if dt else None


def fetch_text(url, timeout=25, attempts=4):
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/csv,text/plain,*/*",
            "Connection": "close",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except Exception as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code != 429:
                raise
            if attempt < attempts:
                time.sleep(attempt * 1.5)
    raise last


def fnum(value):
    if value in (None, "", "NaN", "nan", "MM"):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def find_key(row, candidates):
    lower = {str(k).lower(): k for k in row}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    for k in row:
        lk = str(k).lower()
        if any(candidate.lower() in lk for candidate in candidates):
            return k
    return None


def ncss_hfr_url(lat, lon):
    params = [
        ("var", "u,v,number_of_sites,number_of_radials,hdop"),
        ("latitude", f"{lat:.5f}"),
        ("longitude", f"{lon:.5f}"),
        ("time", "present"),
        ("accept", "CSV"),
    ]
    return HFR_NCSS + "?" + urllib.parse.urlencode(params)


def parse_ncss_hfr(text, lat, lon):
    rows = list(csv.DictReader(io.StringIO(text)))
    for row in rows:
        tk = find_key(row, ["time"])
        uk = find_key(row, ["u", "surface_eastward_sea_water_velocity"])
        vk = find_key(row, ["v", "surface_northward_sea_water_velocity"])
        t = parse_iso(row.get(tk)) if tk else None
        u = fnum(row.get(uk)) if uk else None
        v = fnum(row.get(vk)) if vk else None
        if t is None or u is None or v is None:
            continue
        latk = find_key(row, ["latitude", "lat"])
        lonk = find_key(row, ["longitude", "lon"])
        nsk = find_key(row, ["number_of_sites", "number of contributing radars"])
        nrk = find_key(row, ["number_of_radials", "number of contributing radials"])
        hk = find_key(row, ["hdop", "horizontal dilution"])
        return {
            "time": t,
            "u": u,
            "v": v,
            "lat": fnum(row.get(latk)) if latk else lat,
            "lon": fnum(row.get(lonk)) if lonk else lon,
            "sites": fnum(row.get(nsk)) if nsk else None,
            "radials": fnum(row.get(nrk)) if nrk else None,
            "hdop": fnum(row.get(hk)) if hk else None,
        }
    raise ValueError(f"No numeric HF-radar row in NDBC NCSS response; columns={list(rows[0]) if rows else []}")


def coastwatch_hfr_url(lat, lon):
    subset = f"[(last)][({lat:.5f})][({lon:.5f})]"
    variables = ["water_u", "water_v", "number_of_sites", "number_of_radials", "hdop"]
    return HFR_COASTWATCH_FALLBACK + "?" + ",".join(v + subset for v in variables)


def parse_coastwatch_hfr(text, lat, lon):
    for row in csv.DictReader(io.StringIO(text)):
        t = parse_iso(row.get("time"))
        u, v = fnum(row.get("water_u")), fnum(row.get("water_v"))
        if t is None or u is None or v is None:
            continue
        return {
            "time": t, "u": u, "v": v,
            "lat": fnum(row.get("latitude")) or lat,
            "lon": fnum(row.get("longitude")) or lon,
            "sites": fnum(row.get("number_of_sites")),
            "radials": fnum(row.get("number_of_radials")),
            "hdop": fnum(row.get("hdop")),
        }
    raise ValueError("No numeric HF-radar row in CoastWatch response")


def fetch_hfr(lat, lon, timeout):
    attempts = [
        ("NOAA/NDBC THREDDS NCSS", ncss_hfr_url(lat, lon), parse_ncss_hfr),
        ("NOAA CoastWatch ERDDAP fallback", coastwatch_hfr_url(lat, lon), parse_coastwatch_hfr),
    ]
    errors = []
    for provider, url, parser in attempts:
        try:
            obs = parser(fetch_text(url, timeout), lat, lon)
            speed = math.hypot(obs["u"], obs["v"])
            bearing = (math.degrees(math.atan2(obs["u"], obs["v"])) + 360.0) % 360.0
            age = age_hours(obs["time"])
            usable = age is not None and age <= 6.0
            return {
                "provider": provider,
                "dataset": "US West Coast hourly 2 km near-real-time HF-radar surface currents",
                "query_url": url,
                "catalog_url": HFR_CATALOG,
                "usable": usable,
                "quality": "CURRENT" if usable else "STALE",
                "observation_time_utc": iso(obs["time"]),
                "age_hours": age,
                "grid_lat": obs["lat"],
                "grid_lon": obs["lon"],
                "u_mps": obs["u"],
                "v_mps": obs["v"],
                "speed_kts": speed * 1.9438444924406048,
                "toward_deg_true": bearing,
                "number_of_sites": int(obs["sites"]) if obs["sites"] is not None else None,
                "number_of_radials": int(obs["radials"]) if obs["radials"] is not None else None,
                "hdop": obs["hdop"],
            }
        except Exception as exc:
            errors.append(f"{provider}: {type(exc).__name__}: {exc}")
    return {
        "provider": "NOAA/IOOS HF Radar Network",
        "dataset": "US West Coast hourly 2 km near-real-time HF-radar surface currents",
        "catalog_url": HFR_CATALOG,
        "usable": False,
        "quality": "ERROR",
        "error": " | ".join(errors),
    }


def haversine_nm(lat1, lon1, lat2, lon2):
    r_nm = 3440.065
    a1, a2 = math.radians(lat1), math.radians(lat2)
    da, do = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(da/2)**2 + math.cos(a1)*math.cos(a2)*math.sin(do/2)**2
    return 2*r_nm*math.asin(math.sqrt(a))


def nearest_ndbc(lat, lon):
    return min(STATIONS.items(), key=lambda kv: haversine_nm(lat, lon, kv[1]["lat"], kv[1]["lon"]))


def ndbc_time(row):
    try:
        year = int(row["YY"]); year = year + 2000 if year < 100 else year
        return datetime(year, int(row["MM"]), int(row["DD"]), int(row["hh"]), int(row["mm"]), tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_ndbc(lat, lon, timeout):
    station, meta = nearest_ndbc(lat, lon)
    url = NDBC_REALTIME.format(station=station)
    base = {
        "provider": "NOAA National Data Buoy Center",
        "station": station, "station_name": meta["name"],
        "station_lat": meta["lat"], "station_lon": meta["lon"],
        "distance_from_query_nm": haversine_nm(lat, lon, meta["lat"], meta["lon"]),
        "query_url": url, "usable": False,
    }
    try:
        lines = [ln.strip() for ln in fetch_text(url, timeout).splitlines() if ln.strip()]
        header, rows = None, []
        for ln in lines:
            if ln.startswith("#YY"):
                header = ln.lstrip("#").split(); continue
            if ln.startswith("#"): continue
            if header:
                vals = ln.split()
                if len(vals) >= len(header): rows.append(dict(zip(header, vals)))
        wind = next((r for r in rows if fnum(r.get("WDIR")) is not None and fnum(r.get("WSPD")) is not None), None)
        wave = next((r for r in rows if fnum(r.get("WVHT")) is not None), None)
        if not wind:
            return {**base, "quality": "NO_WIND", "error": "No recent valid wind row."}
        wt, wavt = ndbc_time(wind), ndbc_time(wave) if wave else None
        wa, wavea = age_hours(wt), age_hours(wavt)
        wd, wm = fnum(wind.get("WDIR")), fnum(wind.get("WSPD"))
        wh = fnum(wave.get("WVHT")) if wave else None
        usable = wa is not None and wa <= 3.0 and wd is not None and wm is not None
        return {
            **base, "usable": usable, "quality": "CURRENT" if usable else "STALE_OR_INCOMPLETE",
            "observation_time_utc": iso(wt), "age_hours": wa,
            "wind_from_deg_true": wd, "wind_speed_mps": wm,
            "wind_speed_kts": wm*1.9438444924406048,
            "wind_speed_mph": wm*2.2369362920544,
            "wave_observation_time_utc": iso(wavt), "wave_age_hours": wavea,
            "wave_height_ft": wh*3.2808398950131 if wh is not None else None,
            "dominant_period_sec": fnum(wave.get("DPD")) if wave else None,
            "average_period_sec": fnum(wave.get("APD")) if wave else None,
            "mean_wave_direction_deg_true": fnum(wave.get("MWD")) if wave else None,
        }
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
        raise SystemExit("This v1 adapter is limited to the U.S. West Coast HF-radar domain.")

    hfr, ndbc = fetch_hfr(args.lat, args.lon, args.timeout), fetch_ndbc(args.lat, args.lon, args.timeout)
    out = {
        "schema_version": 1,
        "generated_at_utc": iso(now_utc()),
        "operational_use": False,
        "scope": "Santa Barbara / U.S. West Coast research prototype",
        "query_point": {"lat": args.lat, "lon": args.lon},
        "surface_current": hfr,
        "wind_wave": ndbc,
        "sources": {
            "hf_radar": {"name": "NOAA/IOOS HF Radar Network", "dataset": "NDBC THREDDS hfradar_uswc_2km"},
            "wind_wave": {"name": "NOAA NDBC real-time standard meteorological data", "station": ndbc.get("station")},
        },
        "warning": "Environmental source ages must be checked. This prototype is not Coast Guard SAROPS and is not approved for operational SAR decisions.",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({
        "hfr_provider": hfr.get("provider"), "hfr_quality": hfr.get("quality"), "hfr_usable": hfr.get("usable"), "hfr_age_hours": hfr.get("age_hours"),
        "ndbc_station": ndbc.get("station"), "ndbc_quality": ndbc.get("quality"), "ndbc_usable": ndbc.get("usable"), "ndbc_age_hours": ndbc.get("age_hours"), "ndbc_wave_age_hours": ndbc.get("wave_age_hours"),
    }, indent=2))


if __name__ == "__main__":
    main()
