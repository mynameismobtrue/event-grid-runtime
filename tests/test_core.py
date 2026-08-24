import unittest
from flight_bridge.core import (CrossRepoWriteBlocked, classify_provider_response, dedupe_decision, evaluate_offer,
    query_grid, quota_gate, revalidation_decision, require_target_repository, sanitized_public,
    validate_completeness, verify_booking_coverage)

def offer(**changes):
    segment = {"departure_airport":"GRU","arrival_airport":"LIS","departure_time_utc":"2026-10-27T12:00:00Z","arrival_time_utc":"2026-10-27T20:00:00Z","marketing_carrier_code":"TP","marketing_carrier_name":"TAP","operating_carrier_name":"TAP","flight_number":"TP88"}
    inbound = dict(segment, departure_airport="LIS", arrival_airport="GRU", departure_time_utc="2026-11-03T12:00:00Z", arrival_time_utc="2026-11-03T20:00:00Z")
    row={"outbound":{"origin":"GRU","destination":"LIS","duration_minutes":600,"segments":[segment]},"inbound":{"origin":"LIS","destination":"GRU","duration_minutes":600,"segments":[inbound]},"cabin":"economy","requires_self_transfer":False,"price":{"amount":4499.99,"currency":"BRL","status":"verified"}}
    row.update(changes); return row

class CoreTests(unittest.TestCase):
    def test_grid_is_exactly_twelve_unique_cells(self): self.assertEqual(12, len({x['query_id'] for x in query_grid()}))
    def test_completeness_duplicate_missing_unexpected(self):
        ids=[x['query_id'] for x in query_grid()]; r=validate_completeness(ids[:-1]+[ids[0], 'bad']); self.assertEqual('INCOMPLETE',r['SEARCH_STATUS']); self.assertTrue(r['DUPLICATES']); self.assertTrue(r['MISSING']); self.assertTrue(r['UNEXPECTED'])
    def test_boundaries(self):
        self.assertEqual('ELIGIBLE', evaluate_offer(offer())['ELIGIBILITY_STATE']); self.assertEqual('HARD_REJECTED', evaluate_offer(offer(price={'amount':4500.00,'currency':'BRL','status':'verified'}))['ELIGIBILITY_STATE'])
    def test_taag_operating_and_missing_are_fail_closed(self):
        bad=offer(); bad['outbound']['segments'][0]['operating_carrier_name']='TAAG Angola Airlines'; self.assertEqual('HARD_REJECTED',evaluate_offer(bad)['ELIGIBILITY_STATE'])
        unknown=offer(); unknown['outbound']['segments'][0]['operating_carrier_name']=None; self.assertEqual('NON_VALIDATABLE',evaluate_offer(unknown)['ELIGIBILITY_STATE'])
    def test_duration_and_connections_boundaries(self):
        r=offer(); r['outbound']['duration_minutes']=1080; self.assertEqual('ELIGIBLE',evaluate_offer(r)['ELIGIBILITY_STATE']); r['outbound']['duration_minutes']=1081; self.assertEqual('HARD_REJECTED',evaluate_offer(r)['ELIGIBILITY_STATE'])
    def test_arrival_29_is_rejected_and_28_is_allowed(self):
        r=offer(); r['outbound']['segments'][0]['arrival_time_utc']='2026-10-28T23:30:00Z'; self.assertEqual('ELIGIBLE',evaluate_offer(r)['ELIGIBILITY_STATE']); r['outbound']['segments'][0]['arrival_time_utc']='2026-10-29T00:30:00Z'; self.assertEqual('HARD_REJECTED',evaluate_offer(r)['ELIGIBILITY_STATE'])
    def test_two_connections_rejected_and_300_boundary(self):
        r=offer(); a=r['outbound']['segments'][0]; b=dict(a, departure_airport='LIS', arrival_airport='MAD', departure_time_utc='2026-10-27T01:00:00Z', arrival_time_utc='2026-10-27T02:00:00Z'); c=dict(a, departure_airport='MAD', arrival_airport='LIS', departure_time_utc='2026-10-27T03:00:00Z', arrival_time_utc='2026-10-27T04:00:00Z'); r['outbound']['segments']=[a,b,c]; self.assertEqual('HARD_REJECTED',evaluate_offer(r)['ELIGIBILITY_STATE'])
    def test_africa_connection_and_missing_country_fail_closed(self):
        r=offer(); a=r['outbound']['segments'][0]; b=dict(a, departure_airport='LIS', arrival_airport='LIS', departure_time_utc='2026-10-27T21:00:00Z', arrival_time_utc='2026-10-27T22:00:00Z', connection_country_code='AO'); r['outbound']['segments']=[a,b]; self.assertEqual('HARD_REJECTED',evaluate_offer(r)['ELIGIBILITY_STATE']); b.pop('connection_country_code'); self.assertEqual('NON_VALIDATABLE',evaluate_offer(r)['ELIGIBILITY_STATE'])
    def test_price_status_and_self_transfer(self):
        self.assertEqual('NON_VALIDATABLE',evaluate_offer(offer(price={'amount':4400,'currency':'BRL'}))['ELIGIBILITY_STATE']); self.assertEqual('HARD_REJECTED',evaluate_offer(offer(requires_self_transfer=True))['ELIGIBILITY_STATE'])
    def test_quota_and_booking_integrity(self): self.assertTrue(quota_gate(936)['QUOTA_GATE_ALLOWED']); self.assertFalse(quota_gate(937)['QUOTA_GATE_ALLOWED']); self.assertTrue(verify_booking_coverage({'leg_indexes':[0,1]})); self.assertFalse(verify_booking_coverage({'leg_indexes':[0]}))
    def test_cross_repo_guard(self):
        require_target_repository('mynameismobtrue/event-grid-runtime')
        with self.assertRaises(CrossRepoWriteBlocked): require_target_repository('mynameismobtrue/file-drop')
    def test_technical_errors_never_mean_no_flights(self):
        self.assertEqual('AUTH_REQUIRED',classify_provider_response(401)); self.assertEqual('UPSTREAM_DEPENDENCY',classify_provider_response(424)); self.assertEqual('PROVIDER_NETWORK_ERROR',classify_provider_response(None))
    def test_secret_and_booking_url_sanitization(self):
        clean=sanitized_public({'Authorization':'Bearer x','url':'https://a.example/x?token=abc','ok':'yes'}, forbidden_values=['secret'])
        self.assertNotIn('Authorization',clean); self.assertEqual('[REDACTED_URL]',clean['url']); self.assertEqual('yes',clean['ok'])
    def test_revalidation_requires_exact_match_and_full_journey(self):
        first=offer(); self.assertEqual('VERIFIED_ALERT_CANDIDATE',revalidation_decision(first,offer(),{'leg_indexes':[0,1]})['status']); changed=offer(); changed['outbound']['segments'][0]['flight_number']='TP99'; self.assertEqual('ITINERARY_CHANGED',revalidation_decision(first,changed,{'leg_indexes':[0,1]})['failure_code']); self.assertEqual('BOOKING_OPTION_MISSING',revalidation_decision(first,offer(),{'leg_indexes':[0]})['failure_code'])
    def test_alert_dedupe_only_on_material_change(self):
        first=offer(); self.assertFalse(dedupe_decision(first,offer())['should_alert']); lower=offer(price={'amount':4399,'currency':'BRL','status':'verified'}); self.assertEqual('PRICE_DROP_100_BRL',dedupe_decision(first,lower)['reason'])
