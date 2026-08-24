# V3.3 build checkpoint

## Capability audit

| Capability | Result | Evidence |
|---|---|---|
| Native subagents | Available | Runtime capability |
| Parallel tool execution | Available | Parallel read-only GitHub fan-out completed |
| Structured output | Available | GitHub action results |
| Persistent safe live state | Not available | Public repository cannot receive live state |
| GitHub read | Available | Legacy repository audits |
| GitHub remote write | Available conditionally | File/branch/PR tools exist, guarded in code |
| GitHub create repository | Completed by human | `mynameismobtrue/event-grid-runtime` is now public |
| GitHub Actions secret write | Completed by human | `IGNAV_API_KEY` was added without being shared in chat |
| CI trigger / workflow dispatch | Completed by human | Manual full-grid run `32680391123` succeeded |

## Legacy read-only evidence

- Repository: `mynameismobtrue/file-drop`
- `LEGACY_SOURCE_READ_ONLY=true`; no write tool was invoked against it.
- Asserted SHA `813132345e50dc8cc5b8bad9aac6a0f34453a308` exists and has CI run `32611988447=success`.
- The real state advanced: PR #2 is closed and merged, source PR head is `6ffb49a43618425a904a83c55697891ddfe0f44b`, merge commit is `c90d3fd396192d52e8181c4a3e030635858f034b`.
- PR-head CI `32616816324=success`; no workflow run was returned for the merge SHA.
- `SOURCE_TREE_SHA=UNKNOWN` because the connected GitHub read surface did not expose a tree object for the selected commit.

## New implementation

- Local safe checkout: `execution-graph-v3` at `a6ff7de`.
- Remote target is public, verified and contains the 11-file V3.3 baseline on `main`; `execution-graph-v3` was created from that baseline.
- The remote baseline is a selective clean-room V3 implementation, not a claimed byte-for-byte legacy export.
- `LEGACY_MODIFIED=false`.

## Sanitized live evidence: run `32680391123`

- Executed remote SHA: `d4c112058c6b8f0178939463efaa622dee8568c0` on `execution-graph-v3`.
- CI: Python compile PASS; 21/21 regression tests PASS.
- Provider: `PROVIDER_QUERIES_EXPECTED=12`, `PROVIDER_QUERIES_COMPLETE=12`, `SEARCH_STATUS=COMPLETE`.
- In-memory processing: 37 raw provider offers, 37 normalized offers, 2 eligible, 32 hard rejected, 3 non-validatable.
- Contract matrix: 20/21 designated fields were observed. `operating_carrier_code` was absent for 95/95 observed segments and remains untrusted/unused. `operating_carrier_name` was present for 95/95 segments and is the active fail-closed carrier evidence.
- Revalidation: both eligible candidates were rejected as `NON_VALIDATABLE` because `BOOKING_FULL_JOURNEY_COVERAGE_UNAVAILABLE`; zero alert candidates were produced.
- `RAW_RESPONSE_PERSISTED=false`; `ALERT_DELIVERY_ENABLED=false`.

## Production blockers

1. `OPERATING_CARRIER_SEMANTIC_POLICY`: provider documentation does not establish a trusted operating-carrier code and the live-name behavior must receive adversarial semantic evidence.
2. `AFRICA_METADATA_LIVE_EVIDENCE`: the code rejects unknown connection geography, but the provider did not supply enough live geographic evidence to prove the metadata route end to end.
3. `PERSISTENT_LIVE_STATE`: no safe non-public state store is available; public Git must not receive live itineraries, histories or booking data.
4. `REVALIDATION_REAL_ALERT_CANDIDATE`: revalidation was exercised only through fail-closed rejection. No full-journey booking coverage was confirmed.
5. `HUMAN_AUDIT`: required before any production gate decision.
6. `PRODUCTION_GATE`: the preceding gates are FALSE or UNKNOWN. Schedule and alerts remain disabled.
