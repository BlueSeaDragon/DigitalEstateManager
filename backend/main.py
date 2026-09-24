from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import os

from backend import rag_engine
from backend import pdf_generator

app = FastAPI(title="Digital Estate Manager - Cancellation Engine")

class PolicySummaryRequest(BaseModel):
    provider: str
    sub_type: str = "subscription"
    mode: str = "during_life"

class CancelActionRequest(BaseModel):
    provider: str
    sub_type: str = "subscription"
    person_name: str
    contract_id: str
    mode: str = "during_life"

@app.post("/api/get-policy-summary")
def get_policy_summary(data: PolicySummaryRequest):
    try:
        return rag_engine.search_web_cancellation_policy(
            provider_name=data.provider,
            sub_type=data.sub_type,
            mode=data.mode
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-cancel-docs")
def generate_cancel_docs(data: CancelActionRequest):
    try:
        policy_info = rag_engine.search_web_cancellation_policy(
            provider_name=data.provider,
            sub_type=data.sub_type,
            mode=data.mode
        )
        
        letter_text = rag_engine.generate_cancellation_letter(
            provider_name=data.provider,
            sub_type=data.sub_type,
            person_name=data.person_name,
            contract_id=data.contract_id,
            mode=data.mode,
            policy_info=policy_info
        )
        
        pdf_filename = f"Cancellation_{data.provider}_{data.contract_id}.pdf"
        pdf_path = os.path.join("backend", pdf_filename)
        
        pdf_generator.create_cancellation_pdf(
            sender_name=data.person_name,
            provider_name=data.provider,
            provider_address=policy_info.get("recipient_address", "Customer Support"),
            letter_body=letter_text,
            output_path=pdf_path
        )
        
        return {
            "letter_text": letter_text,
            "direct_links": policy_info.get("direct_links", []),
            "pdf_filename": pdf_filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
