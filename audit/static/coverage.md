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
| Public-data, secret and state controls | workflow/public layout | Partial | Partial | BLOCKED: secret runtime unavailable |
| Provider contract, live schema, revalidation | live validation subgraph | Scaffolded | No | BLOCKED: no safe provider runtime or secret |
| CI, PR, merge, schedule and ChatGPT monitor | Production Gate | Scaffolded | No | BLOCKED: remote CI dispatch/live evidence unavailable |

`MATERIAL_RULES_MAPPED=100%` at the rule-family level. `MATERIAL_RULES_TESTED=60%`; production coverage is not complete.
