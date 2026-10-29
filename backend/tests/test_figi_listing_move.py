"""validate figi_change: a listing move (same composite FIGI, share class and Intrinio security, a new exchange-level FIGI) passes
quietly; any change to those stays an error (services/security_records.figi_move; Sam, 2026-10-29, Decision 2)."""
from app.services.security_records import FIGI_CHANGED, LISTING_MOVE, figi_move

PANW_STORED = dict(figi="BBG002VZ5C47", composite="BBG0014GJCT9", share_class="BBG001T9NWN5", security_id="sec_gjlw7z")
PANW_SEEN = dict(seen_figi="BBG002VZ5CL8", seen_composite="BBG0014GJCT9", seen_share_class="BBG001T9NWN5", seen_security_id="sec_gjlw7z")


def test_panw_nyse_line_to_nasdaq_line_is_a_listing_move():
    kind, detail = figi_move(**PANW_STORED, **PANW_SEEN)
    assert kind == LISTING_MOVE and "BBG0014GJCT9" in detail


def test_panw_as_stored_today_with_no_share_class_of_its_own_is_judged_by_its_composite():
    kind, _ = figi_move(**{**PANW_STORED, "share_class": None}, **PANW_SEEN)
    assert kind == LISTING_MOVE


def test_a_real_change_a_different_composite_is_an_error():                 # a new security behind the ticker (PSKY after the merger)
    kind, detail = figi_move(**PANW_STORED, **{**PANW_SEEN, "seen_composite": "BBG01SKYDNC0"})
    assert kind == FIGI_CHANGED and "composite FIGI" in detail


def test_a_different_share_class_or_security_record_is_an_error():
    assert figi_move(**PANW_STORED, **{**PANW_SEEN, "seen_share_class": "BBG00CLASSB1"})[0] == FIGI_CHANGED
    assert figi_move(**PANW_STORED, **{**PANW_SEEN, "seen_security_id": "sec_OTHER1"})[0] == FIGI_CHANGED


def test_what_cannot_be_compared_is_an_error_and_an_unchanged_figi_is_nothing():
    assert figi_move(**PANW_STORED, **{**PANW_SEEN, "seen_composite": None})[0] == FIGI_CHANGED      # not refreshed since the migration
    assert figi_move(**PANW_STORED, **{**PANW_SEEN, "seen_share_class": None})[0] == FIGI_CHANGED
    assert figi_move(**PANW_STORED, **{**PANW_SEEN, "seen_figi": "BBG002VZ5C47"}) == (None, "")
