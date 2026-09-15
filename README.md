# Medicine Authenticity Checker Agent

Multi-agent system that inspects a photo of a medicine strip/box and flags
possible counterfeit or expired stock.

## Architecture

```
Photo upload
     |
     v
[OCR Agent] --------> extracts drug name, manufacturer, batch no, expiry
     |
     v
[Compliance Agent] --> checks expiry validity, manufacturer legitimacy,
     |                  batch number format
     v
[Visual Forensics Agent] --> independently inspects the SAME photo for
     |                        print-quality / packaging anomalies
     v
[Report Agent] --------> combines everything into one risk verdict
                          (Safe / Caution / High Risk)
```

## Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

export GROQ_API_KEY=your_key_here   # Windows PowerShell: $env:GROQ_API_KEY="your_key_here"
# Get a free key at https://console.groq.com/keys

uvicorn main:app --reload
```

Then POST an image to `http://localhost:8000/verify` (field name: `image`),
e.g. with curl:

```bash
curl -X POST -F "image=@sample_strip.jpg" http://localhost:8000/verify
```

Or test each agent individually from the command line:

```bash
python agents/ocr_agent.py path/to/photo.jpg
python agents/visual_forensics_agent.py path/to/photo.jpg
```

## IMPORTANT — before you demo this

1. **`backend/data/manufacturers.csv` batch-format patterns are placeholders
   I made up for demo purposes.** Real manufacturer batch-numbering formats
   aren't publicly documented in one clean place. Before your demo, either:
   - Clearly label this as "simulated compliance database" in your pitch, OR
   - Spend an evening collecting a few real batch-number examples per
     manufacturer (photos of real strips you have at home) and correct the
     regex patterns to match reality.
   Judges will respect honesty about this far more than a confident claim
   that turns out to be fabricated data.

2. **Add a frontend.** This repo is backend-only. A simple Next.js or even
   a single HTML page with a file input + fetch() call to `/verify` is
   enough for a hackathon demo - don't over-invest here.

3. **Test with real photos early.** Vision-LLM OCR accuracy on small,
   glossy strip text varies a lot with lighting/angle. Take your test
   photos in good light, straight-on, in week 1 - don't wait until the
   night before submission to discover the OCR struggles with foil strips.

## Suggested next steps (in priority order)

- [ ] Build minimal frontend (upload + result display)
- [ ] Test OCR agent on 10+ real medicine photos, tune the prompt
- [ ] Replace placeholder batch patterns with a few verified real ones
- [ ] Record demo video showing: upload -> agent reasoning -> verdict
- [ ] Write up problem/solution doc for submission
