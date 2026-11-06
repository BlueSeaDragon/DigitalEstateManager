"""RAG cancellation engine: web search + Claude (through the local Claude Code CLI).

Results are returned as the webapp's `DeathPolicy` / `CancelPolicy` models
(`digital_estate_manager.models.schemas`), in the same `(death, cancel)` shape
as `digital_estate_manager.policies.get_policies_for_service`.

Two modes: 'during_life' (the owner cancels) and 'after_death' (an executor cancels a
deceased person's contract under Swiss law). In the app both feed only the cancellation
guide; the DeathPolicy shown to executors comes from the legacy policy crawler
(`legacy_policy_crawler`, `digital_estate_manager.policies.legacy`).

Every researched policy is saved to data/cancel_policies_saved.json (public provider terms only,
no personal data). When the search finds nothing or Claude is unavailable, the saved answer is used.
Letters are saved to data/cancel_letters_saved.json with placeholders instead of names.
"""

import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlsplit

# Allow running the backend from a checkout without `pip install -e .`
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.append(str(_SRC_DIR))

from digital_estate_manager import claude_cli  # noqa: E402
from digital_estate_manager import config as _config  # noqa: E402  (also loads the repository .env)
from digital_estate_manager.models.schemas import Asset, CancelPolicy, DeathPolicy, ExecutionMethod  # noqa: E402
from digital_estate_manager.policies.rules import get_policies_for_service  # noqa: E402

# Researched policies, reused when a live lookup fails (data/ is gitignored)
SAVED_POLICIES_FILE = _config.REPO_ROOT / "data" / "cancel_policies_saved.json"
# Letters Claude wrote, with placeholders instead of names and contract number
SAVED_LETTERS_FILE = _config.REPO_ROOT / "data" / "cancel_letters_saved.json"
SENDER, DECEASED, CONTRACT = "[[SENDER]]", "[[DECEASED]]", "[[CONTRACT]]"
# Seconds to wait for Claude before falling back (saved policy, template letter); answers take 10-30 s
CLAUDE_TIMEOUT = 45.0

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
    """Raised when Claude cannot produce a policy or letter and no saved answer exists."""


def _saved_key(provider_name: str, sub_type: str, mode: Mode) -> str:
    return f"{provider_name.strip().lower()}|{sub_type.strip().lower()}|{mode}"


def _load_saved(path: Path) -> Dict[str, Any]:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _store(path: Path, key: str, value: Any) -> None:
    saved = _load_saved(path)
    saved[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass  # saving is only a fallback for later lookups


def _saved_policy(provider_name: str, sub_type: str, mode: Mode) -> Optional[dict]:
    return _load_saved(SAVED_POLICIES_FILE).get(_saved_key(provider_name, sub_type, mode))


def _save_policy(provider_name: str, sub_type: str, mode: Mode, data: dict) -> None:
    _store(SAVED_POLICIES_FILE, _saved_key(provider_name, sub_type, mode), data)


def _letter_fields(person_name: str, contract_id: str, deceased_name: Optional[str]) -> Dict[str, str]:
    """Placeholder -> value for the personal details in a letter (empty values are left out)."""
    contract = contract_id.strip()
    fields = {
        SENDER: person_name.strip(),
        DECEASED: (deceased_name or "").strip(),
        CONTRACT: "" if contract == "-" else contract,
    }
    return {placeholder: value for placeholder, value in fields.items() if value}


def _save_letter(provider_name: str, sub_type: str, mode: Mode, letter: str, fields: Dict[str, str]) -> None:
    """Saves the letter with placeholders in place of the names and contract number.

    Not saved if any part of a name (3+ letters) is still in the letter, e.g. "Frau Keller":
    the saved file must hold no personal data.
    """
    blank = letter
    for placeholder, value in sorted(fields.items(), key=lambda item: -len(item[1])):
        blank = re.sub(rf"\b{re.escape(value)}\b", lambda match: placeholder, blank)
    for placeholder in (SENDER, DECEASED):
        for part in fields.get(placeholder, "").split():
            if len(part) >= 3 and re.search(rf"\b{re.escape(part)}\b", blank, flags=re.IGNORECASE):
                return
    if CONTRACT in fields and fields[CONTRACT] in blank:
        return
    _store(SAVED_LETTERS_FILE, _saved_key(provider_name, sub_type, mode), blank)


def _saved_letter(provider_name: str, sub_type: str, mode: Mode, fields: Dict[str, str]) -> Optional[str]:
    """The saved letter filled in with the current details, or None if there is none or a detail is missing."""
    blank = _load_saved(SAVED_LETTERS_FILE).get(_saved_key(provider_name, sub_type, mode))
    if not isinstance(blank, str):
        return None
    for placeholder in (SENDER, DECEASED, CONTRACT):
        if placeholder in blank:
            if placeholder not in fields:
                return None
            blank = blank.replace(placeholder, fields[placeholder])
    return blank


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
    """Runs web search + Claude and returns the raw policy JSON (or the saved one if that fails)."""
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
    saved = _saved_policy(provider_name, sub_type, mode)
    if not search_results and saved is not None:
        return saved
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

    # One try with a short timeout: when it fails, the saved answer is shown without an error
    try:
        data = claude_cli.ask_json(user_prompt, system_prompt, timeout=CLAUDE_TIMEOUT)
    except claude_cli.ClaudeCLIError as e:
        if saved is not None:
            return saved
        raise CancellationEngineError(f"Claude could not research the policy: {e}") from e
    data["_sources"] = search_results  # lets policies_from_rag() drop links not found in the search
    if search_results:
        _save_policy(provider_name, sub_type, mode, data)
    return data


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


# "1. ", "2) ", "Step 3: ", "Schritt 4 -": the guide numbers the steps itself
_STEP_NUMBER = re.compile(r"^\s*(?:(?:step|schritt)\s*)?\d+\s*[.):\-–]\s+", re.IGNORECASE)


def _as_steps(value: Any) -> List[str]:
    """The researched steps without the numbers Claude sometimes puts in front of them."""
    return [step for step in (_STEP_NUMBER.sub("", item, count=1).strip() for item in _as_list(value)) if step]


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
        steps=_as_steps(raw.get("channel_instructions")),
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
    Claude's letters are saved with placeholders instead of the personal details. If Claude is
    unavailable, the saved letter is filled in with the current details, else a fixed template.
    """
    policy_info = {"cancel_policy": cancel_policy.model_dump(exclude={"email_template", "status", "resolution_notes"})}
    if death_policy is not None and mode == "after_death":
        policy_info["death_policy"] = death_policy.model_dump()
    deceased_line = f"Deceased account holder: {deceased_name}" if mode == "after_death" and deceased_name else ""

    system_prompt = (
        "You write formal legal cancellation letters under Swiss Law. "
        "Reply with the letter body only, without any comment before or after it."
    )

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

    fields = _letter_fields(person_name, contract_id, deceased_name if mode == "after_death" else None)
    try:
        letter = claude_cli.ask(user_prompt, system_prompt, timeout=CLAUDE_TIMEOUT).strip()
    except claude_cli.ClaudeCLIError:
        letter = ""
    if letter:
        _save_letter(provider_name, sub_type, mode, letter, fields)
    else:
        letter = _saved_letter(provider_name, sub_type, mode, fields) or _template_letter(
            provider_name, sub_type, person_name, contract_id, mode, deceased_name
        )

    # CancelPolicy.execute_action() runs str.format() on the template, so escape literal braces
    cancel_policy.email_template = letter.replace("{", "{{").replace("}", "}}")
    return letter


def _template_letter(
    provider_name: str,
    sub_type: str,
    person_name: str,
    contract_id: str,
    mode: Mode,
    deceased_name: Optional[str] = None,
) -> str:
    """A fixed German letter body, used when Claude cannot write one. Same structure as Claude's."""
    plan = sub_type.strip()
    named = plan and plan.lower() != "subscription"
    contract = f"das Abonnement «{plan}» bei {provider_name}" if named else f"das Abonnement bei {provider_name}"
    number = contract_id.strip()
    number = "" if number in ("", "-") else number
    number_part = f" (Vertragsnummer {number})" if number else ""
    subject = f"Betreff: Kündigung {provider_name}" + (f" «{plan}»" if named else "")
    subject += f", Vertragsnummer {number}" if number else ""

    if mode == "after_death":
        holder = deceased_name.strip() if deceased_name and deceased_name.strip() else "die Vertragsinhaberin bzw. der Vertragsinhaber"
        body = [
            f"{subject} (Todesfall)",
            "",
            "Sehr geehrte Damen und Herren,",
            "",
            f"hiermit teile ich Ihnen mit, dass {holder} verstorben ist. "
            f"Es betrifft {contract}{number_part}.",
            "",
            f"Im Namen der Erben kündige ich diesen Vertrag per sofort. Gemäss {SWISS_LEGAL_BASIS} "
            "endet ein solcher Vertrag mit dem Tod der Vertragspartei.",
            "",
            "Bitte stellen Sie ab sofort keine weiteren Rechnungen aus, erstatten Sie allfällig "
            "vorausbezahlte Beträge und bestätigen Sie mir die Kündigung schriftlich.",
            "",
            "Eine Kopie der Todesurkunde und des Erbscheins liegt diesem Schreiben bei.",
        ]
    else:
        body = [
            subject,
            "",
            "Sehr geehrte Damen und Herren,",
            "",
            f"hiermit kündige ich {contract}{number_part} "
            "fristgerecht auf den nächstmöglichen Termin.",
            "",
            "Bitte bestätigen Sie mir die Kündigung sowie das genaue Vertragsende schriftlich.",
        ]
    return "\n".join(body + ["", "Mit freundlichen Grüssen,", person_name.strip()])
