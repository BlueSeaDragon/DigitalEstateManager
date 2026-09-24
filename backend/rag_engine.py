import os
import json
import time
import random
from openai import OpenAI
from fastapi import HTTPException

SWISSCOM_BASE_URL = os.getenv("SWISSCOM_BASE_URL", "https://api.swisscom.com/products/swiss-ai-weeks/apertus-1.5-70b/v1")
SWISSCOM_API_KEY = os.getenv("SWISSCOM_API_KEY", "")

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

client = OpenAI(
    base_url=SWISSCOM_BASE_URL,
    api_key=SWISSCOM_API_KEY,
    timeout=20.0
)

APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"

def fetch_web_results_safe(query: str, max_retries: int = 4) -> list:
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                if results:
                    return [f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}" for r in results]
        except Exception:
            pass
        delay = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.4)
        time.sleep(delay)
    return []

def search_web_cancellation_policy(provider_name: str, sub_type: str = "subscription", mode: str = "during_life") -> dict:
    if mode == "after_death":
        query = f"{provider_name} Todesfall Abo Kündigung Rückerstattung Todesurkunde Schweiz"
    else:
        query = f"{provider_name} {sub_type} Kündigung Mindestlaufzeit Schweiz Abo"
    
    search_results = fetch_web_results_safe(query)
    context_str = "\n\n".join(search_results) if search_results else f"Rely on official Swiss facts specifically for {provider_name}."
    
    system_prompt = f"You are a Swiss legal and estate assistant analyzing cancellation policies strictly for '{provider_name}'. Output valid JSON only."
    
    user_prompt = f"""
    Context: {context_str}
    Target Provider: {provider_name}
    Provided Sub-Type: {sub_type}
    Mode: {mode}
    
    STRICT COMPLIANCE RULES:
    1. NEVER mention or introduce third-party URLs/emails for unrelated companies.
    2. If Mode is 'after_death':
       - Under Swiss Law (OR Art. 405), contracts terminate immediately upon death. Minimum contract duration and notice periods DO NOT apply. Set 'notice_period' and 'minimum_contract_duration' to "Immediate (upon notification of death)".
       - List official required documents in 'required_docs' (MUST include "Todesurkunde" / Death Certificate and optional "Erbenschein").
       - Detail step-by-step estate cancellation procedures in 'channel_instructions' (e.g., submitting death certificate to customer service or SwissPass care service for pro-rata refund).
    3. If Mode is 'during_life':
       - Provide standard notice periods and minimum contract terms.

    Return JSON format:
    - minimum_contract_duration: string
    - notice_period: string
    - primary_channel: string MUST BE ONE OF ["web_portal", "email", "registered_letter", "app_store", "phone_call"]
    - requires_sub_type_selection: boolean
    - sub_type_options: list of strings
    - channel_instructions: list of specific step-by-step instructions for {provider_name}
    - portal_url: string
    - contact_email: string
    - contact_phone: string
    - mailing_address: string
    - required_docs: list of strings
    - has_mourning_portal: boolean
    - mourning_portal_url: string
    """
    
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            response = client.chat.completions.create(
                model=APERTUS_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            
            payload_str = json.dumps(data).lower()
            if "nonstopgym" in payload_str and "nonstop" not in provider_name.lower():
                time.sleep(1.0)
                continue
                
            return data

        except Exception as e:
            if attempt == max_attempts - 1:
                raise HTTPException(
                    status_code=504,
                    detail=f"Swisscom Apertus API failure. Details: {str(e)}"
                )
            
            delay = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.5)
            time.sleep(delay)

def generate_cancellation_letter(provider_name: str, sub_type: str, person_name: str, contract_id: str, mode: str, policy_info: dict) -> str:
    system_prompt = "You write formal legal cancellation letters under Swiss Law."
    
    user_prompt = f"""
    Write the BODY of a formal German cancellation letter.
    Sender: {person_name}
    Contract ID: {contract_id}
    Provider: {provider_name}
    Subscription: {sub_type}
    Mode: {mode}
    Policy Context: {json.dumps(policy_info, ensure_ascii=False)}

    CRITICAL INSTRUCTIONS:
    - DO NOT include sender address, recipient address, or date headers.
    - Start directly with the Subject Line ("Betreff: ...").
    - Include formal greeting ("Sehr geehrte Damen und Herren,").
    - If Mode is 'after_death', explicitly mention contract termination due to death under Swiss Code of Obligations (OR Art. 405) and reference attached Todesurkunde.
    - If Mode is 'during_life', state cancellation per notice terms.
    - End with "Mit freundlichen Grüssen,".
    """

    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model=APERTUS_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception:
            if attempt == 4:
                raise HTTPException(status_code=504, detail="Letter generation failed after retries.")
            delay = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.5)
            time.sleep(delay)
