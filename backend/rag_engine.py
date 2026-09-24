import os
import json
from openai import OpenAI
from ddgs import DDGS

client = OpenAI(
    base_url="https://app.swisscom.ch/ai/api/v1",
    api_key=os.getenv("SWISSCOM_API_KEY", "")
)

APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"

def search_web_cancellation_policy(provider_name: str, sub_type: str = "subscription", mode: str = "during_life") -> dict:
    query = f"{provider_name} {sub_type} Kündigung Kündigungsfrist Adresse Schweiz"
    search_results = []
    
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
        for r in results:
            search_results.append(f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}")
            
    context_str = "\n\n".join(search_results)
    
    system_prompt = "You extract cancellation details into valid JSON."
    user_prompt = f"""
    Context: {context_str}
    Provider: {provider_name}
    
    Extract JSON with:
    - notice_period: string
    - summary_bullets: list of short step strings
    - direct_links: list of URLs
    - required_docs: list of strings
    - recipient_address: physical mailing address for cancellation
    """
    
    response = client.chat.completions.create(
        model=APERTUS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)

def generate_cancellation_letter(provider_name: str, sub_type: str, person_name: str, contract_id: str, mode: str, policy_info: dict) -> str:
    system_prompt = "You write only the body of formal legal cancellation letters under Swiss Law."
    
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
    - If Mode is 'after_death', explicitly mention the contract holder has passed away and cite Swiss Code of Obligations (OR Art. 405).
    - If Mode is 'during_life', state cancellation per notice terms.
    - End with "Mit freundlichen Grüssen,".
    - DO NOT add signature line placeholders at the end.
    """

    response = client.chat.completions.create(
        model=APERTUS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1
    )

    return response.choices[0].message.content
