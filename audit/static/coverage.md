# Material protocol coverage matrix

| Original rule family | V3 node or gate | Implemented | Tested | Status |
|---|---|---:|---:|---|
| Legacy immutability and cross-repo writes | `require_target_repository` | Yes | Yes | PASS |
| Exact 12-cell open-jaw grid and completeness | `query_grid`, `validate_completeness` | Yes | Yes | PASS |
| Quota, warning and paid-use stop | `quota_gate` | Yes | Yes | PASS |
| Route, dates, cabin, duration, connections | `evaluate_offer` | Yes | Yes | PASS |
| TAAG, Africa and operating-carrier fail closed | `evaluate_offer` | Yes | Yes | PASS |
| Self-transfer and protected commercial journey | `evaluate_offer`, `verify_booking_coverage` | Yes | Yes | PASS |
| Decimal strict price and price.status | `decimal_brl`, `evaluate_offer` | Yes | Yes | PASS |
| Public-data and secret controls | sanitizer, secret scan, public layout | Yes | Yes | PASS: run `32680617116` persisted no raw response or alert data |
| Provider contract and sanitized live schema | `contract_matrix`, normalizer | Yes | Partial | UNKNOWN: operating carrier code undocumented; geography metadata needs more evidence |
| Booking revalidation | `booking_links`, exact itinerary and coverage checks | Yes | Yes | PASS for fail-closed path; no positive full-journey coverage observed |
| Adversarial verifier fleet | `verifier_fleet` V1–V12 | Yes | Yes | PASS: TAAG, booking split and privacy refutation tests |
| CI and manual pre-production workflow | `live-provider-validation.yml` | Yes | Yes | PASS: run `32680617116`, 23 tests and 12/12 query grid |
| PR, merge, schedule and ChatGPT monitor | Production Gate | Scaffolded | No | BLOCKED: production inputs are not all TRUE |

`MATERIAL_RULES_MAPPED=100%` at the rule-family level. Static and fail-closed live-path coverage is evidenced; production coverage is not complete because semantic carrier/geography, safe persistent state and human audit remain unresolved.
