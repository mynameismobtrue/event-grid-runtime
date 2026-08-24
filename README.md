# Event Grid Runtime

Public-safe, fail-closed execution graph for a GRU/VCP to LIS monitoring bridge.

This repository contains code, fixtures and static audit evidence only. It must
never contain live itinerary data, booking links, provider sessions or secrets.
`PROTOCOL_VERSION=LISBOA_V2.2` is immutable by architecture.

## State

`PRE_PRODUCTION`. The live workflow is manual-only and cannot run without a
GitHub Actions secret that is intentionally not stored here.

## Local verification

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Remote safety

All remote writes must call `require_target_repository()` before using GitHub.
The only permitted target is `mynameismobtrue/event-grid-runtime`.
