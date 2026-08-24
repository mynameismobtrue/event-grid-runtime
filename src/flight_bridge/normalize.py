"""Provider payload normalization and contract observation; never persists raw payloads."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .core import evaluate_offer

CONTRACT_FIELDS = (
    "ignav_id", "price.amount", "price.currency", "price.status", "requires_self_transfer", "legs",
    "segments", "marketing_carrier_code", "marketing_carrier_name", "operating_carrier_code",
    "operating_carrier_name", "flight_number", "departure_airport", "arrival_airport",
    "departure_time_local", "arrival_time_local", "departure_time_utc", "arrival_time_utc",
    "duration_minutes", "aircraft", "bags",
)


def _value(record: dict[str, Any], dotted: str) -> Any:
    value: Any = record
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def contract_matrix(itineraries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for field in CONTRACT_FIELDS:
        values = []
        for itinerary in itineraries:
            if field in {"segments", "marketing_carrier_code", "marketing_carrier_name", "operating_carrier_code", "operating_carrier_name", "flight_number", "departure_airport", "arrival_airport", "departure_time_local", "arrival_time_local", "departure_time_utc", "arrival_time_utc", "duration_minutes", "aircraft"}:
                for leg in itinerary.get("legs", []) if isinstance(itinerary.get("legs"), list) else []:
                    if field == "marketing_carrier_name":
                        values.append(leg.get("carrier") if isinstance(leg, dict) else None)
                        continue
                    for segment in leg.get("segments", []) if isinstance(leg, dict) and isinstance(leg.get("segments"), list) else []:
                        values.append(_value(segment, field) if field != "segments" else segment)
            else:
                values.append(_value(itinerary, field))
        present = [v for v in values if v is not None]
        types = sorted({type(v).__name__ for v in present})
        rows.append({"FIELD": field, "OPENAPI_EXPECTED": "UNDOCUMENTED" if field == "operating_carrier_code" else ("LEG_CARRIER_DISPLAY" if field == "marketing_carrier_name" else "DOCUMENTED"),
                     "REAL_PRESENT": bool(present), "REAL_TYPE": ",".join(types) or None,
                     "NULL_COUNT": len(values) - len(present), "NULL_RATE": (len(values) - len(present)) / len(values) if values else 1.0,
                     "ADAPTER_EXPECTATION": "FAIL_CLOSED_IF_CRITICAL", "COMPATIBILITY": "OBSERVED" if present else "MISSING",
                     "IMPACT": "NON_VALIDATABLE" if field in {"price.status", "operating_carrier_name", "legs"} and not present else "OBSERVATION"})
    return rows


def normalize_itinerary(itinerary: dict[str, Any], query: dict[str, str]) -> dict[str, Any]:
    legs = itinerary.get("legs") if isinstance(itinerary.get("legs"), list) else []
    directions = []
    for leg in legs[:2]:
        segments = []
        for source in leg.get("segments", []) if isinstance(leg, dict) and isinstance(leg.get("segments"), list) else []:
            segments.append({
                "departure_airport": source.get("departure_airport"), "arrival_airport": source.get("arrival_airport"),
                "departure_time_local": source.get("departure_time_local"), "arrival_time_local": source.get("arrival_time_local"),
                "departure_time_utc": source.get("departure_time_utc"), "arrival_time_utc": source.get("arrival_time_utc"),
                "marketing_carrier_code": source.get("marketing_carrier_code"),
                "marketing_carrier_name": leg.get("carrier"),
                "operating_carrier_code": source.get("operating_carrier_code"),
                "operating_carrier_name": source.get("operating_carrier_name"), "flight_number": source.get("flight_number"),
                "aircraft": source.get("aircraft"), "duration_minutes": source.get("duration_minutes"),
                # Provider may furnish auditable country metadata; absent data stays UNKNOWN.
                "connection_country_code": source.get("departure_country_code"),
            })
        directions.append({"origin": segments[0].get("departure_airport") if segments else None,
                           "destination": segments[-1].get("arrival_airport") if segments else None,
                           "duration_minutes": leg.get("duration_minutes") if isinstance(leg, dict) else None,
                           "segments": segments})
    price = itinerary.get("price") if isinstance(itinerary.get("price"), dict) else {}
    return {"source_offer_id": itinerary.get("ignav_id"), "outbound": directions[0] if len(directions) > 0 else None,
            "inbound": directions[1] if len(directions) > 1 else None, "cabin": itinerary.get("cabin_class"),
            "requires_self_transfer": itinerary.get("requires_self_transfer"),
            "protected_self_transfer": itinerary.get("protected_self_transfer"),
            "airport_change": itinerary.get("airport_change"), "separate_tickets": itinerary.get("separate_tickets"),
            "multiple_booking_required": itinerary.get("multiple_booking_required"),
            "price": {"amount": price.get("amount"), "currency": price.get("currency"), "status": price.get("status")},
            "query_id": query["query_id"]}


def summarize_normalized(itineraries: list[dict[str, Any]], query: dict[str, str]) -> Counter:
    counts: Counter = Counter()
    for raw in itineraries:
        decision = evaluate_offer(normalize_itinerary(raw, query))
        counts[decision["ELIGIBILITY_STATE"]] += 1
    return counts
