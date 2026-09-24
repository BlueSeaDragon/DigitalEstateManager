import os
import json
from openai import OpenAI
from duckduckgo_search import DDGS

APERTUS_API_KEY = os.getenv("SWISSCOM_API_KEY", "your-swisscom-api-key")
APERTUS_BASE_URL = os.getenv("APERTUS_BASE_URL", "https://api.swisscom.com/products/swiss-ai-weeks/apertus-1.5-70b/v1")
APERTUS_MODEL = os.getenv("APERTUS_MODEL", "swiss-ai/Apertus-v1.5-70B")

client = OpenAI(api_key=APERTUS_API_KEY, base_url=APERTUS_BASE_URL)

def search_web_cancellation_policy(provider_name: str, sub_type: str, mode: str = "during_life") -> dict:
    """Searches the web live for specific provider + subscription cancellation rules."""
    query = f"{provider_name} {sub_type} Kündigung {mode} Frist Adresse Switzerland"
    
    results = []
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, max_results=5))
            for r in search_results:
                results.append({"title": r.get("title"), "snippet": r.get("body"), "url": r.get("href")})
    except Exception as e:
        print(f"Search error: {e}")

    system_prompt = (
        "You are a Swiss legal assistant specializing in contract cancellations. "
        "Analyze the web search snippets provided and summarize key cancellation terms in German."
    )
    
    user_prompt = f"""
    Provider: {provider_name}
    Subscription/Asset Type: {sub_type}
    Cancellation Context: {mode}
    Web Search Results: {json.dumps(results, ensure_ascii=False)}
    
    Respond strictly in valid JSON format with these exact keys:
    1. "notice_period": string summarizing notice period / deadline.
    2. "summary_bullets": list of 3-4 short, clear bullet points on how to cancel.
    3. "direct_links": list of strings (URLs found in search for user to visit directly).
    4. "required_docs": list of required documents (e.g., Todesschein, Contract ID).
    5. "recipient_address": official provider cancellation address or online portal link.
    """

    response = client.chat.completions.create(
        model=APERTUS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2
    )

    content = response.choices[0].message.content
    # Clean up markdown code blocks if present in LLM response
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    return json.loads(content)


def generate_cancellation_letter(provider_name: str, sub_type: str, person_name: str, contract_id: str, mode: str, policy_info: dict) -> str:
    """Generates formal Swiss legal letter text using Apertus."""
    system_prompt = "You write formal legal cancellation letters under Swiss Law (Einfacher Auftrag / OR Art. 405)."
    
    user_prompt = f"""
    Write a formal German cancellation letter.
    Sender Name: {person_name}
    Contract/Customer ID: {contract_id}
    Provider: {provider_name}
    Subscription Type: {sub_type}
    Mode: {mode} (during_life or after_death)
    Policy Context: {json.dumps(policy_info, ensure_ascii=False)}
    
    Output ONLY the letter text in proper Swiss business letter formatting.
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
