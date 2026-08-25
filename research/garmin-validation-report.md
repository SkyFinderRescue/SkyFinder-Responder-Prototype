# Garmin public paddler KML validation

Generated: 2026-08-25T15:12:19.137300+00:00

| Feed | California relevance | Public KML | HTTP | Placemarks | Operational fields |
|---|---|---:|---:|---:|---|
| Cali Paddler (`calipaddler`) | 90-mile California paddle test including Santa Barbara coastline; SUP/OC/kayak/surfski community | YES | 200 | 2 | Course, Device Identifier, Device Type, Elevation, Event, IMEI, Id, In Emergency, Incident Id, Latitude, Longitude, Map Display Name, Name, Note, SpatialRefSystem, Text, Time, Time UTC, Valid GPS Fix, Velocity |
| Team Ocean (`teamoceanlive`) | Human-powered ocean row departed Monterey, California for Kauai in 2025 | YES | 200 | 0 |  |
| KURSIS / Aurimas Mockus (`KURSIS`) | Solo human-powered ocean row departed San Diego, California toward Brisbane | YES | 200 | 2 | Course, Device Identifier, Device Type, Elevation, Event, IMEI, Id, In Emergency, Incident Id, Latitude, Longitude, Map Display Name, Name, Note, SpatialRefSystem, Text, Time, Time UTC, Valid GPS Fix, Velocity |
| Mike Ward SUP (`YCMPS`) | Non-California control: verified stand-up paddle expedition feed | YES | 200 | 2 | Course, Device Identifier, Device Type, Elevation, Event, IMEI, Id, In Emergency, Incident Id, Latitude, Longitude, Map Display Name, Name, Note, SpatialRefSystem, Text, Time, Time UTC, Valid GPS Fix, Velocity |
| Bart de Zwart SUP (`BartdeZwartSUPCrossing`) | Non-California control: verified stand-up paddle expedition feed | YES | 200 | 2 | Course, Device Identifier, Device Type, Elevation, Event, IMEI, Id, In Emergency, Incident Id, Latitude, Longitude, Map Display Name, Name, Note, SpatialRefSystem, Text, Time, Time UTC, Valid GPS Fix, Velocity |
| LouAnne Harris (`LouAnneHarris`) | SUP endurance paddler with California River Quest history; published MapShare is known password-protected | NO / protected / unavailable | 401, 401 | — | — |

## Parsed non-sensitive samples

### Cali Paddler
```json
{
  "Map Display Name": "Clarke Graves",
  "Device Type": "GPSMAP 86i",
  "Latitude": "present (numeric; 41.06 rounded)",
  "Longitude": "present (numeric; -124.15 rounded)",
  "Elevation": "-9.81 m from MSL",
  "Velocity": "0.0 km/h",
  "Course": "0.00 \u00b0 True",
  "Valid GPS Fix": "True",
  "In Emergency": "False",
  "Event": "Tracking turned off from device.",
  "Time UTC": "10/3/2025 11:46:45 PM"
}
```
### Team Ocean
```json
{}
```
### KURSIS / Aurimas Mockus
```json
{
  "Map Display Name": "Aurimas Mockus",
  "Device Type": "GPSMAP 86i",
  "Latitude": "present (numeric; -20.39 rounded)",
  "Longitude": "present (numeric; 156.87 rounded)",
  "Elevation": "2.34 m from MSL",
  "Velocity": "8.0 km/h",
  "Course": "202.50 \u00b0 True",
  "Valid GPS Fix": "True",
  "In Emergency": "False",
  "Event": "Tracking turned on from device.",
  "Time UTC": "2/28/2025 5:28:30 AM"
}
```
### Mike Ward SUP
```json
{
  "Map Display Name": "Mike Ward",
  "Device Type": "inReach Mini 2",
  "Latitude": "present (numeric; 44.57 rounded)",
  "Longitude": "present (numeric; -92.54 rounded)",
  "Elevation": "231.12 m from MSL",
  "Velocity": "4.0 km/h",
  "Course": "0.00 \u00b0 True",
  "Valid GPS Fix": "True",
  "In Emergency": "False",
  "Event": "Tracking interval received.",
  "Time UTC": "8/10/2024 8:57:00 PM"
}
```
### Bart de Zwart SUP
```json
{
  "Map Display Name": "Bart de Zwart",
  "Device Type": "InReach BT V1",
  "Latitude": "present (numeric; -15.86 rounded)",
  "Longitude": "present (numeric; 168.17 rounded)",
  "Elevation": "10.46 m from MSL",
  "Velocity": "0.0 km/h",
  "Course": "90.00 \u00b0 True",
  "Valid GPS Fix": "True",
  "In Emergency": "False",
  "Event": "Tracking message received.",
  "Time UTC": "3/17/2019 2:08:00 AM"
}
```

Notes: exact coordinates, IMEIs, Garmin internal IDs, and message text are intentionally not retained in this research report.
