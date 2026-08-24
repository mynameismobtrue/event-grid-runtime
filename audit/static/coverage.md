# Material protocol coverage matrix

| Original rule family | V3 node or gate | Implemented | Tested / evidenced | Status |
|---|---|---:|---:|---|
| Legacy immutability and cross-repo writes | `require_target_repository`, workflow repository guard | Yes | Yes | PASS: this mission wrote only to `mynameismobtrue/event-grid-runtime`; legacy remained read-only |
| Exact 12-cell open-jaw grid and completeness | `query_grid`, `validate_completeness` | Yes | Yes | PASS |
| Quota, free-tier warning and paid-use stop | `quota_gate` | Yes | Yes | PASS for deterministic gate; provider-actual usage remains unavailable. Post-run conservative floor is 244 successful requests, not 232 |
| Route, dates, cabin, duration, connections | `evaluate_offer` | Yes | Yes | PASS |
| TAAG fail-closed, including hidden operating carrier | `carrier_matches_taag`, `evaluate_offer`, V1 | Yes | Static yes; live adversarial evidence pending | PARTIAL: static PASS, production gate remains UNKNOWN |
| African connection fail-closed | documented segment timezone + optional country metadata, V2 | Yes | Static yes; current live timezone evidence pending | PARTIAL: static PASS, production gate remains UNKNOWN |
| Operating-carrier semantic policy | documented `operating_carrier_name`, V3 | Yes | Live field observed 95/95 in run `32680617116`; provider documentation defines it as operator of aircraft | PASS: operating carrier code remains undocumented and is not promoted |
| Self-transfer, airport change and protected journey | `evaluate_offer`, derived airport-change continuity, booking coverage | Yes | Yes | PASS |
| Decimal strict price and `price.status` | `decimal_brl`, `evaluate_offer` | Yes | Static + live | PASS |
| HTTP 200 incomplete payload, auth/billing/upstream/network failures | endpoint schema validation, error classifier | Yes | Yes | PASS: technical errors never become `NO_FLIGHTS_FOUND` |
| Public-data and secret controls | recursive sanitizer, checkpoint sanitizer, secret scan | Yes | Yes | PASS: no raw response, provider ID or booking URL is intentionally persisted by the bridge |
| Provider contract and sanitized live schema | `contract_matrix`, normalizer | Yes | Partial current-generation live evidence | UNKNOWN: current implementation has not run live after timezone/schema hardening |
| Booking revalidation | second search, physical fingerprint, fresh `ignav_id`, full `{0,1}` coverage plus usable link | Yes | Static yes; live fail-closed path observed | PASS for policy; no positive full-journey coverage has been observed |
| Adversarial verifier fleet | V1-V12 | Yes | Yes | PASS: clean-candidate false positives fixed; TAAG, Africa, ambiguous operator, split booking, malformed schema and privacy regressions covered |
| Static CI | `static-safety-ci.yml` | Yes | Yes | PASS: implementation SHA `0772b8aa19f6109e4d051d2b147f649922de799d`, run `32682084222`; observable commit status enabled |
| Persistent live state compatible with public-only repository | Production Gate | No safe design accepted | Audited | FAIL: `PERSISTENT_LIVE_STATE_AVAILABLE=false` |
| PR, merge, schedule and ChatGPT monitor | Production Gate | Scaffolded | No | BLOCKED: production inputs are not all TRUE |

`MATERIAL_RULES_MAPPED=100%` at the rule-family level.

The current architecture intentionally remains fail-closed. A public repository may contain code, aggregate audit facts and static CI evidence, but it must not persist live offer state, dedupe history, itinerary detail, per-offer price, provider IDs, booking URLs, sessions or raw provider payloads. Because no acceptable persistent live-state mechanism is proven under that constraint, production cannot be promoted even if the remaining live semantic gates later pass.

## Current production blockers

FALSE:
- `PERSISTENT_LIVE_STATE_AVAILABLE`

UNKNOWN:
- `LIVE_PROVIDER_VALIDATED`
- `NO_CRITICAL_SCHEMA_DRIFT`
- `TAAG_DEFENSE_CONFIRMED`
- `AFRICA_DEFENSE_CONFIRMED`
- `HUMAN_AUDIT_PASS`
