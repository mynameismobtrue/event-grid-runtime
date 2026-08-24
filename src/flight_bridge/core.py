from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import product
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

TARGET_REPOSITORY = "mynameismobtrue/event-grid-runtime"
AFRICA_COUNTRY_CODES = {
    "AO", "DZ", "BJ", "BW", "BF", "BI", "CV", "CM", "CF", "TD", "KM", "CG", "CD", "CI",
    "DJ", "EG", "GQ", "ER", "SZ", "ET", "GA", "GM", "GH", "GN", "GW", "KE", "LS", "LR",
    "LY", "MG", "MW", "ML", "MR", "MU", "MA", "MZ", "NA", "NE", "NG", "RW", "ST", "SN",
    "SC", "SL", "SO", "ZA", "SS", "SD", "TZ", "TG", "TN", "UG", "ZM", "ZW"
}
TAAG_CODES = {"DT", "TAAG", "TAAG ANGOLA AIRLINES"}
PRODUCTION_GATE_INPUTS = (
    "CODE_VALIDATED", "NEW_REPO_CONFIRMED", "SECRET_STORAGE_SAFE", "LIVE_PROVIDER_VALIDATED",
    "12_OF_12_COMPLETE", "REAL_SCHEMA_AUDITED", "NO_CRITICAL_SCHEMA_DRIFT",
    "OPERATING_CARRIER_POLICY_SAFE", "TAAG_DEFENSE_CONFIRMED", "AFRICA_DEFENSE_CONFIRMED",
    "OPEN_JAW_CONFIRMED", "SELF_TRANSFER_DEFENSE_CONFIRMED", "PRICE_STATUS_CONFIRMED",
    "BOOKING_LINKS_AUDITED", "REVALIDATION_POLICY_SAFE", "NO_SECRET_SERIALIZATION",
    "QUOTA_CONTROL_VALID", "DEDUPE_VALID", "CHECKPOINT_VALID", "HUMAN_AUDIT_PASS",
    "LEGACY_REPOSITORY_UNCHANGED",
)


class CrossRepoWriteBlocked(RuntimeError):
    pass


def require_target_repository(target_repository: str) -> None:
    """Deterministic remote-write guard. Call immediately before every remote write."""
    if target_repository != TARGET_REPOSITORY:
        raise CrossRepoWriteBlocked("CROSS_REPO_WRITE_BLOCKED")


def tri_and(*values: bool | None) -> bool | None:
    if any(value is False for value in values):
        return False
    return None if any(value is None for value in values) else True


def production_gate(inputs: dict[str, bool | None]) -> dict[str, Any]:
    """A critical FALSE or UNKNOWN always keeps the system in PRE_PRODUCTION."""
    missing = [name for name in PRODUCTION_GATE_INPUTS if name not in inputs]
    false = [name for name in PRODUCTION_GATE_INPUTS if inputs.get(name) is False]
    unknown = missing + [name for name in PRODUCTION_GATE_INPUTS if name in inputs and inputs[name] is None]
    allowed = not false and not unknown
    return {"PRODUCTION_GATE": allowed, "STATE": "PRODUCTION" if allowed else "PRE_PRODUCTION",
            "FALSE_GATES": false, "UNKNOWN_GATES": unknown}


def decimal_brl(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def query_grid() -> list[dict[str, str]]:
    rows = []
    for origin, departure, return_destination in product(
        ("GRU", "VCP"), ("2026-10-26", "2026-10-27", "2026-10-28"), ("GRU", "VCP")
    ):
        query_id = f"{origin}-{departure}-LIS-2026-11-03-{return_destination}"
        rows.append({"query_id": query_id, "origin": origin, "outbound_date": departure,
                     "destination": "LIS", "return_date": "2026-11-03", "return_destination": return_destination})
    return rows


def validate_completeness(query_ids: Iterable[str]) -> dict[str, Any]:
    expected = {row["query_id"] for row in query_grid()}
    seen = list(query_ids)
    actual = set(seen)
    duplicates = sorted({x for x in seen if seen.count(x) > 1})
    missing, unexpected = sorted(expected - actual), sorted(actual - expected)
    complete = len(seen) == 12 and not duplicates and not missing and not unexpected
    return {"PROVIDER_QUERIES_EXPECTED": 12, "PROVIDER_QUERIES_STARTED": len(seen),
            "PROVIDER_QUERIES_COMPLETE": len(seen), "UNIQUE_EXPECTED_QUERY_IDS": len(actual & expected),
            "DUPLICATES": duplicates, "MISSING": missing, "UNEXPECTED": unexpected,
            "SEARCH_STATUS": "COMPLETE" if complete else "INCOMPLETE"}


def quota_gate(successful_requests: int, *, extra_requests: int = 0) -> dict[str, Any]:
    remaining = max(0, 1000 - max(0, int(successful_requests)))
    required = 12 + 2 + extra_requests + 50
    allowed = remaining >= required
    return {"IGNAV_PAID_USAGE_AUTHORIZED": False, "IGNAV_SUCCESSFUL_REQUESTS_ESTIMATED": successful_requests,
            "IGNAV_FREE_REQUESTS_ESTIMATED_REMAINING": remaining, "FREE_TIER_WARNING": remaining <= 150,
            "MINIMUM_REMAINING_REQUIRED_BEFORE_START": required,
            "QUOTA_GATE_STATUS": "OK" if allowed else "QUOTA_GATE_BLOCKED", "QUOTA_GATE_ALLOWED": allowed}


def _text(value: Any) -> str:
    return str(value or "").strip().upper()


def _segments(direction: dict[str, Any]) -> list[dict[str, Any]] | None:
    segments = direction.get("segments")
    return segments if isinstance(segments, list) and segments else None


def _parse_lis_date(segment: dict[str, Any]) -> str | None:
    utc = segment.get("arrival_time_utc")
    if not utc:
        return None
    try:
        return datetime.fromisoformat(str(utc).replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Lisbon")).date().isoformat()
    except ValueError:
        return None


def _connection_minutes(segments: list[dict[str, Any]]) -> list[int] | None:
    output = []
    for left, right in zip(segments, segments[1:]):
        try:
            arr = datetime.fromisoformat(str(left["arrival_time_utc"]).replace("Z", "+00:00"))
            dep = datetime.fromisoformat(str(right["departure_time_utc"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return None
        output.append(int((dep - arr).total_seconds() / 60))
    return output


def itinerary_fingerprint(offer: dict[str, Any]) -> str:
    material = []
    for direction in (offer.get("outbound"), offer.get("inbound")):
        for s in (direction or {}).get("segments", []):
            material.append("|".join(str(s.get(k, "")) for k in (
                "departure_airport", "arrival_airport", "departure_time_utc", "arrival_time_utc",
                "flight_number", "marketing_carrier_code", "operating_carrier_name")))
    return sha256("\n".join(material).encode()).hexdigest()


def evaluate_offer(offer: dict[str, Any]) -> dict[str, Any]:
    """Returns only ELIGIBLE, HARD_REJECTED or NON_VALIDATABLE; missing critical data is fail-closed."""
    reasons: list[str] = []
    unknown: list[str] = []
    outbound, inbound = offer.get("outbound"), offer.get("inbound")
    if not isinstance(outbound, dict) or not isinstance(inbound, dict):
        unknown.append("DIRECTION_MISSING")
        outbound, inbound = outbound or {}, inbound or {}
    if _text(outbound.get("origin")) not in {"GRU", "VCP"} or _text(outbound.get("destination")) != "LIS": reasons.append("ROUTE_OUTBOUND")
    if _text(inbound.get("origin")) != "LIS" or _text(inbound.get("destination")) not in {"GRU", "VCP"}: reasons.append("ROUTE_INBOUND")
    if offer.get("cabin") != "economy": reasons.append("CABIN")
    journey_protection_fields = ("requires_self_transfer", "protected_self_transfer", "airport_change", "separate_tickets", "multiple_booking_required")
    if any(offer.get(k) is True for k in journey_protection_fields):
        reasons.append("UNPROTECTED_JOURNEY")
    if any(not isinstance(offer.get(k), bool) for k in journey_protection_fields):
        unknown.append("JOURNEY_PROTECTION_UNKNOWN")
    for direction in (outbound, inbound):
        segments = _segments(direction)
        if not segments:
            unknown.append("SEGMENTS_MISSING"); continue
        if len(segments) - 1 > 1: reasons.append("TOO_MANY_CONNECTIONS")
        duration = direction.get("duration_minutes")
        if not isinstance(duration, int): unknown.append("DURATION_UNKNOWN")
        elif duration > 1080: reasons.append("DURATION_EXCEEDED")
        connections = _connection_minutes(segments)
        if connections is None: unknown.append("CONNECTION_TIME_UNKNOWN")
        elif any(minutes < 0 or minutes > 300 for minutes in connections): reasons.append("CONNECTION_EXCEEDED")
        for s in segments:
            fields = (s.get("marketing_carrier_code"), s.get("marketing_carrier_name"),
                      s.get("operating_carrier_code"), s.get("operating_carrier_name"))
            if not s.get("operating_carrier_name"): unknown.append("OPERATING_CARRIER_UNKNOWN")
            if any(_text(x) in TAAG_CODES or "TAAG" in _text(x) for x in fields): reasons.append("TAAG")
            country = s.get("connection_country_code")
            if s is not segments[0]:
                if not country: unknown.append("CONNECTION_COUNTRY_UNKNOWN")
                elif _text(country) in AFRICA_COUNTRY_CODES: reasons.append("AFRICA_CONNECTION")
    out_segments = _segments(outbound)
    if out_segments:
        lis_arrival = _parse_lis_date(out_segments[-1])
        if not lis_arrival: unknown.append("LIS_ARRIVAL_TIME_UNKNOWN")
        elif lis_arrival not in {"2026-10-27", "2026-10-28"}: reasons.append("LIS_ARRIVAL_DATE")
    price = decimal_brl((offer.get("price") or {}).get("amount"))
    if price is None or (offer.get("price") or {}).get("currency") != "BRL" or (offer.get("price") or {}).get("status") != "verified": unknown.append("PRICE_UNVERIFIED")
    elif price >= Decimal("4500.00"): reasons.append("PRICE_THRESHOLD")
    state = "HARD_REJECTED" if reasons else ("NON_VALIDATABLE" if unknown else "ELIGIBLE")
    return {"ELIGIBILITY_STATE": state, "HARD_REJECT_REASONS": sorted(set(reasons)),
            "NON_VALIDATABLE_REASONS": sorted(set(unknown)), "ITINERARY_FINGERPRINT": itinerary_fingerprint(offer),
            "VERIFIED_ALERT_CANDIDATE": False}


def verify_booking_coverage(option: dict[str, Any]) -> bool:
    indexes = option.get("leg_indexes")
    return isinstance(indexes, list) and set(indexes) == {0, 1} and len(indexes) == 2


def classify_provider_response(http_status: int | None, payload: Any = None) -> str:
    """Technical failures are never classified as no flights."""
    if http_status is None:
        return "PROVIDER_NETWORK_ERROR"
    if http_status == 200:
        # Transport validation accepts either JSON object or list. Endpoint-specific
        # schema validation happens after classification (airport health is a list).
        return "COMPLETE" if isinstance(payload, (dict, list)) else "SCHEMA_INVALID"
    if http_status == 400:
        return "INVALID_REQUEST"
    if http_status == 401:
        return "AUTH_REQUIRED"
    if http_status == 402:
        return "BILLING_REQUIRED"
    if http_status == 404:
        return "NOT_FOUND"
    if http_status == 424:
        return "UPSTREAM_DEPENDENCY"
    if http_status == 429:
        return "RATE_LIMITED"
    if 500 <= http_status <= 599:
        return "PROVIDER_HTTP_ERROR"
    return "PROVIDER_HTTP_ERROR"


def sanitized_public(value: Any, *, forbidden_values: Iterable[str] = ()) -> Any:
    """Remove secret-bearing keys/URLs recursively; input stays in-memory only."""
    secret_keys = ("authorization", "x-api-key", "api_key", "token", "cookie", "session")
    if isinstance(value, dict):
        return {str(k): sanitized_public(v, forbidden_values=forbidden_values)
                for k, v in value.items() if not any(mark in str(k).lower() for mark in secret_keys)}
    if isinstance(value, list):
        return [sanitized_public(x, forbidden_values=forbidden_values) for x in value]
    if isinstance(value, str):
        lower = value.lower()
        if any(str(x) and str(x) in value for x in forbidden_values):
            return "[REDACTED]"
        if lower.startswith(("http://", "https://")):
            try:
                if any(k.lower() in {"token", "session", "authorization", "key", "state", "code", "sig"}
                       for k, _ in parse_qsl(urlsplit(value).query, keep_blank_values=True)):
                    return "[REDACTED_URL]"
            except ValueError:
                return "[REDACTED_URL]"
    return value


def exact_itinerary_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Price and opaque provider IDs do not establish itinerary identity."""
    return itinerary_fingerprint(left) == itinerary_fingerprint(right)


def revalidation_decision(first: dict[str, Any], second: dict[str, Any] | None,
                          booking_option: dict[str, Any] | None) -> dict[str, Any]:
    if second is None:
        return {"status": "NON_VALIDATABLE", "failure_code": "SECOND_SEARCH_MISSING"}
    if not exact_itinerary_match(first, second):
        return {"status": "NON_VALIDATABLE", "failure_code": "ITINERARY_CHANGED"}
    if not booking_option or not verify_booking_coverage(booking_option):
        return {"status": "NON_VALIDATABLE", "failure_code": "BOOKING_OPTION_MISSING"}
    result = evaluate_offer(second)
    if result["ELIGIBILITY_STATE"] != "ELIGIBLE":
        return {"status": "NON_VALIDATABLE", "failure_code": "REVALIDATION_HARD_FILTER_FAILED"}
    return {"status": "VERIFIED_ALERT_CANDIDATE", "failure_code": None,
            "itinerary_fingerprint": result["ITINERARY_FINGERPRINT"]}


def dedupe_decision(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return {"should_alert": True, "reason": "NEW_ITINERARY"}
    if itinerary_fingerprint(previous) != itinerary_fingerprint(current):
        return {"should_alert": True, "reason": "NEW_ITINERARY"}
    old, new = decimal_brl((previous.get("price") or {}).get("amount")), decimal_brl((current.get("price") or {}).get("amount"))
    if old is not None and new is not None and old - new >= Decimal("100"):
        return {"should_alert": True, "reason": "PRICE_DROP_100_BRL"}
    return {"should_alert": False, "reason": "DUPLICATE_NO_MATERIAL_IMPROVEMENT"}
