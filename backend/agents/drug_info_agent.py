"""
Drug Info Agent
---------------
Given the drug name the OCR agent extracted, returns a short, plain-language
note on what this medicine is generally used for - the same kind of general
knowledge you'd find on a pack insert or a pharmacist would tell you in
passing. This is explicitly NOT medical advice: no dosage guidance, no
"you should take this for X", no diagnosis. Always paired with a disclaimer
in the UI.

Uses a fast text-only model (not vision) since it only needs the drug name
string, not the image.

Requires: GROQ_API_KEY environment variable.
"""

import json
import os
import re
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

TEXT_MODEL = "qwen/qwen3.8-27b"

INFO_PROMPT_TEMPLATE = """A user scanned a medicine pack and the text
"{drug_name}" was read off the packaging (this may be a brand name, a
generic/salt name, or both together).

If you recognize this as a real medicine (including Ayurvedic, homeopathic, or herbal supplements), give a short, general, PUBLIC-
KNOWLEDGE description of what it's commonly used for.

If you don't recognize the exact brand but it sounds like an Ayurvedic or herbal medicine, provide a generic description (e.g., "Ayurvedic herbal supplement used for general wellness").

If it is completely garbled and definitely not a medicine, set recognized to false.

Respond with STRICT JSON only, no markdown fences, no extra commentary:

{{
  "recognized": true or false,
  "general_use": "one or two plain sentences on what it's commonly used for, or null if not recognized"
}}
"""


def get_drug_info(drug_name: str | None) -> dict | None:
    """
    Returns {"recognized": bool, "general_use": str|None} or None if there
    was no drug name to look up at all.
    """
    if not drug_name or not drug_name.strip():
        return None

    prompt = INFO_PROMPT_TEMPLATE.format(drug_name=drug_name.strip())

    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None  # never let this optional feature break the main verify flow

    raw_text = response.choices[0].message.content.strip()

    # Strip <think> tags (Qwen-style reasoning traces)
    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

    # Strip markdown fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    # Try regex JSON extraction first
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "Paracetamol"
    print(json.dumps(get_drug_info(name), indent=2))
