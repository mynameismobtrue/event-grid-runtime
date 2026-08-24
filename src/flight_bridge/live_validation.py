"""Manual-only provider preflight. It will not consume quota without an explicit estimate."""
from __future__ import annotations

import argparse
import json
import os

from .core import exact_itinerary_match, quota_gate, query_grid, verify_booking_coverage, evaluate_offer
from .ignav import IgnavClient
from .normalize import contract_matrix, summarize_normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estimated-successful-requests", type=int, required=True)
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args()
    # Full validation needs 12 searches + 2 revalidation reserve; health adds one successful request.
    # Full mode reserves four calls: a second search + booking-links for each of up to two candidates.
    gate = quota_gate(args.estimated_successful_requests, extra_requests=1 if args.health_only else 2)
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
    completed, raw_count, normalized = [], 0, {"ELIGIBLE": 0, "HARD_REJECTED": 0, "NON_VALIDATABLE": 0}
    candidates = []
    all_itineraries = []
    for query in query_grid():
        result = client.search(query["origin"], query["outbound_date"], query["return_destination"])
        if result.status != "COMPLETE" or not isinstance(result.payload, dict) or not isinstance(result.payload.get("itineraries"), list):
            continue
        completed.append(query["query_id"])
        itineraries = [x for x in result.payload["itineraries"] if isinstance(x, dict)]
        all_itineraries.extend(itineraries)
        raw_count += len(itineraries)
        normalized_counts = summarize_normalized(itineraries, query)
        for key in normalized: normalized[key] += normalized_counts[key]
        from .normalize import normalize_itinerary
        for raw in itineraries:
            candidate = normalize_itinerary(raw, query)
            if evaluate_offer(candidate)["ELIGIBILITY_STATE"] == "ELIGIBLE": candidates.append((candidate, query))
    complete = len(completed) == len(query_grid()) and len(set(completed)) == len(query_grid())
    matrix = contract_matrix(all_itineraries)
    # Deliberately emit aggregates only: no raw responses, itineraries, booking URLs or provider IDs.
    revalidated = {"VERIFIED_ALERT_CANDIDATE": 0, "NON_VALIDATABLE": 0}
    for candidate, query in candidates[:2]:
        fresh = client.search(query["origin"], query["outbound_date"], query["return_destination"])
        matches = [] if not isinstance(fresh.payload, dict) else [normalize_itinerary(x, query) for x in fresh.payload.get("itineraries", []) if isinstance(x, dict)]
        matches = [x for x in matches if exact_itinerary_match(candidate, x)]
        if len(matches) != 1 or not matches[0].get("source_offer_id"):
            revalidated["NON_VALIDATABLE"] += 1; continue
        booked = client.booking_links(str(matches[0]["source_offer_id"]))
        data = booked.payload if isinstance(booked.payload, dict) else {}
        options = data.get("booking_options") if isinstance(data.get("booking_options"), list) else []
        itinerary = data.get("itinerary") if isinstance(data.get("itinerary"), dict) else None
        if not itinerary or not any(verify_booking_coverage(option) for option in options):
            revalidated["NON_VALIDATABLE"] += 1; continue
        refreshed = normalize_itinerary(itinerary, query)
        if not exact_itinerary_match(matches[0], refreshed) or evaluate_offer(refreshed)["ELIGIBILITY_STATE"] != "ELIGIBLE":
            revalidated["NON_VALIDATABLE"] += 1; continue
        revalidated["VERIFIED_ALERT_CANDIDATE"] += 1
    print(json.dumps({"LIVE_PROVIDER_VALIDATED": "UNKNOWN", "PROVIDER_QUERIES_EXPECTED": len(query_grid()),
                      "PROVIDER_QUERIES_COMPLETE": len(completed), "SEARCH_STATUS": "COMPLETE" if complete else "INCOMPLETE",
                      "RAW_OFFERS_COUNT": raw_count, "NORMALIZED_OFFERS_COUNT": sum(normalized.values()),
                      "ELIGIBLE": normalized["ELIGIBLE"], "HARD_REJECTED": normalized["HARD_REJECTED"],
                      "NON_VALIDATABLE": normalized["NON_VALIDATABLE"], "CONTRACT_MATRIX": matrix,
                      "CONTRACT_FIELDS_OBSERVED": sum(1 for row in matrix if row["REAL_PRESENT"]), "REVALIDATION": revalidated,
                      "RAW_RESPONSE_PERSISTED": False, "ALERT_DELIVERY_ENABLED": False}))
    return 0 if complete else 6


if __name__ == "__main__":
    raise SystemExit(main())
