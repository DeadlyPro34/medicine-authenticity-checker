"""
Visual Forensics Agent
----------------------
Independent of the OCR text extraction, this agent looks at the SAME image
purely for visual/print-quality red flags that are common in counterfeit
packaging: blurry or misaligned printing, inconsistent fonts, spelling
errors, low-quality holograms/seals, mismatched color printing, etc.

Kept separate from ocr_agent.py on purpose - different prompt, different
job. The report agent combines both signals.

Requires: GROQ_API_KEY environment variable.
"""

import base64
import json
import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

VISION_MODEL = "qwen/qwen3.8-27b"

FORENSICS_PROMPT = """You are a packaging-forensics inspector. Look ONLY at
visual print quality and packaging cues in this medicine strip/box photo -
ignore whether you can identify the drug or not.

IMPORTANT CONTEXT: On virtually all genuine medicine packaging, the batch
number and expiry date are inkjet-stamped SEPARATELY from the main
offset-printed label (different ink, different process, added later in
manufacturing). This is completely normal and expected - do NOT flag it as
an anomaly by itself. Only flag the batch/expiry stamping if it shows
ADDITIONAL problems beyond just "being separate": e.g. smudged past
legibility, wrong/inconsistent font from what similar genuine packs use,
visibly crooked or bleeding ink, or printed over other text.

Check for common counterfeit indicators:
- Blurry, smudged, or misaligned printing on the MAIN label (not the
  routine batch/expiry stamp)
- Inconsistent fonts or font sizes within the same label
- Spelling errors or unusual phrasing
- Low-quality or missing holograms/security seals
- Color printing that looks off (too saturated, wrong shade, banding)
- Batch/expiry stamping that is illegible, bleeding, or visibly botched -
  not just "separate from the main print", which is normal

Respond with STRICT JSON only, no markdown fences, no extra commentary:

{
  "anomalies_found": [list of short strings describing each issue, empty list if none],
  "visual_risk_score": integer 0-100 (0 = looks completely normal, 100 = strongly suspicious),
  "reasoning": "one or two sentence summary"
}
"""


def _load_image_as_data_uri(image_path: str) -> str:
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


def analyze_packaging(image_path: str) -> dict:
    image_data_uri = _load_image_as_data_uri(image_path)

    response = client.chat.completions.create(
        model=VISION_MODEL,
        max_tokens=500,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": FORENSICS_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            }
        ],
    )

    raw_text = response.choices[0].message.content.strip()

    # Robust JSON extraction — handles Qwen thinking tags and markdown fences
    import re as _re
    text = _re.sub(r"<think>.*?</think>", "", raw_text, flags=_re.DOTALL).strip()
    fence_match = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    brace_match = _re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, _re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "anomalies_found": [],
            "visual_risk_score": 0,
            "reasoning": "Could not parse forensics model response.",
            "_raw_response": raw_text,
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python visual_forensics_agent.py <path_to_image>")
        sys.exit(1)

    result = analyze_packaging(sys.argv[1])
    print(json.dumps(result, indent=2))
