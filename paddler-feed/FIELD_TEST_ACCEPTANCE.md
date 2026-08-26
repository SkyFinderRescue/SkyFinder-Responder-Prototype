# SkyFinder Paddler / Kayak Field-Test Acceptance

This document is the release gate for moving the paddler/kayak feature from prototype status into the unified SkyFinder application. A software test is not a substitute for these field checks.

## Required participants

Use at least 3 consenting real participants, preferably covering more than one craft type (SUP, kayak, prone board, surfski or outrigger). Each participant must provide a Garmin MapShare identifier they control and explicitly opt in to exact-location testing. Breadcrumb testing requires the separate breadcrumb consent flag.

## Pass criteria for each participant

1. **Tracker acquisition** — after Garmin tracking is enabled, SkyFinder displays the participant automatically without manually entering coordinates.
2. **Identity** — the displayed participant name/craft is the registered test participant and the feed association is verified.
3. **Last confirmed GPS** — SkyFinder's exact latitude/longitude agrees with the participant's Garmin/known position and is timestamped.
4. **Freshness** — LIVE / AGING / STALE / STOPPED transitions reflect the actual Garmin state and never make stale data look current.
5. **Breadcrumbs** — when separately opted in, only the selected participant's recent trail is shown; timestamp order, course trend and speed are reasonable. Non-opted-in public research feeds show no exact breadcrumb trail.
6. **Loss of tracking** — deliberately stopping tracking produces STOPPED or STALE behavior without retaining a false LIVE status.
7. **Drift handoff** — the drift estimate starts from the participant's last confirmed GPS and timestamp, uses location-appropriate current/wind data, exposes input age, and refuses to calculate when required environmental inputs are stale or unavailable.
8. **Privacy/removal** — disabling a participant removes them from future exact test publishing; protected/passworded feeds remain inaccessible unless the participant explicitly authorizes access.
9. **Mobile usability** — the paddler can be selected, inspected and cleared on an iPhone-sized screen without accidental selection of another target.
10. **Unified target handoff** — an eligible exact paddler position becomes the same internal Rescue Target type used by a paraglider. Coarse research positions cannot become rescue targets.

## Merge gate

The paddler/kayak feature can be called **field-validated** only after:

- at least 3 real participant runs pass items 1–10;
- at least one run includes a deliberate Garmin tracking stop;
- at least one run validates the drift handoff against the participant's last confirmed location;
- no unresolved privacy, stale-data or source-association bug remains;
- automated collector, consent, JavaScript and production-separation tests remain green.

Until then, the feature remains an isolated field-test prototype and production SkyFinder stays unchanged.
