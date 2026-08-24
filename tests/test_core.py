import json
from pathlib import Path
import tempfile
import unittest

from flight_bridge.core import (
    AFRICA_COUNTRY_CODES,
    CrossRepoWriteBlocked,
    PRODUCTION_GATE_INPUTS,
    classify_provider_response,
    dedupe_decision,
    evaluate_offer,
    production_gate,
    query_grid,
    quota_gate,
    revalidation_decision,
    require_target_repository,
    sanitized_public,
    validate_completeness,
    verify_booking_coverage,
)
from flight_bridge.ignav import IgnavClient
from flight_bridge.normalize import contract_matrix, normalize_itinerary
from flight_bridge.adversarial import VERIFIER_IDS, verifier_fleet
from flight_bridge.audit import save_checkpoint


def booking_option(indexes=None, url="https://booking.example/full"):
    return {"leg_indexes": [0, 1] if indexes is None else indexes, "links": [{"url": url}]}


def offer(**changes):
    segment = {
        "departure_airport": "GRU",
        "arrival_airport": "LIS",
        "departure_time_utc": "2026-10-27T12:00:00Z",
        "arrival_time_utc": "2026-10-27T20:00:00Z",
        "departure_timezone": "America/Sao_Paulo",
        "arrival_timezone": "Europe/Lisbon",
        "marketing_carrier_code": "TP",
        "marketing_carrier_name": "TAP Air Portugal",
        "operating_carrier_name": "TAP Air Portugal",
        "flight_number": "TP88",
    }
    inbound = dict(
        segment,
        departure_airport="LIS",
        arrival_airport="GRU",
        departure_time_utc="2026-11-03T12:00:00Z",
        arrival_time_utc="2026-11-03T20:00:00Z",
        departure_timezone="Europe/Lisbon",
        arrival_timezone="America/Sao_Paulo",
    )
    row = {
        "outbound": {"origin": "GRU", "destination": "LIS", "duration_minutes": 600, "segments": [segment]},
        "inbound": {"origin": "LIS", "destination": "GRU", "duration_minutes": 600, "segments": [inbound]},
        "cabin": "economy",
        "requires_self_transfer": False,
        "protected_self_transfer": False,
        "airport_change": False,
        "separate_tickets": False,
        "multiple_booking_required": False,
        "price": {"amount": 4499.99, "currency": "BRL", "status": "verified"},
    }
    row.update(changes)
    return row


def one_stop_offer(connection_timezone="Europe/Madrid", operating_name="Iberia"):
    row = offer()
    first = dict(
        row["outbound"]["segments"][0],
        arrival_airport="MAD",
        arrival_time_utc="2026-10-27T17:00:00Z",
        arrival_timezone="Europe/Madrid",
        operating_carrier_name=operating_name,
        marketing_carrier_name="Iberia",
        marketing_carrier_code="IB",
        flight_number="IB1",
    )
    second = dict(
        first,
        departure_airport="MAD",
        arrival_airport="LIS",
        departure_time_utc="2026-10-27T18:00:00Z",
        arrival_time_utc="2026-10-27T20:00:00Z",
        departure_timezone=connection_timezone,
        arrival_timezone="Europe/Lisbon",
        connection_timezone=connection_timezone,
        flight_number="IB2",
    )
    row["outbound"] = {"origin": "GRU", "destination": "LIS", "duration_minutes": 660, "segments": [first, second]}
    return row


class CoreTests(unittest.TestCase):
    def test_grid_is_exactly_twelve_unique_cells(self):
        self.assertEqual(12, len({x["query_id"] for x in query_grid()}))

    def test_completeness_accepts_exact_grid(self):
        result = validate_completeness([x["query_id"] for x in query_grid()])
        self.assertEqual("COMPLETE", result["SEARCH_STATUS"])
        self.assertEqual(12, result["UNIQUE_EXPECTED_QUERY_IDS"])

    def test_completeness_duplicate_missing_unexpected(self):
        ids = [x["query_id"] for x in query_grid()]
        result = validate_completeness(ids[:-1] + [ids[0], "bad"])
        self.assertEqual("INCOMPLETE", result["SEARCH_STATUS"])
        self.assertTrue(result["DUPLICATES"])
        self.assertTrue(result["MISSING"])
        self.assertTrue(result["UNEXPECTED"])

    def test_price_boundaries_are_strict_decimal(self):
        self.assertEqual("ELIGIBLE", evaluate_offer(offer())["ELIGIBILITY_STATE"])
        self.assertEqual("HARD_REJECTED", evaluate_offer(offer(price={"amount": 4500.00, "currency": "BRL", "status": "verified"}))["ELIGIBILITY_STATE"])
        self.assertEqual("ELIGIBLE", evaluate_offer(offer(price={"amount": 4499.999, "currency": "BRL", "status": "verified"}))["ELIGIBILITY_STATE"])

    def test_taag_operating_and_missing_are_fail_closed(self):
        bad = offer()
        bad["outbound"]["segments"][0]["operating_carrier_name"] = "TAAG Angola Airlines"
        decision = evaluate_offer(bad)
        self.assertEqual("HARD_REJECTED", decision["ELIGIBILITY_STATE"])
        self.assertIn("TAAG", decision["HARD_REJECT_REASONS"])
        unknown = offer()
        unknown["outbound"]["segments"][0]["operating_carrier_name"] = None
        self.assertEqual("NON_VALIDATABLE", evaluate_offer(unknown)["ELIGIBILITY_STATE"])

    def test_taag_hidden_in_codeshare_is_rejected(self):
        bad = offer()
        segment = bad["outbound"]["segments"][0]
        segment["marketing_carrier_code"] = "TP"
        segment["marketing_carrier_name"] = "TAP Air Portugal"
        segment["operating_carrier_name"] = "Linhas Aéreas de Angola"
        decision = evaluate_offer(bad)
        self.assertIn("TAAG", decision["HARD_REJECT_REASONS"])
        self.assertEqual("PASS", verifier_fleet(bad)["VERIFIERS"]["V1_TAAG_FALSE_NEGATIVE"])

    def test_ambiguous_operator_name_is_non_validatable(self):
        row = offer()
        row["outbound"]["segments"][0]["operating_carrier_name"] = "Various Airlines"
        decision = evaluate_offer(row)
        self.assertEqual("NON_VALIDATABLE", decision["ELIGIBILITY_STATE"])
        self.assertIn("OPERATING_CARRIER_UNKNOWN", decision["NON_VALIDATABLE_REASONS"])
        self.assertEqual("PASS", verifier_fleet(row)["VERIFIERS"]["V3_OPERATING_CARRIER"])

    def test_duration_boundaries(self):
        row = offer()
        row["outbound"]["duration_minutes"] = 1080
        self.assertEqual("ELIGIBLE", evaluate_offer(row)["ELIGIBILITY_STATE"])
        row["outbound"]["duration_minutes"] = 1081
        self.assertEqual("HARD_REJECTED", evaluate_offer(row)["ELIGIBILITY_STATE"])

    def test_arrival_29_is_rejected_and_28_is_allowed_in_lisbon_timezone(self):
        row = offer()
        row["outbound"]["segments"][0]["arrival_time_utc"] = "2026-10-28T23:30:00Z"
        self.assertEqual("ELIGIBLE", evaluate_offer(row)["ELIGIBILITY_STATE"])
        row["outbound"]["segments"][0]["arrival_time_utc"] = "2026-10-29T00:30:00Z"
        self.assertEqual("HARD_REJECTED", evaluate_offer(row)["ELIGIBILITY_STATE"])

    def test_two_connections_rejected(self):
        row = offer()
        a = dict(row["outbound"]["segments"][0], arrival_airport="MAD", arrival_time_utc="2026-10-27T14:00:00Z")
        b = dict(a, departure_airport="MAD", arrival_airport="CDG", departure_time_utc="2026-10-27T15:00:00Z", arrival_time_utc="2026-10-27T17:00:00Z", connection_timezone="Europe/Madrid")
        c = dict(a, departure_airport="CDG", arrival_airport="LIS", departure_time_utc="2026-10-27T18:00:00Z", arrival_time_utc="2026-10-27T20:00:00Z", connection_timezone="Europe/Paris")
        row["outbound"]["segments"] = [a, b, c]
        self.assertIn("TOO_MANY_CONNECTIONS", evaluate_offer(row)["HARD_REJECT_REASONS"])

    def test_connection_300_minutes_allowed_301_rejected(self):
        row = one_stop_offer()
        row["outbound"]["segments"][0]["arrival_time_utc"] = "2026-10-27T13:00:00Z"
        row["outbound"]["segments"][1]["departure_time_utc"] = "2026-10-27T18:00:00Z"
        self.assertNotIn("CONNECTION_EXCEEDED", evaluate_offer(row)["HARD_REJECT_REASONS"])
        row["outbound"]["segments"][1]["departure_time_utc"] = "2026-10-27T18:01:00Z"
        self.assertIn("CONNECTION_EXCEEDED", evaluate_offer(row)["HARD_REJECT_REASONS"])

    def test_non_africa_connection_timezone_is_allowed(self):
        row = one_stop_offer("Europe/Madrid")
        decision = evaluate_offer(row)
        self.assertEqual("ELIGIBLE", decision["ELIGIBILITY_STATE"])
        self.assertEqual("PASS", verifier_fleet(row)["VERIFIERS"]["V2_AFRICA_FALSE_NEGATIVE"])

    def test_africa_connection_timezone_is_hard_rejected_without_country_metadata(self):
        row = one_stop_offer("Africa/Luanda", operating_name="TAP Air Portugal")
        second = row["outbound"]["segments"][1]
        second.pop("connection_country_code", None)
        decision = evaluate_offer(row)
        self.assertEqual("HARD_REJECTED", decision["ELIGIBILITY_STATE"])
        self.assertIn("AFRICA_CONNECTION", decision["HARD_REJECT_REASONS"])
        self.assertEqual("PASS", verifier_fleet(row)["VERIFIERS"]["V2_AFRICA_FALSE_NEGATIVE"])

    def test_africa_country_code_is_rejected_when_present(self):
        row = one_stop_offer("Europe/Madrid")
        row["outbound"]["segments"][1]["connection_country_code"] = "AO"
        self.assertIn("AFRICA_CONNECTION", evaluate_offer(row)["HARD_REJECT_REASONS"])
        self.assertIn("AO", AFRICA_COUNTRY_CODES)

    def test_missing_connection_geography_is_fail_closed(self):
        row = one_stop_offer()
        row["outbound"]["segments"][1].pop("connection_timezone", None)
        row["outbound"]["segments"][1].pop("departure_timezone", None)
        decision = evaluate_offer(row)
        self.assertEqual("NON_VALIDATABLE", decision["ELIGIBILITY_STATE"])
        self.assertIn("CONNECTION_COUNTRY_UNKNOWN", decision["NON_VALIDATABLE_REASONS"])

    def test_price_status_and_self_transfer(self):
        self.assertEqual("NON_VALIDATABLE", evaluate_offer(offer(price={"amount": 4400, "currency": "BRL"}))["ELIGIBILITY_STATE"])
        self.assertEqual("HARD_REJECTED", evaluate_offer(offer(requires_self_transfer=True))["ELIGIBILITY_STATE"])

    def test_missing_requires_self_transfer_is_fail_closed(self):
        row = offer()
        row.pop("requires_self_transfer")
        self.assertEqual("NON_VALIDATABLE", evaluate_offer(row)["ELIGIBILITY_STATE"])

    def test_missing_protected_self_transfer_does_not_invent_a_transfer(self):
        row = offer()
        row.pop("protected_self_transfer")
        self.assertEqual("ELIGIBLE", evaluate_offer(row)["ELIGIBILITY_STATE"])

    def test_missing_airport_change_is_fail_closed(self):
        row = offer()
        row.pop("airport_change")
        self.assertEqual("NON_VALIDATABLE", evaluate_offer(row)["ELIGIBILITY_STATE"])

    def test_discovery_can_defer_booking_only_fields_but_final_evaluation_cannot(self):
        row = offer()
        row.pop("separate_tickets")
        row.pop("multiple_booking_required")
        self.assertEqual("NON_VALIDATABLE", evaluate_offer(row)["ELIGIBILITY_STATE"])
        self.assertEqual("ELIGIBLE", evaluate_offer(row, require_booking_coherence=False)["ELIGIBILITY_STATE"])

    def test_quota_boundary_and_paid_use_false(self):
        self.assertTrue(quota_gate(936)["QUOTA_GATE_ALLOWED"])
        self.assertFalse(quota_gate(937)["QUOTA_GATE_ALLOWED"])
        self.assertFalse(quota_gate(0)["IGNAV_PAID_USAGE_AUTHORIZED"])

    def test_booking_integrity_requires_both_legs_and_real_link(self):
        self.assertTrue(verify_booking_coverage(booking_option()))
        self.assertFalse(verify_booking_coverage({"leg_indexes": [0, 1], "links": []}))
        self.assertFalse(verify_booking_coverage(booking_option([0])))
        self.assertFalse(verify_booking_coverage({"leg_indexes": [0, 1]}))

    def test_cross_repo_guard(self):
        require_target_repository("mynameismobtrue/event-grid-runtime")
        with self.assertRaises(CrossRepoWriteBlocked):
            require_target_repository("mynameismobtrue/file-drop")

    def test_production_gate_requires_every_input_true(self):
        all_true = {name: True for name in PRODUCTION_GATE_INPUTS}
        self.assertTrue(production_gate(all_true)["PRODUCTION_GATE"])
        all_true["HUMAN_AUDIT_PASS"] = None
        result = production_gate(all_true)
        self.assertFalse(result["PRODUCTION_GATE"])
        self.assertEqual("PRE_PRODUCTION", result["STATE"])
        self.assertIn("HUMAN_AUDIT_PASS", result["UNKNOWN_GATES"])

    def test_production_gate_explicitly_requires_safe_persistent_state(self):
        all_true = {name: True for name in PRODUCTION_GATE_INPUTS}
        all_true["PERSISTENT_LIVE_STATE_AVAILABLE"] = False
        result = production_gate(all_true)
        self.assertFalse(result["PRODUCTION_GATE"])
        self.assertEqual(["PERSISTENT_LIVE_STATE_AVAILABLE"], result["FALSE_GATES"])

    def test_technical_errors_never_mean_no_flights(self):
        expected = {
            None: "PROVIDER_NETWORK_ERROR",
            401: "AUTH_REQUIRED",
            402: "BILLING_REQUIRED",
            403: "FORBIDDEN",
            424: "UPSTREAM_DEPENDENCY",
            429: "RATE_LIMITED",
            500: "PROVIDER_HTTP_ERROR",
        }
        for status, classification in expected.items():
            with self.subTest(status=status):
                self.assertEqual(classification, classify_provider_response(status))

    def test_http_200_incomplete_search_payload_is_schema_invalid(self):
        client = IgnavClient("x", lambda *_: (200, b'{"itineraries":[]}'))
        self.assertEqual("SCHEMA_INVALID", client.search("GRU", "2026-10-27", "GRU").status)

    def test_http_200_non_json_is_schema_invalid(self):
        result = IgnavClient("x", lambda *_: (200, b"not-json")).search("GRU", "2026-10-27", "GRU")
        self.assertEqual("SCHEMA_INVALID", result.status)

    def test_timeout_is_network_error_not_no_flights(self):
        def timeout(*_):
            raise TimeoutError()
        result = IgnavClient("x", timeout).search("GRU", "2026-10-27", "GRU")
        self.assertEqual("PROVIDER_NETWORK_ERROR", result.status)

    def test_secret_provider_id_and_booking_url_sanitization(self):
        dirty = {
            "Authorization": "Bearer x",
            "ignav_id": "opaque",
            "nested": {
                "source_offer_id": "opaque2",
                "booking_options": [{"links": [{"url": "https://booking.example/x?token=abc"}]}],
                "safe": "yes",
            },
            "url": "https://a.example/x?token=abc",
        }
        clean = sanitized_public(dirty, forbidden_values=["secret"])
        self.assertNotIn("Authorization", clean)
        self.assertNotIn("ignav_id", clean)
        self.assertNotIn("source_offer_id", clean["nested"])
        self.assertNotIn("booking_options", clean["nested"])
        self.assertEqual("[REDACTED_URL]", clean["url"])
        self.assertEqual("yes", clean["nested"]["safe"])

    def test_public_checkpoint_recursively_strips_provider_ids_urls_and_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            save_checkpoint(
                path,
                safe_count=12,
                nested={
                    "ignav_id": "opaque",
                    "Authorization": "secret",
                    "booking_link": "https://booking.example/private",
                    "evidence": "https://provider.example/live/offer",
                },
            )
            data = json.loads(path.read_text())
            self.assertEqual(12, data["safe_count"])
            self.assertNotIn("ignav_id", data["nested"])
            self.assertNotIn("Authorization", data["nested"])
            self.assertNotIn("booking_link", data["nested"])
            self.assertEqual("[REDACTED_URL]", data["nested"]["evidence"])

    def test_revalidation_requires_exact_match_and_full_journey(self):
        first = offer()
        self.assertEqual("VERIFIED_ALERT_CANDIDATE", revalidation_decision(first, offer(), booking_option())["status"])
        changed = offer()
        changed["outbound"]["segments"][0]["flight_number"] = "TP99"
        self.assertEqual("ITINERARY_CHANGED", revalidation_decision(first, changed, booking_option())["failure_code"])
        self.assertEqual("BOOKING_OPTION_MISSING", revalidation_decision(first, offer(), booking_option([0]))["failure_code"])

    def test_alert_dedupe_only_on_material_change(self):
        first = offer()
        self.assertFalse(dedupe_decision(first, offer())["should_alert"])
        lower = offer(price={"amount": 4399, "currency": "BRL", "status": "verified"})
        self.assertEqual("PRICE_DROP_100_BRL", dedupe_decision(first, lower)["reason"])

    def test_ignav_open_jaw_is_one_commercial_request(self):
        body = IgnavClient("x").build_open_jaw_query("GRU", "2026-10-27", "VCP")
        self.assertEqual(2, len(body["legs"]))
        self.assertEqual("GRU", body["legs"][0]["origin"])
        self.assertEqual("VCP", body["legs"][1]["destination"])
        self.assertFalse(body["allow_self_transfer"])
        self.assertEqual(["DT"], body["airlines_exclude"])

    def test_ignav_transport_classifies_auth_without_payload_persistence(self):
        result = IgnavClient("x", lambda *_: (401, b'{"detail":"denied"}')).health_check()
        self.assertEqual("AUTH_REQUIRED", result.status)
        self.assertEqual(401, result.http_status)

    def test_ignav_health_accepts_documented_airport_list(self):
        result = IgnavClient("x", lambda *_: (200, b'[{"iata":"GRU"}]')).health_check()
        self.assertEqual("COMPLETE", result.status)
        self.assertEqual(200, result.http_status)

    def test_ignav_booking_links_uses_opaque_id_only_and_validates_schema(self):
        seen = []
        payload = b'{"itinerary":{},"booking_options":[]}'
        result = IgnavClient("x", lambda method, path, body: (seen.append((method, path, body)) or (200, payload))).booking_links("opaque")
        self.assertEqual("COMPLETE", result.status)
        self.assertEqual(("POST", "/fares/booking-links", {"ignav_id": "opaque"}), seen[0])
        invalid = IgnavClient("x", lambda *_: (200, b'{"itinerary":{}}')).booking_links("opaque")
        self.assertEqual("SCHEMA_INVALID", invalid.status)

    def test_normalization_keeps_operating_carrier_missing_fail_closed(self):
        raw = {
            "ignav_id": "x",
            "cabin_class": "economy",
            "requires_self_transfer": False,
            "price": {"amount": 4400, "currency": "BRL", "status": "verified"},
            "legs": [
                {"carrier": "TAP", "duration_minutes": 600, "segments": [{"departure_airport": "GRU", "arrival_airport": "LIS", "departure_time_utc": "2026-10-27T12:00:00Z", "arrival_time_utc": "2026-10-27T20:00:00Z", "departure_timezone": "America/Sao_Paulo", "arrival_timezone": "Europe/Lisbon", "marketing_carrier_code": "TP"}]},
                {"carrier": "TAP", "duration_minutes": 600, "segments": [{"departure_airport": "LIS", "arrival_airport": "GRU", "departure_time_utc": "2026-11-03T12:00:00Z", "arrival_time_utc": "2026-11-03T20:00:00Z", "departure_timezone": "Europe/Lisbon", "arrival_timezone": "America/Sao_Paulo", "marketing_carrier_code": "TP"}]},
            ],
        }
        normalized = normalize_itinerary(raw, query_grid()[0])
        self.assertEqual("NON_VALIDATABLE", evaluate_offer(normalized, require_booking_coherence=False)["ELIGIBILITY_STATE"])
        self.assertTrue(any(row["FIELD"] == "operating_carrier_name" and not row["REAL_PRESENT"] for row in contract_matrix([raw])))

    def test_normalization_uses_documented_timezone_for_connection_geography(self):
        raw = {
            "ignav_id": "x",
            "cabin_class": "economy",
            "requires_self_transfer": False,
            "price": {"amount": 4400, "currency": "BRL", "status": "verified"},
            "legs": [
                {"carrier": "Iberia", "duration_minutes": 660, "segments": [
                    {"departure_airport": "GRU", "arrival_airport": "MAD", "departure_time_utc": "2026-10-27T10:00:00Z", "arrival_time_utc": "2026-10-27T17:00:00Z", "departure_timezone": "America/Sao_Paulo", "arrival_timezone": "Europe/Madrid", "marketing_carrier_code": "IB", "operating_carrier_name": "Iberia", "flight_number": "IB1"},
                    {"departure_airport": "MAD", "arrival_airport": "LIS", "departure_time_utc": "2026-10-27T18:00:00Z", "arrival_time_utc": "2026-10-27T20:00:00Z", "departure_timezone": "Europe/Madrid", "arrival_timezone": "Europe/Lisbon", "marketing_carrier_code": "IB", "operating_carrier_name": "Iberia", "flight_number": "IB2"},
                ]},
                {"carrier": "TAP", "duration_minutes": 600, "segments": [{"departure_airport": "LIS", "arrival_airport": "GRU", "departure_time_utc": "2026-11-03T12:00:00Z", "arrival_time_utc": "2026-11-03T20:00:00Z", "departure_timezone": "Europe/Lisbon", "arrival_timezone": "America/Sao_Paulo", "marketing_carrier_code": "TP", "operating_carrier_name": "TAP Air Portugal", "flight_number": "TP89"}]},
            ],
        }
        normalized = normalize_itinerary(raw, query_grid()[0])
        decision = evaluate_offer(normalized, require_booking_coherence=False)
        self.assertEqual("ELIGIBLE", decision["ELIGIBILITY_STATE"])
        self.assertEqual("Europe/Madrid", normalized["outbound"]["segments"][1]["connection_timezone"])

    def test_normalization_derives_airport_change(self):
        raw = {
            "cabin_class": "economy",
            "requires_self_transfer": False,
            "price": {"amount": 4400, "currency": "BRL", "status": "verified"},
            "legs": [{"carrier": "X", "duration_minutes": 600, "segments": [
                {"departure_airport": "GRU", "arrival_airport": "LHR", "departure_time_utc": "2026-10-27T10:00:00Z", "arrival_time_utc": "2026-10-27T17:00:00Z", "departure_timezone": "America/Sao_Paulo", "arrival_timezone": "Europe/London", "operating_carrier_name": "Example Air"},
                {"departure_airport": "LGW", "arrival_airport": "LIS", "departure_time_utc": "2026-10-27T19:00:00Z", "arrival_time_utc": "2026-10-27T21:00:00Z", "departure_timezone": "Europe/London", "arrival_timezone": "Europe/Lisbon", "operating_carrier_name": "Example Air"},
            ]}, {"carrier": "X", "duration_minutes": 600, "segments": [{"departure_airport": "LIS", "arrival_airport": "GRU", "departure_time_utc": "2026-11-03T10:00:00Z", "arrival_time_utc": "2026-11-03T20:00:00Z", "departure_timezone": "Europe/Lisbon", "arrival_timezone": "America/Sao_Paulo", "operating_carrier_name": "Example Air"}]}],
        }
        normalized = normalize_itinerary(raw, query_grid()[0])
        self.assertTrue(normalized["airport_change"])
        self.assertIn("UNPROTECTED_JOURNEY", evaluate_offer(normalized, require_booking_coherence=False)["HARD_REJECT_REASONS"])

    def test_contract_uses_documented_leg_carrier_display_name_and_timezones(self):
        raw = {"legs": [{"carrier": "TAP", "segments": [{"departure_timezone": "Europe/Lisbon", "arrival_timezone": "America/Sao_Paulo"}]}]}
        matrix = contract_matrix([raw])
        carrier = next(x for x in matrix if x["FIELD"] == "marketing_carrier_name")
        departure_tz = next(x for x in matrix if x["FIELD"] == "departure_timezone")
        self.assertEqual("LEG_CARRIER_DISPLAY", carrier["OPENAPI_EXPECTED"])
        self.assertTrue(carrier["REAL_PRESENT"])
        self.assertTrue(departure_tz["REAL_PRESENT"])

    def test_clean_adversarial_candidate_has_no_false_failures(self):
        report = verifier_fleet(offer())
        self.assertEqual(set(VERIFIER_IDS), set(report["VERIFIERS"]))
        self.assertEqual([], report["CRITICAL_FAILURES"])
        self.assertEqual("PASS", report["VERIFIERS"]["V1_TAAG_FALSE_NEGATIVE"])
        self.assertEqual("PASS", report["VERIFIERS"]["V2_AFRICA_FALSE_NEGATIVE"])
        self.assertEqual("PASS", report["VERIFIERS"]["V3_OPERATING_CARRIER"])
        self.assertEqual("NOT_APPLICABLE", report["VERIFIERS"]["V9_BOOKING_COHERENCE"])
        self.assertEqual("PASS_WITH_NOT_APPLICABLE", report["VERIFIER_FLEET_STATUS"])

    def test_adversarial_fleet_refutes_taag_and_split_booking(self):
        row = offer()
        row["outbound"]["segments"][0]["operating_carrier_name"] = "TAAG Angola Airlines"
        report = verifier_fleet(row, booking_option=booking_option([0]))
        self.assertEqual("PASS", report["VERIFIERS"]["V1_TAAG_FALSE_NEGATIVE"])
        self.assertIn("V9_BOOKING_COHERENCE", report["CRITICAL_FAILURES"])

    def test_adversarial_full_booking_coverage_passes_v9(self):
        report = verifier_fleet(offer(), booking_option=booking_option())
        self.assertEqual("PASS", report["VERIFIERS"]["V9_BOOKING_COHERENCE"])
        self.assertNotIn("V9_BOOKING_COHERENCE", report["CRITICAL_FAILURES"])

    def test_adversarial_fleet_rejects_unsanitized_public_candidate(self):
        report = verifier_fleet(offer(), public_candidate={"Authorization": "secret"})
        self.assertIn("V12_PRIVACY_SECRET", report["CRITICAL_FAILURES"])


if __name__ == "__main__":
    unittest.main()
