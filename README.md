# SkyFinder Responder Prototype

**Standalone development prototype — NOT connected to production SkyFinder and NOT field-ready.**

This repository exists only to prove secure real-time responder location sharing before any integration with the working SkyFinder application.

## Current prototype scope

- Firebase Realtime Database + Firebase Authentication
- anonymous authentication for limited two-phone prototype testing only
- each authenticated device writes only its own responder record and breadcrumb slots
- live responder markers with call signs
- LIVE / DELAYED / STALE freshness states
- GPS accuracy display
- responder-to-responder distance in feet/miles
- bounded 120-point breadcrumb ring buffer
- explicit Go Live / Stop Sharing controls
- backend adapter kept separate from the UI so Firebase can be replaced later

## Safety boundary

This repository is intentionally separate from `SkyFinderRescue/Sky-Finder`. Nothing here should be copied or merged into production SkyFinder until multi-device, poor-connectivity, stale-data, privacy, security, and iPhone background-location testing are complete.

## Firebase

Firebase project: `skyfinder-live-prototype-63e49`

Realtime Database: `https://skyfinder-live-prototype-63e49-default-rtdb.firebaseio.com`

The Firebase web configuration identifies the Firebase project and is not a server secret. Database Security Rules are the actual access-control boundary.

Anonymous authentication is temporary and is not acceptable for field deployment. Before any real operational use, replace it with an allowlisted identity method and perform a separate security review.
