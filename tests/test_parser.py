from typing import Any, Dict

from parser import _extract_name, _parse_date, parse_email

SAMPLE = """\
Subject: Trip Confirmation

Dear John Smith,

FLIGHT CONFIRMATION
===================
Confirmation Code: ABC123
Flight Number: UA4521
Airline: United Airlines
From: New York (JFK)
To: Los Angeles (LAX)
Departure: April 5, 2026 at 08:30 AM
Arrival: April 5, 2026 at 11:45 AM

HOTEL CONFIRMATION
==================
Booking Reference: HTL789
Hotel: Grand Hyatt Los Angeles
Check-In: 05/04/2026
Check-Out: 08/04/2026

Regards,
TravelCo Support
"""

MALFORMED = """\
flt: BA 492
departs 15/03/2026
hotel: some   INN  check in 15/03/2026
ref: XY9Z12
"""

ALT_SECTION_HEADERS = """\
Subject: Travel Plans

AIR TRAVEL
==========
Flight Number: BA492
Airline: British Airways
From: London
To: Berlin
Departure: March 15, 2026
Arrival: March 16, 2026

ACCOMMODATION DETAILS
=====================
Booking Reference: HTL789
Hotel: River Hotel Berlin
Check-In: April 1, 2026
Check-Out: April 3, 2026
"""


def test_flight_number() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert r["flight"]["flight_number"] == "UA4521"


def test_airline() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert r["flight"]["airline"] is not None
    assert "United" in r["flight"]["airline"]


def test_departure_date() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert r["flight"]["departure"] == "2026-04-05"


def test_hotel_name() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    name = r["hotel"]["name"]
    assert name is not None
    assert "Hyatt" in name or "Grand" in name


def test_check_in() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert r["hotel"]["check_in"] is not None
    assert "2026" in r["hotel"]["check_in"]


def test_check_out() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert r["hotel"]["check_out"] is not None


def test_confirmation_codes() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert "ABC123" in r["confirmation_codes"]


def test_passenger_name() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    name = r["passenger_name"]
    assert name is not None
    assert "John" in name or "Smith" in name


def test_date_written_format() -> None:
    d = _parse_date("April 5, 2026")
    assert d == "2026-04-05"


def test_date_slash_format() -> None:
    d = _parse_date("05/04/2026")
    assert d is not None


def test_minimum_four_fields() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    count = (
        sum(1 for v in r["flight"].values() if v is not None)
        + sum(1 for v in r["hotel"].values() if v is not None)
        + (1 if r["passenger_name"] else 0)
        + (1 if r["confirmation_codes"] else 0)
    )
    assert count >= 4


def test_output_json_structure() -> None:
    r: Dict[str, Any] = parse_email(SAMPLE)
    assert "flight" in r
    assert "hotel" in r
    assert "confirmation_codes" in r
    assert isinstance(r["confirmation_codes"], list)
    for key in ("airline", "flight_number", "departure", "arrival"):
        assert key in r["flight"]
    for key in ("name", "check_in", "check_out"):
        assert key in r["hotel"]


def test_malformed_no_crash() -> None:
    r: Dict[str, Any] = parse_email(MALFORMED)
    assert isinstance(r, dict)
    assert "flight" in r
    assert "hotel" in r


class _FakeEntity:
    def __init__(self, text: str, label_: str = "PERSON") -> None:
        self.text = text
        self.label_ = label_


class _FakeDoc:
    def __init__(self, *ents: _FakeEntity) -> None:
        self.ents = ents


def test_extract_name_rejects_alphanumeric_person_entity() -> None:
    assert _extract_name("ref: XY9Z12", _FakeDoc(_FakeEntity("XY9Z12"))) is None


def test_extract_name_accepts_human_like_person_entity() -> None:
    assert _extract_name("", _FakeDoc(_FakeEntity("John Smith"))) == "John Smith"


def test_extract_name_rejects_punctuation_in_person_entity() -> None:
    # Guards the NAME_RE character class against admitting bracket/operator
    # punctuation (e.g. if the hyphen were ever read as a range delimiter).
    for bad in ("John(Smith", "Jane+Doe", "A,B", "x*y", "a)b"):
        assert _extract_name("", _FakeDoc(_FakeEntity(bad))) is None
    assert _extract_name("", _FakeDoc(_FakeEntity("Mary-Jane O'Brien"))) == "Mary-Jane O'Brien"
def test_alternative_section_headers_prevent_date_bleed() -> None:
    r: Dict[str, Any] = parse_email(ALT_SECTION_HEADERS)
    assert r["flight"]["departure"].startswith("2026-03-15")
    assert r["flight"]["arrival"].startswith("2026-03-16")
    assert r["hotel"]["check_in"].startswith("2026-04-01")
    assert r["hotel"]["check_out"].startswith("2026-04-03")
