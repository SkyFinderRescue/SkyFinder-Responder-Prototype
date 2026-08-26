# SkyFinder Maritime Drift Prototype

Isolated research prototype for estimating a probable drift area after a paddler's GPS feed stops updating.

## Data sources

- NOAA/IOOS HF Radar US West Coast near-real-time 2 km surface-current product (`ucsdHfrW2`). IOOS states the national HF-radar network distributes near-real-time surface currents through NOAA/NDBC infrastructure.
- NOAA National Data Buoy Center real-time standard meteorological data for wind and waves. The Santa Barbara test adapter selects the nearer of stations 46053 and 46054.
- U.S. Coast Guard COMDTINST 16130.2H Appendix H Table H-7 for leeway slope, intercept, divergence angle and standard error where a matching object class exists.

## Object classes in v1

Direct Coast Guard table matches:
- Person in water.
- Sea kayak with person on aft deck.
- Surf board with person.

The published Coast Guard table does not provide a SUP-specific row. `sup_person_proxy` and `prone_person_proxy` therefore reuse the published surf-board-with-person coefficients and are visibly marked as proxies. They must not be described as exact Coast Guard SUP coefficients.

## Method

The engine uses Monte Carlo particles and 20-minute drift steps. Each step combines the observed HF-radar surface-current vector with wind-driven leeway. Published Coast Guard leeway standard error and left/right divergence are used to create spread. The prototype does **not** reproduce SAROPS environmental-error fields, scenario weighting, shoreline interaction, model selection or Coast Guard Environmental Data Server logic.

The generated output includes 50% and 90% approximate particle envelopes and always carries `operational_use: false`.

## Safety boundary

This is not Coast Guard SAROPS and is not approved for operational search planning. It is designed to validate data access, source aging, object-class handling and SkyFinder user-interface concepts before any field-validation work.
