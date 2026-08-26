# SkyFinder Garmin Paddler Feed Prototype

Isolated prototype for validating public Garmin MapShare Raw KML ingestion before any consideration of integration into production SkyFinder.

## What it does

- reads a small registry of known public paddling/ocean-expedition MapShare identifiers
- polls Garmin's Raw KML endpoint
- extracts latest usable point
- converts Garmin metric values to imperial display values
- classifies each feed as LIVE, AGING, STALE, STOPPED, NO_DATA, PROTECTED, etc.
- discards Garmin IMEI, internal IDs and message text
- rounds public-test coordinates to 3 decimals unless the registry explicitly records exact-location opt-in
- treats Garmin KML as a location source, not as an SOS alert system

## Prototype freshness thresholds

- LIVE: 0–15 minutes
- AGING: >15–60 minutes
- STALE: >60 minutes
- STOPPED: Garmin last event explicitly says tracking was turned off

These are prototype thresholds and are not yet production SkyFinder policy.

## Files

- `registry.json` — test feed registry
- `collector.py` — Garmin KML fetch/parser/normalizer
- `validate_output.py` — output safety/schema checks
- `data/paddlers-live.json` — normalized output
- `index.html` / `app.js` / `styles.css` — isolated test map
- `tests/test_collector.py` — parser/freshness/privacy tests

## Operational warning

This prototype is not intended for emergency response or real-world rescue decisions.
