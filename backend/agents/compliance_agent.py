"""
Compliance Agent
-----------------
Runs rule-based checks against the fields the OCR agent extracted:
1. Expiry check          - is the medicine already expired?
2. Manufacturer check    - fuzzy-match against known manufacturers.csv
3. Batch format check    - does the batch number match that manufacturer's
                            known pattern? (patterns in manufacturers.csv are
                            DEMO placeholders - replace with verified formats
                            before treating this as production-grade.)
"""

import re
import csv
import os
from datetime import datetime
from difflib import SequenceMatcher

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "manufacturers.csv")

FUZZY_MATCH_THRESHOLD = 0.72  # below this, treat manufacturer as "unknown"


def _load_manufacturers() -> list[dict]:
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _candidate_names(manufacturer_record: dict) -> list[str]:
    """
    Registered corporate name + any aliases (subsidiary names, brand names,
    common short forms) that might appear printed on actual packaging instead
    of the formal registered name.
    """
    names = [manufacturer_record["name"]]
    aliases = manufacturer_record.get("aliases", "")
    if aliases:
        names.extend(a.strip() for a in aliases.split("|") if a.strip())
    return names


def _best_manufacturer_match(name: str, manufacturers: list[dict]) -> tuple[dict | None, float]:
    """
    Compares the OCR'd manufacturer name against every known manufacturer's
    registered name AND its aliases. An exact or substring match against any
    alias is treated as high-confidence (0.9+) even if the fuzzy string
    ratio against the *registered* name is low - this is exactly the
    "Alkem Health Science" vs "Alkem Laboratories" situation where the name
    printed on the strip is a subsidiary/brand name, not the corporate name.
    """
    if not name:
        return None, 0.0

    name_norm = name.lower().strip()
    best, best_score = None, 0.0

    for m in manufacturers:
        for candidate in _candidate_names(m):
            candidate_norm = candidate.lower().strip()
            score = _similarity(name_norm, candidate_norm)

            # Substring containment (either direction) means the OCR'd name
            # is very likely referring to this manufacturer, even if the
            # exact wording/suffix differs (Ltd vs Limited vs Health Science).
            if candidate_norm in name_norm or name_norm in candidate_norm:
                score = max(score, 0.9)

            if score > best_score:
                best, best_score = m, score

    return best, best_score


def _check_expiry(expiry_str: str | None, mfg_str: str | None, date_confidence: str | None) -> dict:
    if not expiry_str:
        return {"status": "unknown", "detail": "Expiry date not legible in image."}
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m")
    except ValueError:
        return {"status": "unknown", "detail": f"Could not parse expiry date '{expiry_str}'."}

    # Sanity check: expiry should always be after manufacturing date. If it
    # isn't, the OCR almost certainly misread a digit (common with small
    # stamped/inkjet dates) rather than the medicine genuinely being invalid -
    # treat as unverifiable rather than confidently claiming "expired".
    if mfg_str:
        try:
            mfg_date = datetime.strptime(mfg_str, "%Y-%m")
            if mfg_date >= expiry_date:
                return {
                    "status": "unknown",
                    "detail": f"Read manufacturing date ({mfg_str}) and expiry date ({expiry_str}) "
                              f"don't make sense together - likely a misread digit. Please check the "
                              f"date on the pack directly.",
                }
        except ValueError:
            pass

    now = datetime.now()
    if expiry_date < now:
        # Low date-reading confidence + a "just expired" result is exactly
        # the misread-digit failure mode - soften to a warning instead of a
        # confident fail so we don't wrongly tell someone to throw out a
        # perfectly good medicine.
        if date_confidence == "low":
            return {
                "status": "warn",
                "detail": f"Possibly expired ({expiry_str}), but the date was hard to read clearly - "
                          f"please verify the printed date directly before discarding.",
            }
        return {"status": "fail", "detail": f"Expired on {expiry_str}."}
    return {"status": "pass", "detail": f"Valid until {expiry_str}."}


def _check_manufacturer(manufacturer_name: str | None) -> dict:
    manufacturers = _load_manufacturers()
    match, score = _best_manufacturer_match(manufacturer_name or "", manufacturers)

    if not manufacturer_name:
        return {"status": "unknown", "detail": "Manufacturer name not legible in image.", "match": None}

    if score >= FUZZY_MATCH_THRESHOLD:
        return {
            "status": "pass",
            "detail": f"Matched known manufacturer '{match['name']}' (similarity {score:.2f}).",
            "match": match["name"],
        }

    return {
        "status": "warn",
        "detail": f"'{manufacturer_name}' did not closely match any known manufacturer "
                  f"(best guess: '{match['name'] if match else 'none'}', similarity {score:.2f}).",
        "match": None,
    }


def _check_batch_format(batch_number: str | None, manufacturer_match: dict | None) -> dict:
    if not batch_number:
        return {"status": "unknown", "detail": "Batch number not legible in image."}

    if not manufacturer_match or not manufacturer_match.get("match"):
        return {"status": "unknown", "detail": "Cannot validate batch format without a confirmed manufacturer."}

    manufacturers = _load_manufacturers()
    record = next((m for m in manufacturers if m["name"] == manufacturer_match["match"]), None)
    if not record:
        return {"status": "unknown", "detail": "No batch pattern on file for this manufacturer."}

    pattern = record["batch_pattern"]
    if re.match(pattern, batch_number.strip().upper()):
        return {"status": "pass", "detail": f"Batch number matches expected format for {record['name']}."}

    return {
        "status": "warn",
        "detail": f"Batch number '{batch_number}' does NOT match the typical format "
                  f"for {record['name']} (expected pattern: {pattern}).",
    }


def check_compliance(extracted_data: dict) -> dict:
    """
    Input: the dict produced by ocr_agent.extract_medicine_info()
    Output: dict with per-check status ('pass' | 'warn' | 'fail' | 'unknown')
    """
    expiry_result = _check_expiry(
        extracted_data.get("expiry_date"),
        extracted_data.get("manufacturing_date"),
        extracted_data.get("date_confidence"),
    )
    manufacturer_result = _check_manufacturer(extracted_data.get("manufacturer"))
    batch_result = _check_batch_format(extracted_data.get("batch_number"), manufacturer_result)

    return {
        "expiry": expiry_result,
        "manufacturer": manufacturer_result,
        "batch_format": batch_result,
    }


if __name__ == "__main__":
    sample = {
        "manufacturer": "Cipla Ltd",
        "batch_number": "C12345",
        "manufacturing_date": "2025-05",
        "expiry_date": "2027-05",
        "date_confidence": "high",
    }
    import json
    print(json.dumps(check_compliance(sample), indent=2))
