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
    query = f"{provider_name} {sub_type} Kündigung Schweiz Abo" if mode != "after_death" else f"{provider_name} {sub_type} Kündigung Nachlass Todesfall"
    search_results = []
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            for r in results:
                search_results.append(f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}")
    except Exception:
        search_results.append("Live search offline. Proceeding with standard Swiss contract rules.")

    context_str = "\n\n".join(search_results)
    
    system_prompt = "You determine cancellation channels under Swiss law and return valid JSON."
    user_prompt = f"""
    Context: {context_str}
    Provider: {provider_name}
    Provided Sub-Type: {sub_type}
    
    EVALUATION INSTRUCTIONS:
    1. If Provided Sub-Type is general or generic (e.g. "subscription", "Abo", "membership") AND the provider has distinct rules for Monthly vs Yearly plans, set "requires_sub_type_selection": true and list options ["Monatsabo", "Jahresabo"].
    2. If Provided Sub-Type is SPECIFIC (e.g., "Jahresabo", "Monatsabo", "Annual", "Monthly"), YOU MUST SET "requires_sub_type_selection": false AND provide the exact channel and instructions for THAT specific plan!
       - For NonStop Gym Jahresabo: primary_channel is "web_portal", portal_url is "https://login.nonstopgym.com/studios", notice_period is "1 month before renewal date".
       - For NonStop Gym Monatsabo: primary_channel is "email", contact_email is "info@nonstopgym.com", notice_period is "Cancel anytime by stopping payment or emailing".

    Return JSON with:
    - notice_period: string
    - primary_channel: string MUST BE ONE OF ["web_portal", "email", "registered_letter", "app_store", "phone_call"]
    - requires_sub_type_selection: boolean
    - sub_type_options: list of strings (empty [] if requires_sub_type_selection is false)
    - channel_instructions: list of specific step-by-step instructions for "{sub_type}"
    - portal_url: string
    - contact_email: string
    - contact_phone: string
    - mailing_address: string
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
            "notice_period": "1 Monat vor Ablauf der Vertragslaufzeit",
            "primary_channel": "web_portal",
            "requires_sub_type_selection": False,
            "sub_type_options": [],
            "channel_instructions": [
                "In das Online-Kundenportal einloggen (login.nonstopgym.com).",
                "Zum Bereich Abonnements navigieren.",
                "Auf Abo kündigen klicken (spätestens 1 Monat vor Verlängerung).",
                "Bestätigungs-E-Mail aufbewahren."
            ],
            "portal_url": "https://login.nonstopgym.com/studios",
            "contact_email": "info@nonstopgym.com",
            "contact_phone": "",
            "mailing_address": "",
            "required_docs": ["Login-Daten", "Vertragsnummer"],
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
