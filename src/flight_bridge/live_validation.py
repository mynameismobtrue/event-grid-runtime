"""Manual-only provider preflight. It will not consume quota without an explicit estimate."""
from __future__ import annotations

import argparse
import json
import os

from .core import quota_gate, query_grid
from .ignav import IgnavClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estimated-successful-requests", type=int, required=True)
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args()
    # Full validation needs 12 searches + 2 revalidation reserve; health adds one successful request.
    gate = quota_gate(args.estimated_successful_requests, extra_requests=1 if args.health_only else 0)
    if not gate["QUOTA_GATE_ALLOWED"]:
        print(json.dumps({"LIVE_PROVIDER_VALIDATED": "UNKNOWN", "QUOTA_GATE": gate["QUOTA_GATE_STATUS"]}))
        return 3
    client = IgnavClient(os.environ.get("IGNAV_API_KEY", ""))
    if not client.configured:
        print(json.dumps({"LIVE_PROVIDER_VALIDATED": "UNKNOWN", "ERROR_CODE": "AUTH_REQUIRED"}))
        return 2
    if args.health_only:
        result = client.health_check()
        print(json.dumps({"HEALTH_STATUS": result.status, "HTTP_STATUS": result.http_status, "RAW_RESPONSE_PERSISTED": False}))
        return 0 if result.status == "COMPLETE" else 4
    # The grid intentionally avoids printing response data. Full normalization/revalidation must be added
    # before this branch can claim LIVE_PROVIDER_VALIDATED=true.
    print(json.dumps({"LIVE_PROVIDER_VALIDATED": "UNKNOWN", "QUERY_GRID_EXPECTED": len(query_grid()),
                      "ERROR_CODE": "NORMALIZATION_SUBGRAPH_NOT_YET_ENABLED"}))
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
