"""RAG cancellation engine: web search + Swisscom-hosted Apertus.

Results are returned as the webapp's `DeathPolicy` / `CancelPolicy` models
(`digital_estate_manager.models.schemas`), in the same `(death, cancel)` shape
as `digital_estate_manager.policies.get_policies_for_service`.

Two modes: 'during_life' (the owner cancels) and 'after_death' (an executor cancels a
deceased person's contract under Swiss law). In the app both feed only the cancellation
guide; the DeathPolicy shown to executors comes from the legacy policy crawler
(`legacy_policy_crawler`, `digital_estate_manager.policies.legacy`).
"""

import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlsplit

from openai import OpenAI

# Allow running the backend from a checkout without `pip install -e .`
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.append(str(_SRC_DIR))

from digital_estate_manager import config as _config  # noqa: E402,F401  (loads the repository .env)
from digital_estate_manager.models.schemas import Asset, CancelPolicy, DeathPolicy, ExecutionMethod  # noqa: E402
from digital_estate_manager.policies.rules import get_policies_for_service  # noqa: E402

SWISSCOM_BASE_URL = os.getenv("SWISSCOM_BASE_URL") or "https://api.swisscom.com/products/swiss-ai-weeks/apertus-1.5-70b/v1"
SWISSCOM_API_KEY = os.getenv("SWISSCOM_API_KEY", "")

# The SDK rejects an empty key at construction; _require_api_key() reports it on use instead
client = OpenAI(
    base_url=SWISSCOM_BASE_URL,
    api_key=SWISSCOM_API_KEY or "unset",
    timeout=20.0
)

APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"

Mode = Literal["during_life", "after_death"]

# Swiss Code of Obligations: contracts of this kind end upon the holder's death
SWISS_LEGAL_BASIS = "OR Art. 405"
# Documents always required after death, with the spellings used to detect them in LLM output
SWISS_AFTER_DEATH_DOCS = {
    "Todesurkunde (Death Certificate)": ("todesurkunde", "todesschein", "death certificate"),
    "Erbenschein": ("erbenschein", "erbschein", "erbbescheinigung", "certificate of inheritance"),
}

# RAG `primary_channel` -> schemas.ExecutionMethod
CHANNEL_TO_EXECUTION_METHOD: Dict[str, ExecutionMethod] = {
    "web_portal": "web_portal",
    "app_store": "web_portal",
    "email": "email_notice",
    "registered_letter": "manual_steps",
    "phone_call": "manual_steps",
}


class CancellationEngineError(RuntimeError):
    """Raised when the Apertus API cannot produce a policy or letter after retries."""


def _require_api_key() -> None:
    if not SWISSCOM_API_KEY:
        raise CancellationEngineError("SWISSCOM_API_KEY is not set (see .env.example).")


def fetch_web_results_safe(query: str, max_retries: int = 4) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

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


def _query_policy(provider_name: str, sub_type: str, mode: Mode) -> dict:
    """Runs web search + Apertus and returns the raw policy JSON."""
    _require_api_key()
    if mode == "after_death":
        queries = [
            f"{provider_name} support contact email cancellation Todesfall Kündigung Schweiz",
            f"{provider_name} {sub_type} kündigen verstorben Angehörige",
        ]
    else:
        queries = [
            f"{provider_name} {sub_type} Kündigung Mindestlaufzeit Schweiz Abo Support Contact Email",
            f"{provider_name} {sub_type} kündigen Anleitung",
        ]
    search_results: List[str] = []
    for query in queries:
        for result in fetch_web_results_safe(query):
            if result not in search_results:
                search_results.append(result)
    context_str = "\n\n".join(search_results) if search_results else "No search results were found."

    system_prompt = f"You are a Swiss legal and estate assistant analyzing cancellation policies strictly for '{provider_name}'. Output valid JSON only."

    user_prompt = f"""
    Context: {context_str}
    Target Provider: {provider_name}
    Provided Sub-Type: {sub_type}
    Mode: {mode}

    STRICT COMPLIANCE & CONTACT EXTRACTION RULES:
    1. LINKS AND CONTACTS COME ONLY FROM THE CONTEXT:
       - 'portal_url': the page that explains how to cancel {provider_name} or where the cancellation is done (e.g. a help article "cancel subscription" / "Abo kündigen"). Copy it exactly from a 'URL:' line in the Context. Never a homepage.
       - 'policy_url': the page with {provider_name}'s cancellation terms (e.g. "Kündigung und Erstattung", terms of cancellation). Copy it exactly from a 'URL:' line in the Context.
       - Prefer pages on {provider_name}'s own website; use third-party pages only if the Context has no official page.
       - 'contact_email': only an email address that appears in the Context as a contact for cancellations.
       - If the Context contains no suitable URL or email, return "" for it. Never guess or invent links or email addresses.
    2. If Mode is 'after_death' (an executor cancels on behalf of the deceased account holder):
       - Under Swiss Law (OR Art. 405), contracts terminate immediately upon death. Set 'notice_period' and 'minimum_contract_duration' to "Immediate (upon notification of death)".
       - List official required documents in 'required_docs' (MUST include "Todesurkunde (Death Certificate)" and "Erbenschein").
       - Step-by-step instructions in 'channel_instructions' MUST reference the exact contact email or portal provided in the JSON fields.
       - If the Context has {provider_name}'s page for bereaved relatives / deceased customers, set 'has_mourning_portal' to true and copy its URL into 'mourning_portal_url'.
    3. If Mode is 'during_life':
       - Provide standard notice periods and minimum contract terms.
    4. PLAN VARIATION:
       - Decide whether the cancellation rules (minimum contract duration, notice period, cancellation channel) differ between {provider_name}'s plans.
       - If 'Provided Sub-Type' names a specific plan, answer for that plan and set 'requires_sub_type_selection' to false, unless it matches none of {provider_name}'s plans.
       - If 'Provided Sub-Type' is generic (e.g. "subscription") and the rules differ significantly between plans, set 'requires_sub_type_selection' to true, list the plan names in 'sub_type_options', and fill all other fields with the general policy that applies across plans.
       - If the rules are the same for all plans, set 'requires_sub_type_selection' to false and 'sub_type_options' to [].

    Return JSON format:
    - minimum_contract_duration: string
    - notice_period: string
    - primary_channel: string MUST BE ONE OF ["web_portal", "email", "registered_letter", "app_store", "phone_call"]
    - requires_sub_type_selection: boolean
    - sub_type_options: list of strings
    - channel_instructions: list of specific step-by-step instructions for {provider_name}
    - portal_url: string
    - policy_url: string (official {provider_name} page describing its cancellation terms / policy)
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

            data["_sources"] = search_results  # lets policies_from_rag() drop links not found in the search
            return data

        except Exception as e:
            if attempt == max_attempts - 1:
                raise CancellationEngineError(f"Swisscom Apertus API failure. Details: {str(e)}") from e

            delay = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.5)
            time.sleep(delay)

    raise CancellationEngineError(f"Swisscom Apertus API returned no usable policy for {provider_name}.")


# =============================================================================
# RAG output -> schemas.py models
# =============================================================================

def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_url(value: Any) -> Optional[str]:
    url = _as_str(value)
    return url if url.startswith("http") else None


def _as_email(value: Any) -> Optional[str]:
    email = _as_str(value).removeprefix("mailto:")
    return email if "@" in email and " " not in email else None


def _url_key(url: str) -> Tuple[str, str]:
    parts = urlsplit(url)
    return parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/")


def _grounded_url(url: Optional[str], sources: Optional[List[str]]) -> Optional[str]:
    """Keeps a URL only if that exact page is in the search results (never a bare homepage).

    Returns the search result's own URL, so query parameters like the language are kept.
    `sources` is None when no search ran (e.g. raw JSON from tests): the URL is kept as is.
    """
    if url is None or sources is None:
        return url
    host, path = _url_key(url)
    if not path:
        return None
    source_urls = re.findall(r"^URL: (\S+)", "\n".join(sources), flags=re.MULTILINE)
    if url in source_urls:
        return url
    return next((s for s in source_urls if _url_key(s) == (host, path)), None)


def _grounded_email(email: Optional[str], sources: Optional[List[str]]) -> Optional[str]:
    """Keeps an email address only if exactly that address appears in the search results."""
    if email is None or sources is None:
        return email
    pattern = rf"(?<![\w.+-]){re.escape(email)}(?![\w-])"
    return email if re.search(pattern, "\n".join(sources), flags=re.IGNORECASE) else None


def _required_documents(raw_docs: Any, mode: Mode) -> List[str]:
    docs: List[str] = []
    for doc in _as_list(raw_docs):
        if doc.lower() not in (d.lower() for d in docs):
            docs.append(doc)
    if mode == "after_death":
        for label, spellings in SWISS_AFTER_DEATH_DOCS.items():
            if not any(s in doc.lower() for doc in docs for s in spellings):
                docs.append(label)
    return docs


def policies_from_rag(
    raw: Dict[str, Any],
    provider_name: str,
    sub_type: str = "subscription",
    mode: Mode = "during_life",
    service_address: Optional[str] = None,
) -> Tuple[DeathPolicy, CancelPolicy]:
    """Maps raw RAG policy JSON onto the webapp's DeathPolicy and CancelPolicy.

    In 'during_life' mode the death policy comes from the knowledge base; in 'after_death' mode
    it is built from the RAG result under Swiss law (OR Art. 405). Links and the email address
    are kept only if they appear in the search results (`raw["_sources"]`).
    """
    sources = raw.get("_sources")
    portal_url = _grounded_url(_as_url(raw.get("portal_url")), sources)
    policy_url = _grounded_url(_as_url(raw.get("policy_url")), sources)
    mourning_portal_url = None
    if mode == "after_death" and raw.get("has_mourning_portal"):
        mourning_portal_url = _grounded_url(_as_url(raw.get("mourning_portal_url")), sources)
    support_email = _grounded_email(_as_email(raw.get("contact_email")), sources)
    required_documents = _required_documents(raw.get("required_docs"), mode)
    notice_period = _as_str(raw.get("notice_period"))
    minimum_duration = _as_str(raw.get("minimum_contract_duration"))

    primary_channel = _as_str(raw.get("primary_channel")).lower()
    execution_method = CHANNEL_TO_EXECUTION_METHOD.get(primary_channel)
    if execution_method is None:
        execution_method = "email_notice" if support_email else "web_portal" if portal_url else "manual_steps"

    action_payload: Dict[str, Any] = {
        "mode": mode,
        "sub_type": sub_type,
        "primary_channel": primary_channel or None,
        "policy_url": policy_url,
        "notice_period": notice_period or None,
        "minimum_contract_duration": minimum_duration or None,
        "contact_phone": _as_str(raw.get("contact_phone")) or None,
        "mailing_address": _as_str(raw.get("mailing_address")) or None,
        "requires_sub_type_selection": bool(raw.get("requires_sub_type_selection")),
        "sub_type_options": _as_list(raw.get("sub_type_options")),
        "has_mourning_portal": mourning_portal_url is not None,
        "mourning_portal_url": mourning_portal_url,
    }
    if mode == "after_death":
        action_payload["legal_basis"] = SWISS_LEGAL_BASIS

    cancel_policy = CancelPolicy(
        action_type="cancel_subscription",
        action_name=f"Cancel {provider_name} {sub_type}".strip(),
        execution_method=execution_method,
        target_url=(mourning_portal_url or portal_url) if mode == "after_death" else portal_url,
        support_email=support_email,
        required_documents=required_documents,
        steps=_as_list(raw.get("channel_instructions")),
        action_payload=action_payload,
    )

    if mode == "after_death":
        summary = (
            f"Under Swiss law ({SWISS_LEGAL_BASIS}) the {provider_name} contract ends upon the "
            f"account holder's death. Notice period: {notice_period or 'Immediate (upon notification of death)'}."
        )
        death_policy = DeathPolicy(
            summary=summary,
            required_documents=required_documents,
            official_portal_url=mourning_portal_url or portal_url,
        )
    else:
        death_policy, _ = get_policies_for_service(provider_name, service_address)

    return death_policy, cancel_policy


def search_web_cancellation_policy(
    provider_name: str,
    sub_type: str = "subscription",
    mode: Mode = "during_life",
    service_address: Optional[str] = None,
) -> Tuple[DeathPolicy, CancelPolicy]:
    """Researches the provider's cancellation policy and returns (DeathPolicy, CancelPolicy)."""
    raw = _query_policy(provider_name, sub_type, mode)
    return policies_from_rag(raw, provider_name, sub_type, mode, service_address)


def enrich_asset(asset: Asset, mode: Mode = "during_life", sub_type: str = "subscription") -> Asset:
    """Replaces an asset's policies with RAG-researched ones (in place) and returns it."""
    asset.death_policy, asset.cancel_policy = search_web_cancellation_policy(
        asset.service, sub_type=sub_type, mode=mode, service_address=asset.service_address or None
    )
    return asset


def generate_cancellation_letter(
    provider_name: str,
    sub_type: str,
    person_name: str,
    contract_id: str,
    mode: Mode,
    cancel_policy: CancelPolicy,
    death_policy: Optional[DeathPolicy] = None,
    deceased_name: Optional[str] = None,
) -> str:
    """Writes the German letter body and stores it as `cancel_policy.email_template`.

    In 'after_death' mode `person_name` is the executor writing on behalf of `deceased_name`.
    """
    _require_api_key()
    policy_info = {"cancel_policy": cancel_policy.model_dump(exclude={"email_template", "status", "resolution_notes"})}
    if death_policy is not None and mode == "after_death":
        policy_info["death_policy"] = death_policy.model_dump()
    deceased_line = f"Deceased account holder: {deceased_name}" if mode == "after_death" and deceased_name else ""

    system_prompt = "You write formal legal cancellation letters under Swiss Law."

    user_prompt = f"""
    Write the BODY of a formal German cancellation letter.
    Sender: {person_name}
    {deceased_line}
    Contract ID: {contract_id}
    Provider: {provider_name}
    Subscription: {sub_type}
    Mode: {mode}
    Policy Context: {json.dumps(policy_info, ensure_ascii=False)}

    CRITICAL INSTRUCTIONS:
    - DO NOT include sender address, recipient address, or date headers.
    - Start directly with the Subject Line ("Betreff: ...").
    - Include formal greeting ("Sehr geehrte Damen und Herren,").
    - If Mode is 'after_death', write as the executor on behalf of the deceased account holder, explicitly mention contract termination due to death under Swiss Code of Obligations (OR Art. 405) and reference attached Todesurkunde.
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
            letter = response.choices[0].message.content
            break
        except Exception as e:
            if attempt == 4:
                raise CancellationEngineError("Letter generation failed after retries.") from e
            delay = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.5)
            time.sleep(delay)

    # CancelPolicy.execute_action() runs str.format() on the template, so escape literal braces
    cancel_policy.email_template = letter.replace("{", "{{").replace("}", "}}")
    return letter
