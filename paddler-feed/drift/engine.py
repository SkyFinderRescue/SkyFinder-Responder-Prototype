#!/usr/bin/env python3
"""SAROPS-aligned maritime drift research engine for the SkyFinder paddler prototype.

This is NOT Coast Guard SAROPS and is NOT operational SAR software. It uses the
same public environmental data families and current USCG leeway coefficients
where a directly matching drift-object class exists.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EARTH_RADIUS_M = 6371008.8
KNOT_TO_MPS = 0.5144444444444445
MPS_TO_KNOT = 1.9438444924406048

# COMDTINST 16130.2H, Appendix H, Table H-7.
# slope/intercept produce leeway speed in knots from wind speed in knots.
USCG_LEEWAY = {
    "piw": {
        "label": "Person in water",
        "slope": 0.011,
        "intercept_kts": 0.07,
        "divergence_deg": 30.0,
        "std_error_kts": 0.35,
        "source_match": "direct",
    },
    "sea_kayak_person": {
        "label": "Sea kayak with person on aft deck",
        "slope": 0.011,
        "intercept_kts": 0.24,
        "divergence_deg": 15.0,
        "std_error_kts": 0.10,
        "source_match": "direct",
    },
    "surfboard_person": {
        "label": "Surf board with person",
        "slope": 0.020,
        "intercept_kts": 0.00,
        "divergence_deg": 15.0,
        "std_error_kts": 0.25,
        "source_match": "direct",
    },
    # The current public Coast Guard table does not publish a SUP-specific row.
    # These options intentionally reuse the published surf-board-with-person row
    # and are explicitly flagged as proxies rather than calling them exact SUP data.
    "sup_person_proxy": {
        "label": "SUP with person (USCG surf-board proxy)",
        "slope": 0.020,
        "intercept_kts": 0.00,
        "divergence_deg": 15.0,
        "std_error_kts": 0.25,
        "source_match": "proxy: USCG surf board with person",
    },
    "prone_person_proxy": {
        "label": "Prone board with person (USCG surf-board proxy)",
        "slope": 0.020,
        "intercept_kts": 0.00,
        "divergence_deg": 15.0,
        "std_error_kts": 0.25,
        "source_match": "proxy: USCG surf board with person",
    },
}


@dataclass
class Vector:
    east_mps: float
    north_mps: float


def vector_from_speed_bearing(speed_mps: float, bearing_deg: float) -> Vector:
    r = math.radians(bearing_deg % 360.0)
    return Vector(speed_mps * math.sin(r), speed_mps * math.cos(r))


def speed_bearing(v: Vector) -> tuple[float, float]:
    speed = math.hypot(v.east_mps, v.north_mps)
    bearing = (math.degrees(math.atan2(v.east_mps, v.north_mps)) + 360.0) % 360.0
    return speed, bearing


def displace(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    lat2 = lat + math.degrees(north_m / EARTH_RADIUS_M)
    denom = EARTH_RADIUS_M * max(1e-9, math.cos(math.radians(lat)))
    lon2 = lon + math.degrees(east_m / denom)
    return lat2, lon2


def convex_hull(points: list[tuple[float, float]]) -> list[list[float]]:
    # Input/output use lon,lat ordering for GeoJSON-style rendering.
    pts = sorted(set(points))
    if len(pts) <= 2:
        return [[x, y] for x, y in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    if hull and hull[0] != hull[-1]:
        hull.append(hull[0])
    return [[x, y] for x, y in hull]


def probability_hull(particles: list[tuple[float, float]], fraction: float) -> list[list[float]]:
    if not particles:
        return []
    mean_lat = sum(p[0] for p in particles) / len(particles)
    mean_lon = sum(p[1] for p in particles) / len(particles)
    ranked = sorted(particles, key=lambda p: (p[0] - mean_lat) ** 2 + (p[1] - mean_lon) ** 2)
    n = max(3, min(len(ranked), int(math.ceil(len(ranked) * fraction))))
    return convex_hull([(lon, lat) for lat, lon in ranked[:n]])


def simulate(
    *,
    lat: float,
    lon: float,
    current_u_mps: float,
    current_v_mps: float,
    wind_speed_kts: float,
    wind_from_deg: float,
    object_key: str,
    hours: float,
    particles: int = 3000,
    seed: int = 42,
    step_minutes: int = 20,
) -> dict:
    if object_key not in USCG_LEEWAY:
        raise ValueError(f"Unknown object type: {object_key}")
    if hours <= 0 or hours > 48:
        raise ValueError("hours must be >0 and <=48")
    if particles < 100 or particles > 20000:
        raise ValueError("particles must be between 100 and 20000")

    cfg = USCG_LEEWAY[object_key]
    rng = random.Random(seed)
    steps = max(1, int(math.ceil(hours * 60.0 / step_minutes)))
    dt_s = (hours * 3600.0) / steps
    downwind_bearing = (wind_from_deg + 180.0) % 360.0
    current = Vector(current_u_mps, current_v_mps)

    final = []
    for _ in range(particles):
        plat, plon = lat, lon
        side = -1.0 if rng.random() < 0.5 else 1.0
        # USCG H-7 standard error is applied to leeway speed. We intentionally
        # do not invent extra wind/current uncertainty here; that would require
        # additional validated environmental error fields to be SAROPS-like.
        for _step in range(steps):
            leeway_kts = max(
                0.0,
                cfg["slope"] * wind_speed_kts
                + cfg["intercept_kts"]
                + rng.gauss(0.0, cfg["std_error_kts"]),
            )
            leeway = vector_from_speed_bearing(
                leeway_kts * KNOT_TO_MPS,
                downwind_bearing + side * cfg["divergence_deg"],
            )
            east = (current.east_mps + leeway.east_mps) * dt_s
            north = (current.north_mps + leeway.north_mps) * dt_s
            plat, plon = displace(plat, plon, east, north)
        final.append((plat, plon))

    center_lat = sum(p[0] for p in final) / len(final)
    center_lon = sum(p[1] for p in final) / len(final)
    cur_speed, cur_bearing = speed_bearing(current)
    sample_stride = max(1, len(final) // 250)

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "operational_use": False,
        "warning": "Research prototype only. Estimated drift is not a confirmed GPS position and is not Coast Guard SAROPS.",
        "method": {
            "particle_count": particles,
            "step_minutes": step_minutes,
            "elapsed_hours": hours,
            "monte_carlo": True,
            "environmental_uncertainty_added": False,
            "note": "Spread uses the published USCG leeway standard error and left/right divergence. Additional SAROPS environmental uncertainty fields are not reproduced.",
        },
        "object": {"key": object_key, **cfg},
        "last_known_position": {"lat": lat, "lon": lon},
        "environment_used": {
            "current_u_mps": current_u_mps,
            "current_v_mps": current_v_mps,
            "current_speed_kts": cur_speed * MPS_TO_KNOT,
            "current_toward_deg_true": cur_bearing,
            "wind_speed_kts": wind_speed_kts,
            "wind_from_deg_true": wind_from_deg,
            "downwind_deg_true": downwind_bearing,
        },
        "estimate": {
            "center": {"lat": center_lat, "lon": center_lon},
            "probability_50_polygon": probability_hull(final, 0.50),
            "probability_90_polygon": probability_hull(final, 0.90),
            "sample_particles": [{"lat": p[0], "lon": p[1]} for p in final[::sample_stride][:250]],
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--environment", required=True)
    ap.add_argument("--object", default="sea_kayak_person", choices=sorted(USCG_LEEWAY))
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--particles", type=int, default=3000)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    env = json.loads(Path(args.environment).read_text(encoding="utf-8"))
    hfr = env.get("surface_current") or {}
    wind = env.get("wind_wave") or {}
    if not hfr.get("usable"):
        raise SystemExit(f"HF-radar current unavailable/unusable: {hfr.get('error') or hfr.get('quality')}")
    if not wind.get("usable"):
        raise SystemExit(f"NDBC wind unavailable/unusable: {wind.get('error') or wind.get('quality')}")

    out = simulate(
        lat=float(env["query_point"]["lat"]),
        lon=float(env["query_point"]["lon"]),
        current_u_mps=float(hfr["u_mps"]),
        current_v_mps=float(hfr["v_mps"]),
        wind_speed_kts=float(wind["wind_speed_kts"]),
        wind_from_deg=float(wind["wind_from_deg_true"]),
        object_key=args.object,
        hours=args.hours,
        particles=args.particles,
        seed=args.seed,
    )
    out["source_snapshot_generated_at_utc"] = env.get("generated_at_utc")
    out["source_metadata"] = env.get("sources")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "object": out["object"]["label"],
        "source_match": out["object"]["source_match"],
        "center": out["estimate"]["center"],
        "particles": out["method"]["particle_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
