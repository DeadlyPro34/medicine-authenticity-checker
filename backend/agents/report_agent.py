"""
Report Agent
------------
Combines OCR extraction + compliance checks + visual forensics into one
final verdict. This agent has two audiences:

1. A real user checking their own medicine - they get a plain-language
   headline verdict and a short list of findings in everyday words. No
   similarity scores, no regex, no JSON.
2. A judge/developer inspecting how the system reasoned - the full
   technical detail (fuzzy-match scores, regex patterns, per-agent output)
   is still available under "details" for the raw-output toggle in the UI.
"""

RISK_LEVELS = ("Safe", "Caution", "High Risk")

# batch_format checks lean on placeholder regex patterns (see manufacturers.csv
# notes) - not reliable enough to show a real user as a finding, but still
# folded into the score at a low weight and kept in the raw technical detail.
_SCORE_WEIGHTS = {"expiry": 45, "manufacturer": 40, "batch_format": 15}


def _compliance_penalty(compliance: dict) -> int:
    """Turns compliance check statuses into a 0-100 penalty score."""
    penalty = 0
    for check_name, weight in _SCORE_WEIGHTS.items():
        status = compliance.get(check_name, {}).get("status", "unknown")
        if status == "fail":
            penalty += weight
        elif status == "warn":
            penalty += weight * 0.6
        elif status == "unknown":
            penalty += weight * 0.2  # small penalty for not being able to verify at all
    return min(int(penalty), 100)


def _build_verdict(risk_level: str, compliance: dict) -> dict:
    """
    One short, plain-language headline + a slightly longer explanation -
    what a real user actually needs to decide what to do next.
    """
    expiry_status = compliance.get("expiry", {}).get("status")
    manufacturer_status = compliance.get("manufacturer", {}).get("status")

    if risk_level == "Safe":
        return {
            "headline": "This looks genuine and safe to use.",
            "detail": "No major issues were found with the packaging, manufacturer, or expiry date.",
            "icon": "safe",
        }

    if expiry_status == "fail":
        return {
            "headline": "This medicine has expired - don't use it.",
            "detail": "Everything else about the packaging looks consistent, but the expiry date has passed. Dispose of it safely and get a fresh pack.",
            "icon": "caution",
        }

    if expiry_status == "warn":
        return {
            "headline": "The expiry date was hard to read clearly.",
            "detail": "It may be expired, but the printed date wasn't fully legible in the photo. Please check the date on the pack directly before using it.",
            "icon": "caution",
        }

    if risk_level == "High Risk":
        return {
            "headline": "Several signs suggest this may not be genuine.",
            "detail": "Please don't use this medicine. Check with your pharmacist, or contact the manufacturer using the details on the pack.",
            "icon": "risk",
        }

    if manufacturer_status == "warn":
        return {
            "headline": "We couldn't confirm the manufacturer.",
            "detail": "This doesn't mean it's fake - our manufacturer list is limited. To be safe, ask your pharmacist to double-check it.",
            "icon": "caution",
        }

    return {
        "headline": "A few things need a closer look.",
        "detail": "See the findings below, and check with your pharmacist if anything looks unclear.",
        "icon": "caution",
    }


def _build_plain_flags(compliance: dict, forensics: dict) -> list[str]:
    """
    Everyday-language findings for a real user. Deliberately leaves out
    batch_format (too unreliable to show as a claim) and raw similarity
    scores/regex - those stay in the technical `details` block only.
    """
    flags = []

    expiry = compliance.get("expiry", {})
    if expiry.get("status") == "fail":
        flags.append("This medicine's expiry date has passed.")
    elif expiry.get("status") == "warn":
        flags.append("The expiry date was hard to read clearly - please verify it directly on the pack.")
    elif expiry.get("status") == "unknown":
        flags.append("We couldn't clearly read an expiry date on this pack.")

    manufacturer = compliance.get("manufacturer", {})
    if manufacturer.get("status") == "warn":
        flags.append("The manufacturer isn't in our verified list yet - not necessarily fake, just unconfirmed.")
    elif manufacturer.get("status") == "unknown":
        flags.append("We couldn't clearly read the manufacturer's name on this pack.")

    # Visual forensics anomalies are already written in plain-ish language
    # by the forensics agent's prompt, so pass them through as-is.
    flags.extend(forensics.get("anomalies_found", []))

    return flags


def _build_about(drug_info: dict | None) -> dict | None:
    """
    Turns the drug_info_agent's output into a UI-ready block. Always
    includes a disclaimer - this is general public information, never
    personal medical advice.
    """
    if not drug_info or not drug_info.get("recognized") or not drug_info.get("general_use"):
        return None

    return {
        "general_use": drug_info["general_use"],
        "disclaimer": "General information only - not medical advice. Always follow your doctor's or pharmacist's instructions.",
    }


def generate_report(extracted_data: dict, compliance: dict, forensics: dict, drug_info: dict | None = None) -> dict:
    compliance_score = _compliance_penalty(compliance)
    visual_score = forensics.get("visual_risk_score", 0)

    # Weighted blend: compliance checks are the stronger signal, visuals support it
    combined_score = round(0.65 * compliance_score + 0.35 * visual_score)

    if combined_score >= 60:
        risk_level = "High Risk"
    elif combined_score >= 25:
        risk_level = "Caution"
    else:
        risk_level = "Safe"

    verdict = _build_verdict(risk_level, compliance)
    plain_flags = _build_plain_flags(compliance, forensics)
    about = _build_about(drug_info)

    return {
        "drug_name": extracted_data.get("drug_name"),
        "manufacturer": extracted_data.get("manufacturer"),
        "risk_level": risk_level,
        "risk_score": combined_score,
        "verdict": verdict,
        "flags": plain_flags,
        "about": about,
        "ocr_confidence": extracted_data.get("ocr_confidence", "unknown"),
        "details": {
            "compliance": compliance,
            "visual_forensics": forensics,
        },
    }


if __name__ == "__main__":
    import json

    sample_extracted = {"drug_name": "Paracetamol", "manufacturer": "Cipla Ltd", "ocr_confidence": "high"}
    sample_compliance = {
        "expiry": {"status": "pass", "detail": "Valid until 2027-05."},
        "manufacturer": {"status": "pass", "detail": "Matched Cipla.", "match": "Cipla"},
        "batch_format": {"status": "warn", "detail": "Batch format mismatch."},
    }
    sample_forensics = {"anomalies_found": ["Slightly blurry print"], "visual_risk_score": 20}

    print(json.dumps(generate_report(sample_extracted, sample_compliance, sample_forensics), indent=2))
