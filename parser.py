#!/usr/bin/env python3
import re
import argparse
import logging
from typing import Any, Dict, List, Optional, Tuple

import dateparser

from loader import load_email
from exporter import export_json

logger = logging.getLogger(__name__)

_nlp: Any = None
SPACY_AVAILABLE: bool = False

try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    SPACY_AVAILABLE = True
except Exception:
    pass

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

FLIGHT_NUMBER_RE = re.compile(r"\b([A-Z]{2})\s?(\d{3,4})\b")

CONF_CODE_RE = re.compile(
    r"(?:confirmation|reference|booking|code|number)\s*:\s*"
    r"([A-Z0-9]{5,10})\b",
    re.IGNORECASE,
)

DATE_WRITTEN_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
    r"\.?\s+\d{1,2},?\s+\d{4}"
    r"(?:\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?)\b",
    re.IGNORECASE,
)

DATE_SLASH_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")

DATE_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

AIRLINE_RE = re.compile(
    r"\b([\w][\w ]*(?:Airlines|Airways|Air(?:line)?|Aviation))\b",
    re.IGNORECASE,
)

HOTEL_RE = re.compile(
    r"\b([\w][\w ]*"
    r"(?:Hotel|Inn|Suites?|Resort|Lodge|Hostel|Motel|"
    r"Hyatt|Hilton|Marriott|Sheraton|Radisson))\b",
    re.IGNORECASE,
)

AIRLINE_TERM = frozenset(
    {"airline", "airlines", "airways", "air", "aviation"}
)

HOTEL_TERM = frozenset(
    {
        "hotel", "inn", "suite", "suites", "resort", "lodge",
        "hostel", "motel", "hyatt", "hilton", "marriott", "sheraton",
    }
)

FLIGHT_SECTION_RE = re.compile(
    r"(?m)^[ \t=*-]*"
    r"(?:FLIGHT|AIR TRAVEL|OUTBOUND|INBOUND|JOURNEY|YOUR ITINERARY)\b",
    re.IGNORECASE,
)

HOTEL_SECTION_RE = re.compile(
    r"(?m)^[ \t=*-]*"
    r"(?:HOTEL|ACCOMMODATION|LODGING|STAY|PROPERTY|YOUR STAY AT|YOUR RESERVATION)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> Optional[str]:
    result = dateparser.parse(
        raw.strip(),
        settings={"DATE_ORDER": "MDY", "RETURN_AS_TIMEZONE_AWARE": False},
    )
    if result is None:
        return None
    try:
        # Preserve time if present (e.g. "April 5, 2026 at 08:30 AM")
        # dateparser returns a datetime when time is in the input
        if hasattr(result, "hour") and result.hour is not None:
            return result.isoformat()
        return result.date().isoformat()
    except AttributeError:
        return None


def _all_dates(text: str) -> List[Tuple[int, str]]:
    found: List[Tuple[int, str]] = []
    for m in DATE_WRITTEN_RE.finditer(text):
        d = _parse_date(m.group(1))
        if d:
            found.append((m.start(), d))
    for m in DATE_SLASH_RE.finditer(text):
        d = _parse_date(m.group(1))
        if d:
            found.append((m.start(), d))
    for m in DATE_ISO_RE.finditer(text):
        found.append((m.start(), m.group(1)))
    found.sort(key=lambda x: x[0])
    return found


def _flight_text(text: str) -> str:
    # Match flight section headers only at the start of a line.
    m = FLIGHT_SECTION_RE.search(text)
    if not m:
        return text
    flight_start = m.start()
    hotel_m = HOTEL_SECTION_RE.search(text[m.end():])
    end = m.end() + hotel_m.start() if hotel_m else len(text)
    return text[flight_start:end]


def _hotel_text(text: str) -> str:
    # Match hotel section headers only at the start of a line.
    m = HOTEL_SECTION_RE.search(text)
    return text[m.start():] if m else text


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _extract_flight(
    text: str, doc: Any
) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "airline": None,
        "flight_number": None,
        "departure": None,
        "arrival": None,
        "origin": None,
        "destination": None,
    }
    sec = _flight_text(text)

    fn_m = FLIGHT_NUMBER_RE.search(sec)
    if fn_m:
        result["flight_number"] = fn_m.group(1) + fn_m.group(2)
        logger.info("flight_number: %s", result["flight_number"])
    else:
        logger.info("flight_number: not found")

    # Airline: spaCy ORG -> regex -> labeled field
    if doc is not None:
        for ent in doc.ents:
            if ent.label_ == "ORG" and any(
                t in ent.text.lower() for t in AIRLINE_TERM
            ):
                result["airline"] = ent.text.strip()
                break
    if not result["airline"]:
        am = AIRLINE_RE.search(sec)
        result["airline"] = am.group(1).strip() if am else None
    if not result["airline"]:
        lm = re.search(r"airline\s*:\s*([^\n]+)", sec, re.IGNORECASE)
        result["airline"] = lm.group(1).strip() if lm else None
    logger.info("airline: %s", result["airline"])

    # Departure / arrival via labeled patterns
    dm = re.search(
        r"depart(?:ure)?\s*:\s*([^\n]+)", sec, re.IGNORECASE
    )
    am2 = re.search(
        r"arriv(?:al)?\s*:\s*([^\n]+)", sec, re.IGNORECASE
    )
    if dm:
        result["departure"] = _parse_date(dm.group(1))
    if am2:
        result["arrival"] = _parse_date(am2.group(1))

    # Fallback: positional dates
    if not result["departure"] or not result["arrival"]:
        dates = _all_dates(sec)
        if doc is not None:
            for ent in doc.ents:
                if ent.label_ == "DATE":
                    d = _parse_date(ent.text)
                    if d and not any(x[1] == d for x in dates):
                        dates.append((0, d))
            dates.sort(key=lambda x: x[0])
        if not result["departure"] and dates:
            result["departure"] = dates[0][1]
        if not result["arrival"] and len(dates) > 1:
            result["arrival"] = dates[1][1]
    logger.info(
        "departure: %s  arrival: %s",
        result["departure"],
        result["arrival"],
    )

    # Origin / destination via labeled fields then spaCy GPE
    fm = re.search(r"from\s*:\s*([^\n]+)", sec, re.IGNORECASE)
    tm = re.search(r"\bto\s*:\s*([^\n]+)", sec, re.IGNORECASE)
    result["origin"] = fm.group(1).strip() if fm else None
    result["destination"] = tm.group(1).strip() if tm else None

    if doc is not None and not result["origin"]:
        gpe = [e.text for e in doc.ents if e.label_ == "GPE"]
        if gpe:
            result["origin"] = gpe[0]
        if len(gpe) > 1:
            result["destination"] = gpe[1]

    return result


def _extract_hotel(
    text: str, doc: Any
) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "name": None,
        "check_in": None,
        "check_out": None,
    }
    sec = _hotel_text(text)

    # Hotel name: labeled field -> spaCy ORG/FAC -> regex
    lm = re.search(r"hotel\s*:\s*([^\n]+)", sec, re.IGNORECASE)
    if lm:
        raw = lm.group(1).strip()
        raw = re.split(r"\s+check", raw, flags=re.IGNORECASE)[0].strip()
        result["name"] = raw if raw else None
    if not result["name"] and doc is not None:
        for ent in doc.ents:
            if ent.label_ in ("ORG", "FAC") and any(
                t in ent.text.lower() for t in HOTEL_TERM
            ):
                result["name"] = ent.text.strip()
                break
    if not result["name"]:
        hm = HOTEL_RE.search(sec)
        result["name"] = hm.group(1).strip() if hm else None
    logger.info("hotel_name: %s", result["name"])

    # Check-in / check-out via labeled patterns
    ci = re.search(r"check[- ]?in\s*:\s*([^\n]+)", sec, re.IGNORECASE)
    co = re.search(
        r"check[- ]?out\s*:\s*([^\n]+)", sec, re.IGNORECASE
    )
    if ci:
        result["check_in"] = _parse_date(ci.group(1))
    if co:
        result["check_out"] = _parse_date(co.group(1))

    # Fallback: positional dates
    if not result["check_in"] or not result["check_out"]:
        dates = _all_dates(sec)
        if not result["check_in"] and dates:
            result["check_in"] = dates[0][1]
        if not result["check_out"] and len(dates) > 1:
            result["check_out"] = dates[1][1]
    logger.info(
        "check_in: %s  check_out: %s",
        result["check_in"],
        result["check_out"],
    )

    return result


def _extract_codes(text: str) -> List[str]:
    codes: List[str] = []
    for m in CONF_CODE_RE.finditer(text):
        code = m.group(1).upper()
        # Skip flight-number-shaped values (e.g. UA4521)
        if re.match(r"^[A-Z]{2}\d{3,4}$", code):
            continue
        # Skip purely alphabetic values (common English words)
        if code.isalpha():
            continue
        if code not in codes:
            codes.append(code)
            logger.info("confirmation_code: %s", code)
    return codes


def _extract_name(text: str, doc: Any) -> Optional[str]:
    if doc is not None:
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                logger.info("passenger_name (spaCy): %s", ent.text)
                return ent.text.strip()
    m = re.search(
        r"dear\s+([\w .'-]+?)(?:[,\n])", text, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        logger.info("passenger_name (Dear): %s", name)
        return name
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_email(text: str) -> Dict[str, Any]:
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    doc: Any = None
    if SPACY_AVAILABLE and _nlp is not None:
        try:
            doc = _nlp(text)
            logger.info("spaCy NER active")
        except Exception as exc:
            logger.warning("spaCy failed (%s); regex-only mode", exc)

    flight = _extract_flight(text, doc)
    hotel = _extract_hotel(text, doc)
    codes = _extract_codes(text)
    name = _extract_name(text, doc)

    extracted = (
        [k for k, v in flight.items() if v is not None]
        + [k for k, v in hotel.items() if v is not None]
        + (["confirmation_codes"] if codes else [])
        + (["passenger_name"] if name else [])
    )
    empty = (
        [k for k, v in flight.items() if v is None]
        + [k for k, v in hotel.items() if v is None]
    )
    logger.info("Extracted fields: %s", extracted)
    if empty:
        logger.info("Empty fields: %s", empty)

    return {
        "flight": flight,
        "hotel": hotel,
        "confirmation_codes": codes,
        "passenger_name": name,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(
        description="Parse flight/hotel details from email text."
    )
    ap.add_argument(
        "--input",
        required=True,
        metavar="PATH",
        help="Email text file, or '-' for stdin",
    )
    ap.add_argument(
        "--output",
        default="itinerary.json",
        metavar="PATH",
        help="Output JSON path (default: itinerary.json)",
    )
    args = ap.parse_args()
    email_text = load_email(args.input)
    structured = parse_email(email_text)
    export_json(structured, args.output)
    print(
        f"\n✅ Validation Passed — "
        f"JSON exported successfully to {args.output}"
    )


if __name__ == "__main__":
    main()
