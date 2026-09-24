from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import re

from backend import rag_engine
from backend import pdf_generator
from backend.rag_engine import CancellationEngineError, Mode

app = FastAPI(title="Digital Estate Manager - Cancellation Engine")

PDF_DIR = os.path.dirname(os.path.abspath(__file__))

class PolicySummaryRequest(BaseModel):
    provider: str
    sub_type: str = "subscription"
    mode: Mode = "during_life"
    service_address: str = ""

class CancelActionRequest(BaseModel):
    provider: str
    sub_type: str = "subscription"
    person_name: str
    contract_id: str
    mode: Mode = "during_life"
    service_address: str = ""


def _safe_filename(*parts: str) -> str:
    stem = "_".join(re.sub(r"[^A-Za-z0-9-]+", "-", p).strip("-") or "none" for p in parts)
    return f"Cancellation_{stem}.pdf"


@app.post("/api/get-policy-summary")
def get_policy_summary(data: PolicySummaryRequest):
    try:
        death_policy, cancel_policy = rag_engine.search_web_cancellation_policy(
            provider_name=data.provider,
            sub_type=data.sub_type,
            mode=data.mode,
            service_address=data.service_address or None
        )
    except CancellationEngineError as e:
        raise HTTPException(status_code=504, detail=str(e))
    return {
        "mode": data.mode,
        "death_policy": death_policy.model_dump(),
        "cancel_policy": cancel_policy.model_dump()
    }

@app.post("/api/generate-cancel-docs")
def generate_cancel_docs(data: CancelActionRequest):
    try:
        death_policy, cancel_policy = rag_engine.search_web_cancellation_policy(
            provider_name=data.provider,
            sub_type=data.sub_type,
            mode=data.mode,
            service_address=data.service_address or None
        )

        letter_text = rag_engine.generate_cancellation_letter(
            provider_name=data.provider,
            sub_type=data.sub_type,
            person_name=data.person_name,
            contract_id=data.contract_id,
            mode=data.mode,
            cancel_policy=cancel_policy,
            death_policy=death_policy
        )
    except CancellationEngineError as e:
        raise HTTPException(status_code=504, detail=str(e))

    try:
        pdf_filename = _safe_filename(data.provider, data.contract_id)
        pdf_path = os.path.join(PDF_DIR, pdf_filename)

        recipient_addr = cancel_policy.action_payload.get("mailing_address") or "Kundenservice"

        pdf_generator.create_cancellation_pdf(
            sender_name=data.person_name,
            provider_name=data.provider,
            provider_address=recipient_addr,
            letter_body=letter_text,
            output_path=pdf_path
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "mode": data.mode,
        "death_policy": death_policy.model_dump(),
        "cancel_policy": cancel_policy.model_dump(),
        "letter_text": letter_text,
        "pdf_filename": pdf_filename,
        "download_url": f"/api/download-pdf/{pdf_filename}"
    }

@app.get("/api/download-pdf/{filename}")
def download_pdf(filename: str):
    pdf_path = os.path.join(PDF_DIR, os.path.basename(filename))
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(
        path=pdf_path,
        filename=os.path.basename(filename),
        media_type="application/pdf"
    )
