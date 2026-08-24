"""Fail-closed adversarial checks. Outputs only verifier status and codes, never offers or secrets."""
from __future__ import annotations

from typing import Any

from .core import evaluate_offer, sanitized_public, verify_booking_coverage


VERIFIER_IDS = (
    "V1_TAAG_FALSE_NEGATIVE", "V2_AFRICA_FALSE_NEGATIVE", "V3_OPERATING_CARRIER",
    "V4_SELF_TRANSFER", "V5_CONNECTION_DURATION", "V6_JOURNEY_DURATION",
    "V7_ARRIVAL_DATE_TIMEZONE", "V8_PRICE_THRESHOLD_STATUS", "V9_BOOKING_COHERENCE",
    "V10_OPEN_JAW_INTEGRITY", "V11_MISSING_FIELD_FAIL_CLOSED", "V12_PRIVACY_SECRET",
)


def _status(condition: bool | None) -> str:
    return "PASS" if condition is True else ("FAIL" if condition is False else "NOT_APPLICABLE")


def verifier_fleet(offer: dict[str, Any], *, booking_option: dict[str, Any] | None = None,
                   public_candidate: Any | None = None) -> dict[str, Any]:
    """Try to refute a candidate; a critical FAIL or UNKNOWN must block its alert path."""
    decision = evaluate_offer(offer)
    hard = set(decision["HARD_REJECT_REASONS"])
    unknown = set(decision["NON_VALIDATABLE_REASONS"])
    outbound, inbound = offer.get("outbound") or {}, offer.get("inbound") or {}
    segments = (outbound.get("segments") or []) + (inbound.get("segments") or [])
    carrier_text = " ".join(str(s.get(k, "")) for s in segments for k in (
        "marketing_carrier_code", "marketing_carrier_name", "operating_carrier_code", "operating_carrier_name"))
    output = {
        "V1_TAAG_FALSE_NEGATIVE": _status("TAAG" in carrier_text.upper() and "TAAG" in hard),
        "V2_AFRICA_FALSE_NEGATIVE": _status("AFRICA_CONNECTION" in hard or "CONNECTION_COUNTRY_UNKNOWN" in unknown),
        "V3_OPERATING_CARRIER": _status("OPERATING_CARRIER_UNKNOWN" in unknown or all(bool(s.get("operating_carrier_name")) for s in segments)),
        "V4_SELF_TRANSFER": _status("UNPROTECTED_JOURNEY" in hard or "JOURNEY_PROTECTION_UNKNOWN" in unknown or all(offer.get(k) is False for k in ("requires_self_transfer", "protected_self_transfer", "airport_change", "separate_tickets", "multiple_booking_required"))),
        "V5_CONNECTION_DURATION": _status("CONNECTION_EXCEEDED" in hard or "CONNECTION_TIME_UNKNOWN" in unknown or len(outbound.get("segments") or []) <= 1),
        "V6_JOURNEY_DURATION": _status("DURATION_EXCEEDED" in hard or "DURATION_UNKNOWN" in unknown or (outbound.get("duration_minutes", 1081) <= 1080 and inbound.get("duration_minutes", 1081) <= 1080)),
        "V7_ARRIVAL_DATE_TIMEZONE": _status("LIS_ARRIVAL_DATE" in hard or "LIS_ARRIVAL_TIME_UNKNOWN" in unknown or decision["ELIGIBILITY_STATE"] in {"ELIGIBLE", "NON_VALIDATABLE"}),
        "V8_PRICE_THRESHOLD_STATUS": _status("PRICE_THRESHOLD" in hard or "PRICE_UNVERIFIED" in unknown or decision["ELIGIBILITY_STATE"] == "ELIGIBLE"),
        "V9_BOOKING_COHERENCE": _status(None if booking_option is None else verify_booking_coverage(booking_option)),
        "V10_OPEN_JAW_INTEGRITY": _status(outbound.get("origin") in {"GRU", "VCP"} and outbound.get("destination") == "LIS" and inbound.get("origin") == "LIS" and inbound.get("destination") in {"GRU", "VCP"}),
        "V11_MISSING_FIELD_FAIL_CLOSED": _status(not unknown or decision["ELIGIBILITY_STATE"] == "NON_VALIDATABLE"),
        "V12_PRIVACY_SECRET": _status(public_candidate is None or sanitized_public(public_candidate) == public_candidate),
    }
    blocking = [key for key, value in output.items() if value == "FAIL"]
    return {"VERIFIERS": output, "CRITICAL_FAILURES": blocking,
            "VERIFIER_FLEET_STATUS": "PASS" if not blocking else "FAIL"}
