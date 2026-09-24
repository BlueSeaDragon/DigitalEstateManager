import os
import json
import time
from openai import OpenAI
from fastapi import HTTPException

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

# Configured with robust 40s timeout for complex Swiss legal queries
client = OpenAI(
    base_url="https://app.swisscom.ch/ai/api/v1",
    api_key=os.getenv("SWISSCOM_API_KEY", ""),
    timeout=40.0
)

APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"

def fetch_web_results_with_retry(query: str, max_retries: int = 3) -> list:
    """Retries web search with exponential backoff if network drops or rate-limits occur."""
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                if results:
                    return [f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}" for r in results]
        except Exception as e:
            if attempt == max_retries - 1:
                # Log search failure, continue with Apertus model's knowledge
                return []
            # Exponential backoff: wait 1s, 2s, 4s...
            time.sleep(2 ** attempt)
    return []

def search_web_cancellation_policy(provider_name: str, sub_type: str = "subscription", mode: str = "during_life") -> dict:
    query = f"{provider_name} {sub_type} Kündigung Schweiz Abo" if mode != "after_death" else f"{provider_name} {sub_type} Kündigung Nachlass Todesfall Schweiz"
    
    # Execute search with retry mechanism
    search_results = fetch_web_results_with_retry(query)
    context_str = "\n\n".join(search_results) if search_results else f"No live search results available for {provider_name}. Rely on verified facts for {provider_name} in Switzerland."
    
    system_prompt = f"You are a Swiss legal assistant analyzing cancellation policies strictly for '{provider_name}'. Output valid JSON only."
    user_prompt = f"""
    Context: {context_str}
    Target Provider: {provider_name}
    Provided Sub-Type: {sub_type}
    Mode: {mode}
    
    STRICT COMPLIANCE RULES:
    1. NEVER mention or introduce third-party URLs/emails for unrelated companies.
    2. If Provided Sub-Type is general (e.g. "subscription", "Abo", "membership") AND {provider_name} has distinct rules for Monthly vs Yearly plans, set "requires_sub_type_selection": true and list "sub_type_options".
    3. If Provided Sub-Type is specific (e.g., "GA Generalabonnement", "Halbtax", "Jahresabo"), set "requires_sub_type_selection": false AND provide the exact channel and instructions for THAT specific plan.

    Return JSON format:
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
    
    # Retry Apertus LLM request if connection fails
    max_llm_retries = 3
    for attempt in range(max_llm_retries):
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
            
            # Guardrail: Verify payload belongs strictly to requested provider
            payload_str = json.dumps(data).lower()
            if "nonstopgym" in payload_str and "nonstop" not in provider_name.lower():
                raise ValueError(f"Cross-provider contamination detected: NonStop Gym data returned for {provider_name}")
                
            return data

        except Exception as e:
            if attempt == max_llm_retries - 1:
                raise HTTPException(
                    status_code=503,
                    detail=f"Swisscom Apertus API connection temporarily unavailable for '{provider_name}'. Please try again in a few seconds. Error: {str(e)}"
                )
            time.sleep(2 ** attempt)

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
    - If Mode is 'after_death', explicitly mention contract termination due to death under Swiss Code of Obligations (OR Art. 405).
    - If Mode is 'during_life', state cancellation per notice terms.
    - End with "Mit freundlichen Grüssen,".
    """

    for attempt in range(3):
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
        except Exception as e:
            if attempt == 2:
                raise HTTPException(status_code=503, detail="Failed to generate letter due to network connection issues.")
            time.sleep(2)
