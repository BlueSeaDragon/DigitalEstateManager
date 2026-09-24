from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import rag_engine
import pdf_generator
import os

app = FastAPI()

class PolicyFetchRequest(BaseModel):
    provider: str
    sub_type: str
    mode: str = "during_life"

class CancelActionRequest(BaseModel):
    provider: str
    sub_type: str
    person_name: str
    contract_id: str
    mode: str = "during_life"

@app.post("/api/get-policy-summary")
def get_policy_summary(data: PolicyFetchRequest):
    """Called to populate UI dropdown with bullet points & direct links."""
    return rag_engine.search_web_cancellation_policy(
        provider_name=data.provider,
        sub_type=data.sub_type,
        mode=data.mode
    )

@app.post("/api/generate-cancel-docs")
def generate_cancel_docs(data: CancelActionRequest):
    """Called when user clicks 'Help Me Cancel'. Generates letter + PDF."""
    policy_info = rag_engine.search_web_cancellation_policy(data.provider, data.sub_type, data.mode)
    
    letter_text = rag_engine.generate_cancellation_letter(
        data.provider, data.sub_type, data.person_name, data.contract_id, data.mode, policy_info
    )
    
    pdf_filename = f"Cancellation_{data.provider}_{data.contract_id}.pdf"
    pdf_path = os.path.join("backend", pdf_filename)
    
    pdf_generator.create_cancellation_pdf(
        sender_name=data.person_name,
        provider_name=data.provider,
        provider_address=policy_info.get("recipient_address", "Provider Contact Center"),
        letter_body=letter_text,
        output_path=pdf_path
    )
    
    return {
        "letter_text": letter_text,
        "direct_links": policy_info.get("direct_links", []),
        "pdf_filename": pdf_filename
    }
