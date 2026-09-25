"""RAG cancellation engine: web search + Swisscom-hosted Apertus.

Results are returned as the webapp's `DeathPolicy` / `CancelPolicy` models
(`digital_estate_manager.models.schemas`), in the same `(death, cancel)` shape
as `digital_estate_manager.policies.get_policies_for_service`.
"""

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

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
        query = f"{provider_name} support contact email cancellation Todesfall Kündigung Schweiz"
    else:
        query = f"{provider_name} {sub_type} Kündigung Mindestlaufzeit Schweiz Abo Support Contact Email"

    search_results = fetch_web_results_safe(query)
    context_str = "\n\n".join(search_results) if search_results else f"Rely on official Swiss and global support facts for {provider_name}."

    system_prompt = f"You are a Swiss legal and estate assistant analyzing cancellation policies strictly for '{provider_name}'. Output valid JSON only."

    user_prompt = f"""
    Context: {context_str}
    Target Provider: {provider_name}
    Provided Sub-Type: {sub_type}
    Mode: {mode}

    STRICT COMPLIANCE & CONTACT EXTRACTION RULES:
    1. PROVIDE DIRECT CONTACT INFO:
       - If an email, portal URL, or contact link exists for {provider_name} (e.g. support@anthropic.com, https://support.anthropic.com, support@sbb.ch), YOU MUST INCLUDE IT in 'contact_email' and 'portal_url'.
       - DO NOT leave 'portal_url' or 'contact_email' empty if the official support domain or address is standard for {provider_name}.
    2. If Mode is 'after_death':
       - Under Swiss Law (OR Art. 405), contracts terminate immediately upon death. Set 'notice_period' and 'minimum_contract_duration' to "Immediate (upon notification of death)".
       - List official required documents in 'required_docs' (MUST include "Todesurkunde (Death Certificate)" and "Erbenschein").
       - Step-by-step instructions in 'channel_instructions' MUST reference the exact contact email or portal provided in the JSON fields.
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

    In 'during_life' mode the death policy comes from the known-policy knowledge base;
    in 'after_death' mode it is built from the RAG result under Swiss law (OR Art. 405).
    """
    portal_url = _as_url(raw.get("portal_url"))
    mourning_portal_url = _as_url(raw.get("mourning_portal_url")) if raw.get("has_mourning_portal") else None
    support_email = _as_email(raw.get("contact_email"))
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
        "policy_url": _as_url(raw.get("policy_url")),
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


def enrich_asset(asset: Asset, mode: Mode = "after_death", sub_type: str = "subscription") -> Asset:
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
) -> str:
    """Writes the German letter body and stores it as `cancel_policy.email_template`."""
    _require_api_key()
    policy_info = {"cancel_policy": cancel_policy.model_dump(exclude={"email_template", "status", "resolution_notes"})}
    if death_policy is not None and mode == "after_death":
        policy_info["death_policy"] = death_policy.model_dump()

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
