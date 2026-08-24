"""Manual-only provider preflight. It will not consume quota without an explicit estimate."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os

from .core import exact_itinerary_match, quota_gate, query_grid, validate_completeness, verify_booking_coverage, evaluate_offer
from .ignav import IgnavClient
from .normalize import contract_matrix, normalize_itinerary
from .adversarial import verifier_fleet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estimated-successful-requests", type=int, required=True)
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args()
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

    completed: list[str] = []
    raw_count = 0
    normalized = Counter({"ELIGIBLE": 0, "HARD_REJECTED": 0, "NON_VALIDATABLE": 0})
    candidates: list[tuple[dict, dict[str, str]]] = []
    all_itineraries: list[dict] = []
    provider_statuses: Counter = Counter()
    hard_reasons: Counter = Counter()
    unknown_reasons: Counter = Counter()

    for query in query_grid():
        result = client.search(query["origin"], query["outbound_date"], query["return_destination"])
        provider_statuses[result.status] += 1
        if result.status != "COMPLETE" or not isinstance(result.payload, dict):
            continue
        completed.append(query["query_id"])
        itineraries = [x for x in result.payload["itineraries"] if isinstance(x, dict)]
        all_itineraries.extend(itineraries)
        raw_count += len(itineraries)
        for raw in itineraries:
            candidate = normalize_itinerary(raw, query)
            decision = evaluate_offer(candidate, require_booking_coherence=False)
            normalized[decision["ELIGIBILITY_STATE"]] += 1
            hard_reasons.update(decision["HARD_REJECT_REASONS"])
            unknown_reasons.update(decision["NON_VALIDATABLE_REASONS"])
            if decision["ELIGIBILITY_STATE"] == "ELIGIBLE":
                candidates.append((candidate, query))

    completeness = validate_completeness(completed)
    complete = completeness["SEARCH_STATUS"] == "COMPLETE"
    matrix = contract_matrix(all_itineraries)
    # Deliberately emit aggregates only: no raw responses, itineraries, booking URLs or provider IDs.
    revalidated = {"VERIFIED_ALERT_CANDIDATE": 0, "NON_VALIDATABLE": 0, "REASONS": {}}
    verifier_summary = {"CANDIDATES_EXAMINED": 0, "CRITICAL_FAILURES": {}}

    def reject(reason: str) -> None:
        revalidated["NON_VALIDATABLE"] += 1
        revalidated["REASONS"][reason] = revalidated["REASONS"].get(reason, 0) + 1

    for candidate, query in candidates[:2]:
        initial_verifiers = verifier_fleet(candidate)
        verifier_summary["CANDIDATES_EXAMINED"] += 1
        for failure in initial_verifiers["CRITICAL_FAILURES"]:
            verifier_summary["CRITICAL_FAILURES"][failure] = verifier_summary["CRITICAL_FAILURES"].get(failure, 0) + 1
        if initial_verifiers["CRITICAL_FAILURES"]:
            reject("ADVERSARIAL_VERIFIER_FAILED")
            continue

        fresh = client.search(query["origin"], query["outbound_date"], query["return_destination"])
        if fresh.status != "COMPLETE" or not isinstance(fresh.payload, dict):
            reject("SECOND_SEARCH_" + fresh.status)
            continue
        matches = [normalize_itinerary(x, query) for x in fresh.payload["itineraries"] if isinstance(x, dict)]
        matches = [x for x in matches if exact_itinerary_match(candidate, x)]
        if len(matches) != 1 or not matches[0].get("source_offer_id"):
            reject("SECOND_SEARCH_EXACT_MATCH_NOT_UNIQUE_OR_MISSING_ID")
            continue

        booked = client.booking_links(str(matches[0]["source_offer_id"]))
        if booked.status != "COMPLETE" or not isinstance(booked.payload, dict):
            reject("BOOKING_LINKS_" + booked.status)
            continue
        data = booked.payload
        options = data["booking_options"]
        itinerary = data["itinerary"]
        booking_option = next((option for option in options if isinstance(option, dict) and verify_booking_coverage(option)), None)
        if booking_option is None:
            reject("BOOKING_FULL_JOURNEY_COVERAGE_UNAVAILABLE")
            continue

        refreshed = normalize_itinerary(itinerary, query)
        final_verifiers = verifier_fleet(refreshed, booking_option=booking_option)
        for failure in final_verifiers["CRITICAL_FAILURES"]:
            verifier_summary["CRITICAL_FAILURES"][failure] = verifier_summary["CRITICAL_FAILURES"].get(failure, 0) + 1
        if final_verifiers["CRITICAL_FAILURES"]:
            reject("ADVERSARIAL_VERIFIER_FAILED")
            continue
        if final_verifiers["VERIFIERS"]["V9_BOOKING_COHERENCE"] != "PASS":
            reject("BOOKING_FULL_JOURNEY_COVERAGE_UNAVAILABLE")
            continue
        if not exact_itinerary_match(matches[0], refreshed) or evaluate_offer(refreshed, require_booking_coherence=False)["ELIGIBILITY_STATE"] != "ELIGIBLE":
            reject("BOOKING_ITINERARY_CHANGED_OR_HARD_FILTER_FAILED")
            continue
        revalidated["VERIFIED_ALERT_CANDIDATE"] += 1

    print(json.dumps({
        "LIVE_PROVIDER_VALIDATED": "TRUE" if complete else "UNKNOWN",
        "PROVIDER_QUERIES_EXPECTED": completeness["PROVIDER_QUERIES_EXPECTED"],
        "PROVIDER_QUERIES_COMPLETE": completeness["PROVIDER_QUERIES_COMPLETE"],
        "SEARCH_STATUS": completeness["SEARCH_STATUS"],
        "PROVIDER_STATUS_COUNTS": dict(sorted(provider_statuses.items())),
        "RAW_OFFERS_COUNT": raw_count,
        "NORMALIZED_OFFERS_COUNT": sum(normalized.values()),
        "ELIGIBLE": normalized["ELIGIBLE"],
        "HARD_REJECTED": normalized["HARD_REJECTED"],
        "NON_VALIDATABLE": normalized["NON_VALIDATABLE"],
        "HARD_REJECT_REASON_COUNTS": dict(sorted(hard_reasons.items())),
        "NON_VALIDATABLE_REASON_COUNTS": dict(sorted(unknown_reasons.items())),
        "CONTRACT_MATRIX": matrix,
        "CONTRACT_FIELDS_OBSERVED": sum(1 for row in matrix if row["REAL_PRESENT"]),
        "REVALIDATION": revalidated,
        "ADVERSARIAL_VERIFIERS": verifier_summary,
        "RAW_RESPONSE_PERSISTED": False,
        "ALERT_DELIVERY_ENABLED": False,
    }))
    return 0 if complete else 6


if __name__ == "__main__":
    raise SystemExit(main())
