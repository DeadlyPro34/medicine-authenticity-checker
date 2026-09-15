"""
FastAPI Orchestrator
---------------------
Single endpoint that runs all four agents in sequence:
  1. ocr_agent            -> structured data from the image
  2. compliance_agent     -> expiry / manufacturer / batch checks
  3. visual_forensics_agent -> packaging anomaly detection
  4. report_agent         -> final combined verdict

Run with:  uvicorn main:app --reload
Requires:  ANTHROPIC_API_KEY set in your environment
"""

import os
import shutil
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env before importing agents
load_dotenv()

from agents.ocr_agent import extract_medicine_info
from agents.compliance_agent import check_compliance
from agents.visual_forensics_agent import analyze_packaging
from agents.drug_info_agent import get_drug_info
from agents.report_agent import generate_report

app = FastAPI(title="Medicine Authenticity Checker Agent")

# Loosen CORS for hackathon demo purposes - tighten before any real deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "medicine-authenticity-checker"}


@app.post("/verify")
async def verify_medicine(image: UploadFile = File(...)):
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    suffix = os.path.splitext(image.filename)[-1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(image.file, tmp)
        tmp_path = tmp.name

    try:
        extracted = extract_medicine_info(tmp_path)
        compliance = check_compliance(extracted)
        forensics = analyze_packaging(tmp_path)
        drug_info = get_drug_info(extracted.get("drug_name"))
        report = generate_report(extracted, compliance, forensics, drug_info)
        return report
    finally:
        os.remove(tmp_path)
