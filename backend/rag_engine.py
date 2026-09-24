import os
import json
from openai import OpenAI

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

client = OpenAI(
    base_url="https://app.swisscom.ch/ai/api/v1",
    api_key=os.getenv("SWISSCOM_API_KEY", ""),
    timeout=20.0
)

APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"

def search_web_cancellation_policy(provider_name: str, sub_type: str = "subscription", mode: str = "during_life") -> dict:
    query = f"{provider_name} {sub_type} Kündigung Abo kündigen Schweiz" if mode != "after_death" else f"{provider_name} {sub_type} Kündigung Nachlass Todesfall"
    search_results = []
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            for r in results:
                search_results.append(f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}")
    except Exception as e:
        search_results.append("Error fetching live web search results.")

    context_str = "\n\n".join(search_results)
    
    system_prompt = "You extract exact subscription cancellation instructions into valid JSON based on official web sources."
    user_prompt = f"""
    Context: {context_str}
    Provider: {provider_name}
    Subscription Type: {sub_type}
    Mode: {mode}
    
    CRITICAL: Analyze the context carefully. Check if cancellation is done online via a member portal, by email, or via letter.
    
    Extract JSON with:
    - notice_period: string (e.g., "1 month before renewal date" or "Cancel anytime during contract term")
    - primary_channel: string MUST BE ONE OF ["web_portal", "email", "registered_letter", "app_store", "phone_call"]
    - channel_instructions: list of precise step-by-step instructions based strictly on policy context
    - portal_url: string (direct link to customer login/portal if web_portal, else "")
    - contact_email: string (support email if email option exists, else "")
    - contact_phone: string (phone number if applicable, else "")
    - mailing_address: string (physical address if letter required, else "")
    - required_docs: list of strings
    - has_mourning_portal: boolean
    - mourning_portal_url: string
    """
    
    try:
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
    except Exception as e:
        return {
            "notice_period": "Unable to fetch live policy. Please check internet connection.",
            "primary_channel": "email",
            "channel_instructions": ["Live search timeout. Retry request."],
            "portal_url": "",
            "contact_email": "",
            "contact_phone": "",
            "mailing_address": "",
            "required_docs": [],
            "has_mourning_portal": False,
            "mourning_portal_url": ""
        }

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
    - If Mode is 'after_death', explicitly mention contract termination due to death under Swiss Code of Obligations (OR Art. 405).
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
