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
    timeout=15.0
)

APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"

def search_web_cancellation_policy(provider_name: str, sub_type: str = "subscription", mode: str = "during_life") -> dict:
    query = f"{provider_name} {sub_type} Kündigung Schweiz Nachlass Todesfall" if mode == "after_death" else f"{provider_name} {sub_type} Kündigung Schweiz"
    search_results = []
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            for r in results:
                search_results.append(f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}")
    except Exception as e:
        # Fallback snippet if DDGS times out or blocks rate
        search_results.append(f"Snippet: Standard Swiss subscription cancellation for {provider_name}.")

    context_str = "\n\n".join(search_results)
    
    system_prompt = "You determine the primary cancellation channel and extract structured information into valid JSON."
    user_prompt = f"""
    Context: {context_str}
    Provider: {provider_name}
    Mode: {mode}
    
    Extract JSON with:
    - notice_period: string (e.g. "3 months to month end")
    - primary_channel: string MUST BE ONE OF ["web_portal", "email", "registered_letter", "app_store", "phone_call"]
    - channel_instructions: list of clear, short step-by-step strings for the user
    - portal_url: string (direct URL if web_portal or app_store, else "")
    - contact_email: string (support email if email, else "")
    - contact_phone: string (phone number if phone_call, else "")
    - mailing_address: string (physical address if registered_letter, else "")
    - required_docs: list of strings (e.g. ["Customer ID", "Death Certificate"])
    - has_mourning_portal: boolean (true if provider has a specific digital estate/mourning portal in Switzerland)
    - mourning_portal_url: string (URL if has_mourning_portal is true, else "")
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
        # Fallback structured plan if API connection drops
        return {
            "notice_period": "In der Regel 1 bis 3 Monate per Ende der Vertragslaufzeit.",
            "primary_channel": "registered_letter",
            "channel_instructions": [
                f"Kündigung schriftlich an {provider_name} verfassen.",
                "Per Einschreiben oder offizieller E-Mail senden.",
                "Bestätigung aufbewahren."
            ],
            "portal_url": "",
            "contact_email": "",
            "contact_phone": "",
            "mailing_address": f"{provider_name}, Kundendienst, Schweiz",
            "required_docs": ["Vertragsnummer", "Personalien"],
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
        # Static fallback letter text if Apertus LLM endpoint is unreachable
        return f"Betreff: Kündigung meiner Mitgliedschaft bei {provider_name} - Vertragsnummer {contract_id}\n\nSehr geehrte Damen und Herren,\n\nhiermit kündige ich meinen Vertrag ({contract_id}) bei {provider_name} fristgerecht zum nächstmöglichen Zeitpunkt.\n\nBitte bestätigen Sie mir den Erhalt dieser Kündigung sowie das Vertragsende schriftlich.\n\nMit freundlichen Grüssen,\n{person_name}"
