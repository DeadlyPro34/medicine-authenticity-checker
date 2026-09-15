"""
OCR Agent
---------
Takes a photo of a medicine strip/box and extracts structured fields
(drug name, manufacturer, batch number, mfg date, expiry date) using
Groq's vision model. Vision LLM is used instead of classic OCR
(Tesseract) because strip/box text is often small, glossy, or at an angle -
a reasoning model handles that far more reliably than raw OCR.

Requires: GROQ_API_KEY environment variable.
"""

import base64
import json
import os
import re
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Groq's currently supported vision model (check console.groq.com/docs/vision
# if this ever gets deprecated - Groq rotates vision model names periodically)
VISION_MODEL = "qwen/qwen3.8-27b"

EXTRACTION_PROMPT = """You are looking at a photo of a medicine strip or box.

Many packs stamp several values (Batch No., Mfg. Date, Expiry Date, MRP) as
a column of numbers in a separate box, positioned next to a column of
PRINTED labels ("Batch No.", "Mfg. Date", "Expiry Date", "MRP"). When you
see this layout: match each stamped value to its label by ROW POSITION
(the value on the same horizontal line as a label belongs to that label) -
do NOT guess which number is the expiry date just because it looks like a
plausible date. The label tells you which value is which, not the value's
appearance. Read the label text first, then read the value stamped directly
across from it on the same row.

Read dates VERY carefully - stamped/inkjet dates on medicine packs are small
and easy to misread digit-by-digit. Read each digit one at a time instead of
guessing from a glance, especially digits that look similar when stamped
(3 vs 8, 0 vs 6, 5 vs 6, 1 vs 7).

Self-check before answering: the expiry date must always be LATER than the
manufacturing date, usually by 1-3 years. If your first reading gives an
expiry date that is not clearly after the manufacturing date, re-check
BOTH which row you matched to which label AND the digits themselves - you
likely mismatched a row or misread a digit.

Extract the following fields as strict JSON, with no markdown fences and no
extra commentary. If a field is not visible/legible, set it to null.

{
  "drug_name": string or null,
  "manufacturer": string or null,
  "batch_number": string or null,
  "manufacturing_date": "YYYY-MM" or null,
  "expiry_date": "YYYY-MM" or null,
  "mrp": string or null,
  "ocr_confidence": "high" | "medium" | "low",
  "date_confidence": "high" | "medium" | "low"
}

Set ocr_confidence based on how clearly the text was visible in the image
overall. Set date_confidence specifically for the manufacturing/expiry
dates - lower it if the digits were stamped, smudged, at an angle, if you
had to guess between similar-looking digits, or if the label-to-value row
alignment was unclear.
Respond with ONLY the JSON object.
"""


DATE_VERIFY_PROMPT = """Look ONLY at the manufacturing and expiry date stamp
on this medicine pack. Ignore every other piece of text on the packaging.

Two common layouts:
(a) A single line like "MFG.MMM.YYYY  EXP.MMM.YYYY" printed together, or
(b) A column of PRINTED labels ("Batch No.", "Mfg. Date", "Expiry Date",
    "MRP") next to a separate stamped column of values - in this case,
    match each value to the label on the SAME horizontal row. Do not guess
    which value is the expiry date by how it looks - use the row position
    relative to the "Mfg. Date" and "Expiry Date" labels.

Read the digits one character at a time - stamped fonts are frequently
misread (3 vs 8, 0 vs 6, 5 vs 6, 1 vs 7, 2 vs 7). Report exactly what you
see, even if you already have a hunch about what it "should" be.

Respond with STRICT JSON only, no markdown fences, no commentary:

{
  "manufacturing_date": "YYYY-MM" or null,
  "expiry_date": "YYYY-MM" or null
}
"""


def _load_image_as_data_uri(image_path: str) -> str:
    """Returns a base64 data: URI for a local image file."""
    ext = image_path.lower().rsplit(".", 1)[-1]
    media_type = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return f"data:{media_type};base64,{data}"


def _extract_json_from_raw(raw_text: str) -> dict | None:
    """Strip Qwen <think> tags, markdown fences, and extract JSON."""
    # Strip <think>...</think> blocks (Qwen reasoning model artifact)
    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    # Try to find a JSON object in the remaining text
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _call_vision_model(image_data_uri: str, prompt: str, retries: int = 1) -> dict | None:
    """Call Groq vision model with retry on JSON parse failure."""
    for attempt in range(1 + retries):
        try:
            response = client.chat.completions.create(
                model=VISION_MODEL,
                max_tokens=300,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data_uri}},
                        ],
                    }
                ],
            )
            raw_text = response.choices[0].message.content.strip()
            result = _extract_json_from_raw(raw_text)
            if result is not None:
                return result
        except Exception:
            if attempt == retries:
                return None
    return None


def _verify_dates(image_data_uri: str, first_pass: dict) -> None:
    """
    Re-reads just the date stamp in a second, narrowly-focused call and
    cross-checks it against the first extraction. Mutates first_pass in
    place: if the two readings disagree, downgrades date_confidence to
    "low" and records both readings - this is what lets the compliance
    agent avoid confidently claiming "expired" off a single misread digit.
    """
    mfg = first_pass.get("manufacturing_date")
    exp = first_pass.get("expiry_date")
    if not mfg and not exp:
        return  # nothing to verify

    second_pass = _call_vision_model(image_data_uri, DATE_VERIFY_PROMPT)
    if not second_pass:
        return  # verification call failed to parse - leave first_pass as-is

    mfg_agrees = (not mfg) or (not second_pass.get("manufacturing_date")) or (mfg == second_pass.get("manufacturing_date"))
    exp_agrees = (not exp) or (not second_pass.get("expiry_date")) or (exp == second_pass.get("expiry_date"))

    if not (mfg_agrees and exp_agrees):
        first_pass["date_confidence"] = "low"
        first_pass["_date_verification"] = {
            "first_read": {"manufacturing_date": mfg, "expiry_date": exp},
            "second_read": second_pass,
            "note": "Two independent reads of the date stamp disagreed - treat with caution.",
        }


def extract_medicine_info(image_path: str) -> dict:
    """
    Runs the OCR agent on a medicine strip/box image, then re-verifies the
    date fields with a second, narrowly-focused pass before returning.
    """
    image_data_uri = _load_image_as_data_uri(image_path)
    result = _call_vision_model(image_data_uri, EXTRACTION_PROMPT)

    if result is None:
        return {
            "drug_name": None,
            "manufacturer": None,
            "batch_number": None,
            "manufacturing_date": None,
            "expiry_date": None,
            "mrp": None,
            "ocr_confidence": "low",
            "date_confidence": "low",
        }

    _verify_dates(image_data_uri, result)
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python ocr_agent.py <path_to_image>")
        sys.exit(1)

    result = extract_medicine_info(sys.argv[1])
    print(json.dumps(result, indent=2))
