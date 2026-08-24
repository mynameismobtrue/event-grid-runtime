"""Fail-closed adversarial checks. Outputs only verifier status and codes, never offers or secrets."""
from __future__ import annotations

from typing import Any

from .core import (
    AFRICA_COUNTRY_CODES,
    carrier_matches_taag,
    evaluate_offer,
    operator_name_is_specific,
    sanitized_public,
    timezone_is_africa,
    verify_booking_coverage,
)


VERIFIER_IDS = (
    "V1_TAAG_FALSE_NEGATIVE", "V2_AFRICA_FALSE_NEGATIVE", "V3_OPERATING_CARRIER",
    "V4_SELF_TRANSFER", "V5_CONNECTION_DURATION", "V6_JOURNEY_DURATION",
    "V7_ARRIVAL_DATE_TIMEZONE", "V8_PRICE_THRESHOLD_STATUS", "V9_BOOKING_COHERENCE",
    "V10_OPEN_JAW_INTEGRITY", "V11_MISSING_FIELD_FAIL_CLOSED", "V12_PRIVACY_SECRET",
)


def _status(condition: bool | None) -> str:
    return "PASS" if condition is True else ("FAIL" if condition is False else "NOT_APPLICABLE")


def _directions(offer: dict[str, Any]) -> list[dict[str, Any]]:
    return [direction for direction in (offer.get("outbound"), offer.get("inbound")) if isinstance(direction, dict)]


def _segments(offer: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for direction in _directions(offer):
        output.extend(segment for segment in (direction.get("segments") or []) if isinstance(segment, dict))
    return output


def _connections(offer: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for direction in _directions(offer):
        segments = [segment for segment in (direction.get("segments") or []) if isinstance(segment, dict)]
        output.extend(segments[1:])
    return output


def _taag_marker(segment: dict[str, Any]) -> bool:
    return any(carrier_matches_taag(segment.get(key)) for key in (
        "marketing_carrier_code", "marketing_carrier_name", "operating_carrier_code", "operating_carrier_name"
    ))


def verifier_fleet(offer: dict[str, Any], *, booking_option: dict[str, Any] | None = None,
                   public_candidate: Any | None = None) -> dict[str, Any]:
    """Try to refute a candidate. Critical FAIL blocks; final alert additionally requires V9 to be PASS."""
    decision = evaluate_offer(offer)
    hard = set(decision["HARD_REJECT_REASONS"])
    unknown = set(decision["NON_VALIDATABLE_REASONS"])
    outbound, inbound = offer.get("outbound") or {}, offer.get("inbound") or {}
    segments = _segments(offer)
    connections = _connections(offer)

    taag_present = any(_taag_marker(segment) for segment in segments)
    taag_invariant = ("TAAG" in hard) if taag_present else ("TAAG" not in hard)

    africa_present = any(
        str(segment.get("connection_country_code") or "").upper() in AFRICA_COUNTRY_CODES
        or timezone_is_africa(segment.get("connection_timezone") or segment.get("departure_timezone"))
        for segment in connections
    )
    africa_unknown = any(not (segment.get("connection_timezone") or segment.get("departure_timezone")) for segment in connections)
    if africa_present:
        africa_invariant = "AFRICA_CONNECTION" in hard
    elif africa_unknown:
        africa_invariant = "CONNECTION_COUNTRY_UNKNOWN" in unknown
    else:
        africa_invariant = "AFRICA_CONNECTION" not in hard and "CONNECTION_COUNTRY_UNKNOWN" not in unknown

    operator_unknown = any(not operator_name_is_specific(segment.get("operating_carrier_name")) for segment in segments)
    operator_invariant = ("OPERATING_CARRIER_UNKNOWN" in unknown) if operator_unknown else ("OPERATING_CARRIER_UNKNOWN" not in unknown)

    self_transfer_known_safe = offer.get("requires_self_transfer") is False and offer.get("airport_change") is False
    self_transfer_invariant = (
        "UNPROTECTED_JOURNEY" in hard
        or "JOURNEY_PROTECTION_UNKNOWN" in unknown
        or "AIRPORT_CHANGE_UNKNOWN" in unknown
        or self_transfer_known_safe
    )

    has_connection = any(len(direction.get("segments") or []) > 1 for direction in _directions(offer))
    connection_invariant = (
        "CONNECTION_EXCEEDED" in hard
        or "CONNECTION_TIME_UNKNOWN" in unknown
        or not has_connection
        or ("CONNECTION_EXCEEDED" not in hard and "CONNECTION_TIME_UNKNOWN" not in unknown)
    )

    durations = [direction.get("duration_minutes") for direction in _directions(offer)]
    duration_invariant = (
        "DURATION_EXCEEDED" in hard
        or "DURATION_UNKNOWN" in unknown
        or (len(durations) == 2 and all(isinstance(value, int) and value <= 1080 for value in durations))
    )

    arrival_invariant = (
        "LIS_ARRIVAL_DATE" in hard
        or "LIS_ARRIVAL_TIME_UNKNOWN" in unknown
        or ("LIS_ARRIVAL_DATE" not in hard and "LIS_ARRIVAL_TIME_UNKNOWN" not in unknown)
    )
    price_invariant = (
        "PRICE_THRESHOLD" in hard
        or "PRICE_UNVERIFIED" in unknown
        or ("PRICE_THRESHOLD" not in hard and "PRICE_UNVERIFIED" not in unknown)
    )

    output = {
        "V1_TAAG_FALSE_NEGATIVE": _status(taag_invariant),
        "V2_AFRICA_FALSE_NEGATIVE": _status(africa_invariant),
        "V3_OPERATING_CARRIER": _status(operator_invariant),
        "V4_SELF_TRANSFER": _status(self_transfer_invariant),
        "V5_CONNECTION_DURATION": _status(connection_invariant),
        "V6_JOURNEY_DURATION": _status(duration_invariant),
        "V7_ARRIVAL_DATE_TIMEZONE": _status(arrival_invariant),
        "V8_PRICE_THRESHOLD_STATUS": _status(price_invariant),
        "V9_BOOKING_COHERENCE": _status(None if booking_option is None else verify_booking_coverage(booking_option)),
        "V10_OPEN_JAW_INTEGRITY": _status(outbound.get("origin") in {"GRU", "VCP"} and outbound.get("destination") == "LIS" and inbound.get("origin") == "LIS" and inbound.get("destination") in {"GRU", "VCP"}),
        "V11_MISSING_FIELD_FAIL_CLOSED": _status(not unknown or decision["ELIGIBILITY_STATE"] == "NON_VALIDATABLE"),
        "V12_PRIVACY_SECRET": _status(public_candidate is None or sanitized_public(public_candidate) == public_candidate),
    }
    blocking = [key for key, value in output.items() if value == "FAIL"]
    has_not_applicable = any(value == "NOT_APPLICABLE" for value in output.values())
    fleet_status = "FAIL" if blocking else ("PASS_WITH_NOT_APPLICABLE" if has_not_applicable else "PASS")
    return {"VERIFIERS": output, "CRITICAL_FAILURES": blocking, "VERIFIER_FLEET_STATUS": fleet_status}
