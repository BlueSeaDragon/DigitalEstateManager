import csv
import io
import os
import re
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

import pandas as pd
import streamlit as st

from digital_estate_manager.config import REPO_ROOT, onboarding_enabled
from digital_estate_manager.discovery import (
    DiscoveryInputError,
    EmailConnectionError,
    MalformedFinderResult,
    complete_email_connection,
    connect_email_provider,
    parse_and_extract,
)
from digital_estate_manager.models import (
    Asset,
    CancelPolicy,
    CloudStorageAssetInfo,
    DeathPolicy,
    FinancialAssetInfo,
    GenericAssetInfo,
    SocialMediaAssetInfo,
    SubscriptionAssetInfo,
)
from digital_estate_manager.policies.legacy import (
    AI_NOTICE,
    apply_legacy_record,
    days_since_checked,
    is_stale,
    legacy_record,
    policy_marks,
    provider_key,
    refresh_legacy_policy,
)
from digital_estate_manager.policies.rules import get_policies_for_service
from digital_estate_manager.ui import components as ui
from digital_estate_manager.ui.format import (
    asset_facts,
    categories_display,
    category_label,
    chf,
    display_name,
    monthly_display,
    status_text,
    subtitle,
    value_display,
)
from digital_estate_manager.vault import (
    WISH_OPTIONS,
    calculate_metrics,
    get_default_assets,
    join_wish,
    monthly_cost_chf,
    save_wishes,
    split_wish,
)

try:
    from cancel_policy_finder import pdf_generator, rag_engine
    CANCELLATION_ENGINE_ERROR = None
except ImportError as exc:  # backend dependencies missing: the cancellation guide reports it
    pdf_generator = rag_engine = None
    CANCELLATION_ENGINE_ERROR = str(exc)

try:
    from subscription_finder import LLMConfigError, ReconnectRequired
except ImportError:  # finder not installed: parse_and_extract() reports that itself
    class LLMConfigError(Exception):
        pass

    class ReconnectRequired(Exception):
        pass

st.set_page_config(
    page_title="Digital Estate Manager",
    page_icon=":material/lock:",
    layout="wide",
)
ui.inject_styles()

DEMO_DATASET = REPO_ROOT / "samples" / "demo_transactions.jsonl"
PAGES = ["Assets", "Discover"]
LEGACY_PAGES = {"Overview": "Assets", "Catalogue": "Assets", "Find Assets": "Discover"}
CATEGORIES = ["Subscription", "Crypto / Finance", "Cloud Storage", "Social Media", "Other"]
CLOSED = ("Cancelled", "Archived", "Completed")
STATUSES = ["Active", "Pending Review", "In Progress", "Completed", "Cancelled", "Archived", "Removed", "Wrongly Attributed"]

# =============================================================================
# 1. State Management
# =============================================================================
# Guided onboarding (docs/design/onboarding-demo.md): landing -> connect -> analyse -> reveal -> done.
ONBOARDING = onboarding_enabled()
st.session_state.setdefault("onboarding", "landing" if ONBOARDING else "done")

if "assets" not in st.session_state:
    # The onboarding starts empty, so the magic moment only counts what the scan found.
    st.session_state.assets = [] if ONBOARDING else get_default_assets()
elif len(st.session_state.assets) > 0 and isinstance(st.session_state.assets[0], dict):
    # Migrate any legacy dictionary state to typed models
    st.session_state.assets = [Asset.from_table_row(d) for d in st.session_state.assets]

if st.session_state.get("active_page") not in PAGES:
    st.session_state.active_page = LEGACY_PAGES.get(st.session_state.get("active_page"), "Assets")
st.session_state.setdefault("open_rows", set())
st.session_state.setdefault("toasts", [])
# Preference only for now: nothing sends the reminder yet.
st.session_state.setdefault("yearly_reminder", True)


def handle_oauth_redirect() -> None:
    """Completes the Gmail OAuth flow when Google redirects back with ?code=...&state=..."""
    params = st.query_params
    if "code" not in params and "error" not in params:
        return
    code, state, error = params.get("code"), params.get("state"), params.get("error")
    st.query_params.clear()
    if st.session_state.onboarding == "done":
        st.session_state.active_page = "Discover"
    else:
        st.session_state.onboarding = "connect"

    if error:
        st.session_state.oauth_message = ("error", f"Google sign-in was not completed ({error}). Try connecting again.")
        return
    try:
        # Checks that the state was issued by this server (and only once) before exchanging the code.
        st.session_state.gmail_credentials = complete_email_connection(code, state)
        st.session_state.oauth_message = ("success", "Gmail connected for this session.")
    except EmailConnectionError as exc:
        st.session_state.oauth_message = ("error", str(exc))


handle_oauth_redirect()

current_assets: List[Asset] = st.session_state.assets


def notify(message: str) -> None:
    """Queues a toast for the next run, so it survives st.rerun()."""
    st.session_state.toasts.append(message)


for _message in st.session_state.toasts:
    st.toast(_message)
st.session_state.toasts = []


def go_to(page: str) -> None:
    """Button callback: switches page before the navigation widget is drawn."""
    st.session_state.active_page = page


def toggle_row(row_key: str) -> None:
    st.session_state.open_rows ^= {row_key}


def matches_category(asset: Asset, category: str) -> bool:
    """Filter labels: Subscriptions / Finance / Cloud / Social / Other."""
    return any(category_label(t) == category for t in asset.types)


MARK_WORDS = {"✔": "Yes", "✘": "No", "–": "Not stated"}


def policy_answers(death_pol: DeathPolicy) -> Dict[str, str]:
    """The crawler's tick boxes as words (the table and letters must stay free of symbols)."""
    return {label: MARK_WORDS[mark] for label, mark in policy_marks(death_pol.tick_boxes)}


def policy_source(death_pol: DeathPolicy) -> str:
    if not death_pol.ai_generated:
        return "Hand-written"
    return "AI crawler" if death_pol.policy_found else "AI crawler, not found"


def policy_link_label(death_pol: DeathPolicy) -> str:
    if death_pol.policy_found is False:
        return "Possibly useful link (unverified)"
    if death_pol.policy_found:
        return "Open policy source"
    return "Open deceased-account page"


def render_policy_summary(death_pol: DeathPolicy) -> None:
    """Provider policy. AI-crawler text is labelled and comes with a caution."""
    ui.section_label("Provider policy (AI-generated)" if death_pol.ai_generated else "Provider policy", first=True)
    st.write(death_pol.summary)
    if death_pol.ai_generated:
        checked = f" Checked {death_pol.source_checked}." if death_pol.source_checked else ""
        if is_stale(death_pol.source_checked):
            checked += " This result is old; the owner can refresh it in the account's details."
        st.caption(AI_NOTICE + checked)
        if death_pol.policy_found:
            ui.definition_list(policy_answers(death_pol))


# =============================================================================
# 3. Dialogs
# =============================================================================
def dialog_footer(secondary: str, primary: str, key: str):
    """Secondary on the left, primary on the right. Returns (secondary_clicked, primary_clicked)."""
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        left = st.button(secondary, key=f"{key}_secondary")
        right = st.button(primary, type="primary", key=f"{key}_primary")
    return left, right


@st.dialog("Connect Gmail")
def email_connection_dialog():
    """Starts the Gmail OAuth flow."""
    ui.definition_list({"Access": "Read-only, billing emails", "Provider": "Gmail (personal and Workspace)"})
    st.caption(
        "Emails are processed in memory and only short excerpts are sent to the Swiss-hosted AI model. "
        "Nothing is stored, and the connection ends with this browser session."
    )
    if st.session_state.get("gmail_credentials"):
        ui.notice("A Gmail account is already connected for this session.", "green")

    target_email = st.text_input("Gmail address (optional)", placeholder="name@gmail.com")

    cancel_clicked, auth_clicked = dialog_footer("Cancel", "Continue with Google", "email_auth")
    if cancel_clicked:
        st.rerun()
    if auth_clicked:
        if target_email and "@" not in target_email:
            ui.notice("Enter a full Gmail address, or leave the field empty.", "red")
            return
        resp = connect_email_provider(provider="gmail", email_address=target_email or None)
        if not resp["success"]:
            ui.notice(resp["message"], "red")
            return
        st.session_state.oauth_state = resp["state"]
        st.link_button("Open Google sign-in", resp["auth_url"], type="primary", width="stretch")
        st.caption("Google opens in a new tab and sends you back here, connected. Continue in that tab.")


@st.dialog("Add asset", width="large")
def modal_add_asset_dialog(default_category: str = "Subscription"):
    """Adds one asset by hand. Type-specific fields follow the selected categories."""
    key_cat = "modal_dialog_category"
    if st.session_state.get("_last_dialog_default") != default_category:
        st.session_state[key_cat] = [default_category] if default_category in CATEGORIES else ["Subscription"]
        st.session_state["_last_dialog_default"] = default_category

    current_cats = st.session_state.get(key_cat, [default_category])
    if isinstance(current_cats, str):
        current_cats = [current_cats] if current_cats in CATEGORIES else ["Subscription"]

    r1_c1, r1_c2 = st.columns(2, vertical_alignment="bottom")
    with r1_c1:
        service_input = st.text_input("Service*", placeholder="e.g. Netflix, Dropbox, PostFinance", key="modal_service")
    with r1_c2:
        website_input = st.text_input("Website", placeholder="https://", key="modal_website")

    r2_c1, r2_c2 = st.columns(2, vertical_alignment="bottom")
    with r2_c1:
        username_input = st.text_input("Account (email, username or handle)*", key="modal_username")
    with r2_c2:
        selected_categories = st.multiselect(
            "Categories*",
            CATEGORIES,
            default=current_cats,
            key=key_cat,
            help="An asset can have several categories, e.g. Subscription and Cloud Storage for Google One.",
        )
        if not selected_categories:
            selected_categories = ["Other"]

    if "Subscription" in selected_categories:
        ui.section_label("Subscription")
        sub_c1, sub_c2, sub_c3 = st.columns(3, vertical_alignment="top")
        with sub_c1:
            cost_val = st.number_input("Monthly cost (CHF)", min_value=0.0, value=12.90, step=1.0, key="modal_sub_cost")
        with sub_c2:
            billing_val = st.selectbox("Billing", ["monthly", "annual", "quarterly", "weekly"], key="modal_sub_billing",
                                       format_func=str.capitalize)
        with sub_c3:
            tier_val = st.text_input("Plan", placeholder="e.g. Premium, Family", key="modal_sub_tier")
        renewal_val = st.text_input("Next renewal (optional)", placeholder="YYYY-MM-DD", key="modal_sub_renewal")

    if "Crypto / Finance" in selected_categories:
        ui.section_label("Finance")
        fin_c1, fin_c2, fin_c3 = st.columns(3, vertical_alignment="top")
        with fin_c1:
            balance_val = st.number_input("Approx. value (CHF)", min_value=0.0, value=1500.0, step=100.0, key="modal_fin_balance")
        with fin_c2:
            inst_val = st.selectbox("Institution", ["bank", "brokerage", "crypto_exchange", "wallet", "fintech"], key="modal_fin_inst",
                                    format_func=lambda v: v.replace("_", " ").capitalize())
        with fin_c3:
            custody_val = st.selectbox("Custody", ["Custodial (bank or exchange)", "Self-custody (private key)"], key="modal_fin_custody")
        probate_val = st.checkbox("Requires a certificate of inheritance", value=True, key="modal_fin_probate")

    if "Cloud Storage" in selected_categories:
        ui.section_label("Cloud storage")
        cl_c1, cl_c2 = st.columns(2, vertical_alignment="top")
        with cl_c1:
            cap_val = st.number_input("Capacity (GB)", min_value=1.0, value=100.0, step=10.0, key="modal_cloud_cap")
        with cl_c2:
            used_val = st.number_input("Used (GB)", min_value=0.0, value=30.0, step=5.0, key="modal_cloud_used")
        data_types_val = st.multiselect(
            "Content",
            ["Documents", "Family Photos", "Tax Returns", "Backups", "Source Code", "Legal Contracts"],
            default=["Documents", "Family Photos"],
            key="modal_cloud_types",
        )
        sens_val = st.checkbox("Contains sensitive documents", value=True, key="modal_cloud_sens")

    if "Social Media" in selected_categories:
        ui.section_label("Social media")
        soc_c1, soc_c2 = st.columns(2, vertical_alignment="top")
        with soc_c1:
            handle_val = st.text_input("Handle", placeholder="@alex", key="modal_soc_handle")
        with soc_c2:
            profile_url_val = st.text_input("Profile URL", placeholder="https://", key="modal_soc_url")
        soc_mem_val = st.checkbox("Platform supports memorialization", value=True, key="modal_soc_mem")
        soc_leg_val = st.checkbox("Legacy contact already set on the platform", value=False, key="modal_soc_leg")

    if "Other" in selected_categories or not any(c in selected_categories for c in CATEGORIES[:4]):
        ui.section_label("Other")
        custom_cat_val = st.text_input("Category name", value="Digital account", key="modal_other_name")
        custom_notes_val = st.text_area("Description", key="modal_other_notes")

    ui.section_label("After death")
    wish_input = st.selectbox(
        "Your wish for this account (optional)",
        WISH_OPTIONS,
        format_func=lambda option: option or "Not set",
        key="modal_wish",
    )
    heir_input = ""
    if wish_input == "Pass to heir":
        heir_input = st.text_input("Responsible heir (optional)", placeholder="e.g. Alex", key="modal_heir")
    wish_detail = ""
    if wish_input == "Other":
        wish_detail = st.text_input("Your wish, in a few words", max_chars=60, key="modal_wish_text",
                                    placeholder="e.g. give the photos to my sister")
    notes_input = st.text_input("Notes (optional)", key="modal_notes")

    cancel_clicked, save_clicked = dialog_footer("Cancel", "Add asset", "modal_save")
    if cancel_clicked:
        st.rerun()

    if save_clicked:
        if not service_input.strip() or not username_input.strip():
            ui.notice("Enter the service and the account to continue.", "red")
            return

        infos_to_add = []
        if "Subscription" in selected_categories:
            infos_to_add.append(
                SubscriptionAssetInfo(
                    cost_monthly=cost_val,
                    currency="CHF",
                    billing_cycle=billing_val,
                    plan_tier=tier_val.strip() if tier_val else None,
                    renewal_date=renewal_val.strip() if renewal_val else None,
                )
            )
        if "Crypto / Finance" in selected_categories:
            infos_to_add.append(
                FinancialAssetInfo(
                    approximate_balance=balance_val,
                    currency="CHF",
                    institution_type=inst_val,
                    is_custodial=custody_val.startswith("Custodial"),
                    requires_probate=probate_val,
                )
            )
        if "Cloud Storage" in selected_categories:
            infos_to_add.append(
                CloudStorageAssetInfo(
                    storage_capacity_gb=cap_val,
                    used_storage_gb=used_val,
                    data_types=data_types_val,
                    contains_sensitive_data=sens_val,
                )
            )
        if "Social Media" in selected_categories:
            infos_to_add.append(
                SocialMediaAssetInfo(
                    platform_handle=handle_val.strip() if handle_val else None,
                    profile_url=profile_url_val.strip() if profile_url_val else None,
                    memorialization_supported=soc_mem_val,
                    has_legacy_contact_set=soc_leg_val,
                )
            )
        if "Other" in selected_categories or not infos_to_add:
            infos_to_add.append(
                GenericAssetInfo(
                    category_name=custom_cat_val.strip() or "Digital account",
                    notes=custom_notes_val.strip() if custom_notes_val else None,
                )
            )

        default_death, default_cancel = get_policies_for_service(service_input, website_input)

        new_asset = Asset(
            service=service_input.strip(),
            service_address=website_input.strip(),
            username=username_input.strip(),
            death_policy=default_death,
            cancel_policy=default_cancel,
            asset_infos=infos_to_add,
            heir=heir_input.strip() or "Unassigned",
            wish=join_wish(wish_input, wish_detail),
            status="Active",
            notes=notes_input.strip() if notes_input else None,
        )

        st.session_state.assets.append(new_asset)
        save_wishes([new_asset])
        notify(f"{new_asset.service} added.")
        st.rerun()


# Cancellation guide: the RAG cancellation engine (backend/rag_engine.py) researches the
# provider's policy when the dialog opens; the dialog shows only that researched content.
CHANNEL_LABELS = {
    "web_portal": "Online portal",
    "app_store": "App store subscription settings",
    "email": "Email",
    "registered_letter": "Registered letter (Einschreiben)",
    "phone_call": "Phone call",
}
MIN_STEPS_FOR_GUIDE = 2  # fewer researched steps link to the provider's policy instead


def _asset_sub_type(asset: Asset) -> str:
    sub_info = asset.get_info("Subscription")
    return sub_info.plan_tier if sub_info and sub_info.plan_tier else "subscription"


def researched_cancel_policy(asset: Asset, sub_type: str, mode: str = "during_life"):
    """Researches the provider's cancellation policy once per asset/plan/mode and session.

    `mode` is "during_life" (the owner cancels) or "after_death" (an executor cancels for the deceased).

    Returns the CancelPolicy, or an error message when the engine is unavailable or fails.
    """
    cache = st.session_state.setdefault("researched_cancel_policies", {})
    key = (asset.id, sub_type, mode)
    if key not in cache:
        if rag_engine is None:
            cache[key] = f"The cancellation engine is not installed ({CANCELLATION_ENGINE_ERROR})."
        else:
            with st.spinner(f"Researching how to cancel {display_name(asset)}..."):
                try:
                    _, cancel_policy = rag_engine.search_web_cancellation_policy(
                        asset.service,
                        sub_type=sub_type,
                        mode=mode,
                        service_address=asset.service_address or None,
                    )
                    cache[key] = cancel_policy
                except Exception as exc:
                    cache[key] = str(exc)
    return cache[key]


def _set_state(key: str, value) -> None:
    """Button callback: runs before the dialog re-renders, so the new state shows immediately."""
    if value is None:
        st.session_state.pop(key, None)
    else:
        st.session_state[key] = value


def _needs_plan(policy: CancelPolicy) -> bool:
    """True when the cancellation rules differ per plan and the researched plan was not specific."""
    return bool(policy.action_payload.get("requires_sub_type_selection"))


def _letter_kind(policy: CancelPolicy) -> Optional[str]:
    """'letter' or 'email' when the provider needs a written notice, else None."""
    channel = policy.action_payload.get("primary_channel")
    if channel == "registered_letter":
        return "letter"
    if channel == "email" or (not channel and policy.execution_method == "email_notice"):
        return "email"
    return None


def _letter_pdf_bytes(sender_name: str, provider_name: str, provider_address: str, letter_body: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "cancellation.pdf")
        pdf_generator.create_cancellation_pdf(
            sender_name=sender_name,
            provider_name=provider_name,
            provider_address=provider_address,
            letter_body=letter_body,
            output_path=pdf_path,
        )
        return Path(pdf_path).read_bytes()


def _split_subject(letter: str, fallback: str):
    """Splits a 'Betreff: ...' first line off the generated letter for use as email subject."""
    lines = letter.strip().splitlines()
    if lines and lines[0].lower().startswith("betreff:"):
        return lines[0].split(":", 1)[1].strip(), "\n".join(lines[1:]).strip()
    return fallback, letter.strip()


def render_plan_picker(asset: Asset, policy: CancelPolicy, plan_key: str) -> None:
    """Asks which plan the user has: pick a researched option, type a name, or 'I don't know'."""
    ui.notice(f"The cancellation rules differ between {display_name(asset)}'s plans. Which plan do you have?", "navy")

    options = policy.action_payload.get("sub_type_options") or []
    if options:
        with st.container(horizontal=True):
            for idx, option in enumerate(options):
                st.button(option, key=f"cxl_plan_opt_{asset.id}_{idx}",
                          on_click=_set_state, args=(plan_key, {"plan": option}))

    typed_key = f"cxl_plan_typed_{asset.id}"

    def search_typed_plan() -> None:
        typed = (st.session_state.get(typed_key) or "").strip()
        if typed:
            _set_state(plan_key, {"plan": typed})

    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Or enter your plan name", key=typed_key, placeholder="e.g. Swisscom blue Mobile M")
        st.button("Search this plan", icon=":material/search:", key=f"cxl_plan_search_{asset.id}",
                  on_click=search_typed_plan)

    st.button("I don't know my plan", type="tertiary", key=f"cxl_plan_unknown_{asset.id}",
              on_click=_set_state, args=(plan_key, {"unknown": True}))


def render_written_notice(
    asset: Asset, policy: CancelPolicy, sub_type: str, kind: str, mode: str = "during_life", deceased_name: str = ""
) -> None:
    """Button that writes the cancellation email text or letter PDF, and shows the result.

    Same form for owner and executor; after a death the letter also names the deceased
    (from the executor page's "Name of the deceased" field, if filled in).
    """
    name = display_name(asset)
    mailing_address = policy.action_payload.get("mailing_address") or ""
    if kind == "email":
        ui.section_label("Cancellation email")
        st.caption(f"{name} accepts cancellations by email. Generate a ready-to-send text.")
    else:
        ui.section_label("Cancellation letter")
        st.caption(f"{name} requires a written cancellation letter. Generate a ready-to-sign PDF.")

    n1, n2 = st.columns(2)
    sender_name = n1.text_input("Your full name", key=f"cxl_sender_{mode}_{asset.id}")
    contract_id = n2.text_input("Customer or contract number", value=asset.username, key=f"cxl_contract_{mode}_{asset.id}")
    ready = bool(sender_name.strip())

    notices = st.session_state.setdefault("generated_cancel_notices", {})
    notice_key = (asset.id, mode)
    if st.button(
        "Write cancellation email" if kind == "email" else "Generate cancellation letter",
        type="primary",
        icon=":material/edit:" if kind == "email" else ":material/description:",
        disabled=not ready,
        help=None if ready else "Enter your name first.",
        key=f"cxl_write_{mode}_{asset.id}",
    ):
        with st.spinner("Writing your cancellation..."):
            try:
                letter = rag_engine.generate_cancellation_letter(
                    provider_name=asset.service,
                    sub_type=sub_type,
                    person_name=sender_name.strip(),
                    contract_id=contract_id.strip() or "-",
                    mode=mode,
                    cancel_policy=policy,
                    deceased_name=deceased_name.strip() or None,
                )
                pdf_bytes = None
                if kind == "letter":
                    pdf_bytes = _letter_pdf_bytes(sender_name.strip(), asset.service, mailing_address or "Kundenservice", letter)
                notices[notice_key] = {"kind": kind, "text": letter, "pdf": pdf_bytes}
            except Exception as exc:
                ui.error_with_details("The cancellation could not be written. Try again.", exc)

    notice = notices.get(notice_key)
    if not notice or notice["kind"] != kind:
        return

    if kind == "email":
        subject, body = _split_subject(notice["text"], f"Kündigung {asset.service} ({contract_id})")
        ui.definition_list({"Send to": policy.support_email, "Subject": subject})
        st.text_area("Email text", body, height=260, key=f"cxl_email_text_{mode}_{asset.id}")
        if policy.support_email:
            st.link_button(
                "Open in mail app",
                f"mailto:{policy.support_email}?subject={quote(subject)}&body={quote(body)}",
                icon=":material/mail:",
            )
    else:
        ui.definition_list({"Send by registered mail to": mailing_address.replace("\n", ", ")})
        st.text_area("Letter text", notice["text"], height=260, key=f"cxl_letter_text_{mode}_{asset.id}")
        st.download_button(
            "Download letter (PDF)",
            data=notice["pdf"],
            file_name=f"Kuendigung_{asset.service}.pdf".replace(" ", "_"),
            mime="application/pdf",
            type="primary",
            icon=":material/download:",
            on_click="ignore",
            key=f"cxl_pdf_{mode}_{asset.id}",
        )


def render_researched_cancellation(
    asset: Asset,
    policy: CancelPolicy,
    sub_type: str,
    general_policy: bool = False,
    mode: str = "during_life",
    deceased_name: str = "",
) -> None:
    """Shows only what the RAG engine researched: facts, steps, links, contacts, documents.

    `general_policy` marks a plan-independent answer (user doesn't know their plan): the link to
    the provider's policy is then always shown so the user can look up their plan's details.
    """
    name = display_name(asset)
    payload = policy.action_payload
    ui.definition_list({
        "Cancel via": CHANNEL_LABELS.get(payload.get("primary_channel")),
        "Notice period": payload.get("notice_period"),
        "Minimum term": payload.get("minimum_contract_duration"),
        "Legal basis": payload.get("legal_basis"),
    })

    enough_steps = len(policy.steps) >= MIN_STEPS_FOR_GUIDE
    if policy.steps:
        ui.section_label("Steps")
        if enough_steps:
            ui.numbered(policy.steps)
        else:
            st.markdown("\n".join(f"- {step}" for step in policy.steps))

    policy_url = payload.get("policy_url") or policy.target_url
    if general_policy or not enough_steps:
        if general_policy:
            reason = f"This is {name}'s general policy; the exact rules depend on your plan."
        else:
            reason = "Not enough details were found for step-by-step instructions."
        if policy_url:
            ui.notice(f"{reason} See {name}'s official policy for details.", "amber")
        else:
            ui.notice(f"{reason} No link to {name}'s policy was found.", "amber")

    with st.container(horizontal=True):
        if policy.target_url:
            st.link_button("Open cancellation page", policy.target_url, type="primary", icon=":material/open_in_new:")
        if policy_url and policy_url != policy.target_url and (general_policy or not enough_steps):
            st.link_button(f"{name} cancellation policy", policy_url, icon=":material/description:")
        if policy.support_email:
            st.link_button(f"Email {policy.support_email}", f"mailto:{policy.support_email}", icon=":material/mail:")

    contacts = {
        "Email": policy.support_email,
        "Phone": payload.get("contact_phone"),
        "Postal address": (payload.get("mailing_address") or "").replace("\n", ", "),
    }
    if any(contacts.values()):
        ui.section_label("Contact")
        ui.definition_list(contacts)

    if policy.required_documents:
        ui.section_label("Documents")
        st.markdown("\n".join(f"- {doc}" for doc in policy.required_documents))

    kind = _letter_kind(policy)
    if kind:
        render_written_notice(asset, policy, sub_type, kind, mode, deceased_name)


@st.dialog("Cancellation guide", width="large")
def cancellation_guide_dialog(asset: Asset, mode: str = "during_life", deceased_name: str = ""):
    """Researches how to cancel on open and shows only that, plus the email or letter when needed.

    Owner and executor get the same dialog. Only the research differs: the owner opens it in
    "during_life" mode, the executor view in "after_death" mode (rules for a deceased person's contract).
    """
    ui.section_label(display_name(asset), first=True)

    # Research runs with the account's plan (if known). When the rules differ per plan, the user
    # picks or types a plan (researched again) or continues with the general policy.
    sub_type = _asset_sub_type(asset)
    plan_key = f"cxl_plan_{mode}_{asset.id}"
    choice = st.session_state.get(plan_key)  # None, {"plan": name} or {"unknown": True}
    researched = researched_cancel_policy(asset, sub_type, mode)
    general_policy = False

    if isinstance(researched, CancelPolicy) and _needs_plan(researched):
        if choice and choice.get("plan"):
            plan_result = researched_cancel_policy(asset, choice["plan"], mode)
            if isinstance(plan_result, CancelPolicy) and _needs_plan(plan_result):
                ui.notice(f"No specific policy was found for the plan '{choice['plan']}'. Pick another option.", "amber")
                choice = None
            else:
                sub_type, researched = choice["plan"], plan_result
        elif choice and choice.get("unknown"):
            general_policy = True

        if not choice:
            render_plan_picker(asset, researched, plan_key)
            researched = None
        else:
            with st.container(horizontal=True, vertical_alignment="center"):
                ui.definition_list({"Plan": "Unknown, general policy" if general_policy else sub_type})
                st.button("Change plan", type="tertiary", key=f"cxl_change_plan_{asset.id}",
                          on_click=_set_state, args=(plan_key, None))

    if isinstance(researched, CancelPolicy):
        render_researched_cancellation(asset, researched, sub_type, general_policy, mode, deceased_name)
    elif researched is not None:
        ui.notice(f"The cancellation policy could not be researched: {researched}", "red")
        if rag_engine is not None:
            st.button("Try again", icon=":material/refresh:", key=f"cxl_retry_{asset.id}",
                      on_click=lambda: st.session_state.researched_cancel_policies.pop((asset.id, sub_type, mode), None))

    st.divider()
    keep_clicked, confirm_clicked = dialog_footer("Keep active", "Mark as cancelled", f"dlg_cancel_{mode}_{asset.id}")
    if keep_clicked:
        st.rerun()
    if confirm_clicked:
        asset.status = "Cancelled"
        asset.cancel_policy.status = "Completed"
        notify(f"{display_name(asset)} marked as cancelled.")
        st.rerun()

    # Executors can flag an account but not remove it (see the executor view)
    if mode == "during_life" and st.button("Added by mistake? Remove it instead", type="tertiary",
                                           key=f"dlg_switch_remove_{asset.id}"):
        switch_dialog("remove", asset)


@st.dialog("Remove from vault")
def remove_account_dialog(asset: Asset):
    """Removes a wrongly added account from tracking; executors still see it in the audit log."""
    ui.definition_list({
        "Service": display_name(asset),
        "Account": asset.username or "Not recorded",
        "Per month": monthly_display(asset),
    })
    ui.notice(
        f"Removing only stops tracking. It does not cancel billing with {display_name(asset)}; "
        "cancel a paid plan on the provider's site.",
        "amber",
    )
    st.markdown(
        "- The account moves to *Removed* and no longer counts towards monthly costs.\n"
        "- You can restore it at any time.\n"
        "- Executors still see it, so nothing can be hidden from the estate."
    )

    keep_clicked, remove_clicked = dialog_footer("Keep", "Remove", f"dlg_remove_{asset.id}")
    if keep_clicked:
        st.rerun()
    if remove_clicked:
        asset.status = "Removed"
        notify(f"{display_name(asset)} removed. Restore it under Show removed.")
        st.rerun()

    if st.button("Cancel the subscription instead", type="tertiary", key=f"dlg_switch_cancel_{asset.id}"):
        switch_dialog("cancel", asset)


def switch_dialog(kind: str, asset: Asset) -> None:
    """Streamlit cannot open a dialog from inside another one: close this one and open the
    other on the next run."""
    st.session_state.switch_dialog = (kind, asset.id)
    st.rerun()


_switch = st.session_state.pop("switch_dialog", None)
if _switch:
    _target = next((a for a in current_assets if a.id == _switch[1]), None)
    if _target is not None:
        (remove_account_dialog if _switch[0] == "remove" else cancellation_guide_dialog)(_target)


# =============================================================================
# 4. Asset lists
# =============================================================================
ROW = [3.2, 1.6, 1.4, 1.3, 0.8]
EXECUTOR_ROW = [3.2, 1.6, 1.3, 0.8]
POLICY_ROW = [2.6, 1.1, 1.1, 1.1, 1.1, 1.2, 0.7]
# Column heads for the crawler's answers; the full wording is in each row's details.
POLICY_COLUMNS = {
    "Owner can name a successor": "Successor",
    "Heirs can request access": "Heir access",
    "Subscription or balance covered": "Balance covered",
    "Proof required": "Proof needed",
}


def has_heir(asset: Asset) -> bool:
    """A responsible heir exists only when the owner's wish is to pass the account on and they named one."""
    return asset.wish == "Pass to heir" and asset.heir.strip() not in ("", "Unassigned")


def list_header(labels: List[str], widths: List[float] = ROW) -> None:
    with st.container(key="list_head"):
        cols = st.columns(widths, vertical_alignment="center")
        for col, label in zip(cols, labels):
            with col:
                ui.section_label(label, first=True)


def owner_status(asset: Asset) -> str:
    if asset.status in ("Active", "Pending Review") and not asset.user_verified:
        return asset.review_label
    return status_text(asset.status)


def close_action_label(asset: Asset) -> str:
    if asset.has_type("Subscription"):
        return "Cancel subscription"
    if asset.has_type("Social Media"):
        return "Close profile"
    if asset.has_type("Cloud Storage"):
        return "Cancel plan"
    return "Close account"


def confirm_asset(asset: Asset) -> None:
    asset.user_verified = True
    notify(f"{display_name(asset)} confirmed.")


def reject_asset(asset: Asset) -> None:
    asset.status = "Removed"
    notify(f"{display_name(asset)} moved to Removed.")


def set_status(asset: Asset, status: str, message: Optional[str] = None) -> None:
    asset.status = status
    if status == "Active":
        asset.cancel_policy.status = "Pending"
    if message:
        notify(message)


def wish_picker(asset: Asset, key: str) -> None:
    """The owner's wish as a dropdown, plus a short text for "Other". A change is saved to data/wishes.json."""
    current, detail = split_wish(asset.wish)
    options = WISH_OPTIONS + ([current] if current not in WISH_OPTIONS else [])
    choice = st.selectbox(
        "Your wish after death",
        options,
        index=options.index(current),
        format_func=lambda option: option or "Not set",
        key=f"wish_{key}_{current}",  # the wish in the key rebuilds the widget after an edit elsewhere
    )
    if choice == "Other":
        detail = st.text_input("Your wish, in a few words", value=detail, max_chars=60,
                               placeholder="e.g. give the photos to my sister",
                               label_visibility="collapsed", key=f"wish_text_{key}_{asset.wish}")
    wish = join_wish(choice, detail)
    if wish != asset.wish:
        asset.wish = wish
        save_wishes(st.session_state.assets)
        st.rerun()
    if choice == "Pass to heir":
        heir = st.text_input("Responsible heir (optional)", value=asset.heir if has_heir(asset) else "",
                             placeholder="e.g. Alex", key=f"heir_{key}")
        asset.heir = heir.strip() or "Unassigned"


def owner_details(asset: Asset, key: str) -> None:
    """Definition list, evidence for detected items, and the contextual actions."""
    facts: Dict[str, object] = {"Account": asset.username or "Not recorded", "Website": asset.service_address}
    facts.update(asset_facts(asset))
    if asset.notes and not asset.evidence and asset.user_verified:
        facts["Notes"] = asset.notes
    ui.definition_list(facts)
    # Right above the wish: what the provider allows is what the wish has to work with.
    policy_block(asset, key, "What the provider does after death",
                 note=AI_NOTICE if asset.death_policy.ai_generated else None)
    wish_picker(asset, key)

    detected = not asset.user_verified and asset.status != "Removed"
    if asset.evidence or asset.confidence_reasons:
        ui.evidence_panel(asset)
        if asset.evidence:
            with st.expander(f"View evidence ({len(asset.evidence)})"):
                ui.evidence_table(asset)

    portal = asset.cancel_policy.target_url or asset.service_address
    with st.container(horizontal=True, vertical_alignment="center"):
        if asset.status == "Removed":
            st.button("Restore", type="primary", key=f"{key}_restore", on_click=set_status,
                      args=(asset, "Active", f"{display_name(asset)} restored."))
            if st.button("Cancellation guide", type="tertiary", key=f"{key}_guide"):
                cancellation_guide_dialog(asset)
            return

        if detected:
            st.button("Confirm", type="primary", key=f"{key}_confirm", on_click=confirm_asset, args=(asset,))
        elif asset.status in CLOSED:
            st.button("Reactivate", key=f"{key}_react", on_click=set_status,
                      args=(asset, "Active", f"{display_name(asset)} marked as active."))
        elif st.button(close_action_label(asset), type="primary", key=f"{key}_close"):
            cancellation_guide_dialog(asset)

        if portal and portal.startswith("http"):
            st.link_button("Open provider site", portal, icon=":material/open_in_new:")
        if detected:
            st.button("Not mine", type="tertiary", key=f"{key}_reject", on_click=reject_asset, args=(asset,))
        else:
            if asset.status in CLOSED and st.button("Cancellation guide", type="tertiary", key=f"{key}_guide"):
                cancellation_guide_dialog(asset)
            if st.button("Remove", type="tertiary", key=f"{key}_remove"):
                remove_account_dialog(asset)


def owner_rows(assets: List[Asset], prefix: str) -> None:
    list_header(["Service", "Category", "Per month", "Status", ""])
    for asset in assets:
        row_key = f"{prefix}_{asset.id}"
        with st.container(key=f"row_{row_key}"):
            is_open = row_key in st.session_state.open_rows
            # The whole row toggles the details: the button stretches over it (see styles.py).
            with st.container(key=f"rowhead_{row_key}"):
                c1, c2, c3, c4, c5 = st.columns(ROW, vertical_alignment="center")
                with c1:
                    ui.cell(display_name(asset), subtitle(asset), strong=True)
                with c2:
                    ui.cell(categories_display(asset))
                with c3:
                    value = value_display(asset)
                    ui.cell(monthly_display(asset), f"Value {value}" if value else None)
                with c4:
                    st.markdown(ui.status_label(owner_status(asset)), unsafe_allow_html=True)
                with c5:
                    st.button("Hide" if is_open else "Details", type="tertiary", key=f"toggle_{row_key}",
                              on_click=toggle_row, args=(row_key,))
            if is_open:
                with st.container(key=f"details_{row_key}"):
                    owner_details(asset, row_key)


def flag_asset(asset: Asset, flagged: bool) -> None:
    asset.status = "Wrongly Attributed" if flagged else "Active"
    notify(f"{display_name(asset)} flagged as not part of the estate." if flagged else f"{display_name(asset)} returned to the estate.")


def set_done(asset: Asset, key: str) -> None:
    done = st.session_state[key]
    asset.status = "Completed" if done else "In Progress"
    asset.cancel_policy.status = "Completed" if done else "In Progress"


def executor_details(asset: Asset, key: str) -> None:
    death_pol, cancel_pol = asset.death_policy, asset.cancel_policy
    is_flagged = asset.status == "Wrongly Attributed"
    if is_flagged:
        ui.notice("Flagged as not part of the estate. It stays in the audit log.", "amber")
    elif asset.status == "Removed":
        ui.notice("Removed by the owner. Kept in the records so no asset can be hidden.", "amber")

    facts: Dict[str, object] = {"Account": asset.username or "Not recorded", "Website": asset.service_address}
    facts.update(asset_facts(asset))
    if has_heir(asset):
        facts["Responsible heir"] = asset.heir
    if asset.wish:
        facts["Owner's wish"] = asset.wish
    ui.definition_list(facts)

    render_policy_summary(death_pol)

    portal = death_pol.official_portal_url or cancel_pol.target_url or asset.service_address
    with st.container(horizontal=True, vertical_alignment="center"):
        if not is_flagged and asset.status not in CLOSED and st.button(
            close_action_label(asset), type="primary", key=f"{key}_exec_cancel"
        ):
            # The executor page's "Name of the deceased" field (key "deceased_name") prefills the letter
            cancellation_guide_dialog(
                asset, mode="after_death", deceased_name=st.session_state.get("deceased_name") or ""
            )
        done_key = f"exec_done_{key}"
        st.session_state[done_key] = asset.status in CLOSED
        st.checkbox("Action complete", key=done_key, disabled=is_flagged, on_change=set_done, args=(asset, done_key))
        if portal and portal.startswith("http"):
            st.link_button(policy_link_label(death_pol), portal, icon=":material/open_in_new:")
        if is_flagged:
            st.button("Return to estate", type="tertiary", key=f"exec_reattrib_{key}",
                      on_click=flag_asset, args=(asset, False))
        else:
            st.button("Flag as not part of estate", type="tertiary", key=f"exec_wrong_{key}",
                      on_click=flag_asset, args=(asset, True),
                      help="Use this if the account did not belong to the deceased. It stays in the audit log.")


def executor_rows(assets: List[Asset], prefix: str) -> None:
    """Worklist, largest monthly charge first. Closed items keep their place so rows don't jump when ticked."""
    list_header(["Service", "Per month", "Status", ""], EXECUTOR_ROW)
    for asset in sorted(assets, key=lambda a: (-monthly_cost_chf(a), display_name(a).lower())):
        row_key = f"{prefix}_{asset.id}"
        with st.container(key=f"row_{row_key}"):
            is_open = row_key in st.session_state.open_rows
            # The whole row toggles the details: the button stretches over it (see styles.py).
            with st.container(key=f"rowhead_{row_key}"):
                c1, c2, c3, c4 = st.columns(EXECUTOR_ROW, vertical_alignment="center")
                with c1:
                    ui.cell(display_name(asset), subtitle(asset), strong=True)
                with c2:
                    ui.cell(monthly_display(asset), categories_display(asset))
                with c3:
                    st.markdown(ui.status_label(status_text(asset.status)), unsafe_allow_html=True)
                with c4:
                    st.button("Hide" if is_open else "Details", type="tertiary", key=f"toggle_{row_key}",
                              on_click=toggle_row, args=(row_key,))
            if is_open:
                with st.container(key=f"details_{row_key}"):
                    executor_details(asset, row_key)


def lookup_label(pol: DeathPolicy) -> Optional[str]:
    """The look-up button's text, or None while the crawler's result is current."""
    if not pol.ai_generated:
        return "Look up with AI"
    if is_stale(pol.source_checked):
        return f"Refresh (checked {days_since_checked(pol.source_checked)} days ago)"
    if pol.policy_found is False:
        return "Try again"
    return None


def policy_block(asset: Asset, key: str, title: str, note: Optional[str] = None) -> None:
    """The provider's policy after death, with its source link and the look-up button right below."""
    pol = asset.death_policy
    tone = "muted" if not pol.ai_generated else ("green" if pol.policy_found else "amber")
    meta = None
    if pol.source_checked:
        meta = f"Checked {pol.source_checked}" + (", old" if is_stale(pol.source_checked) else "")
    answers = policy_answers(pol) if pol.ai_generated and pol.policy_found else {}
    link = pol.official_portal_url or asset.cancel_policy.target_url or asset.service_address
    host, label = provider_key(asset.service_address), lookup_label(pol)
    with st.container(key=f"polblock_{key}"):
        ui.policy_panel(title, (policy_source(pol), tone), pol.summary, answers, meta, note)
        with st.container(horizontal=True, vertical_alignment="center"):
            if link and link.startswith("http"):
                st.link_button(policy_link_label(pol), link, type="tertiary", icon=":material/open_in_new:")
            if host and label and st.button(label, type="tertiary", icon=":material/travel_explore:",
                                            key=f"{key}_lookup",
                                            help="Searches the provider's website, 10 to 40 seconds. "
                                                 "Needs the Apertus token in .env."):
                look_up_policy(asset, host)


def look_up_policy(asset: Asset, host: str) -> None:
    with st.spinner(f"Searching {host} for its legacy policy"):
        problem = refresh_legacy_policy(asset.service_address)
    if problem:
        ui.notice(problem, "red")
        return
    record = legacy_record(asset.service_address)
    for other in st.session_state.assets:
        if provider_key(other.service_address) == host:
            other.death_policy = apply_legacy_record(other.death_policy, record)
    st.rerun()


def legacy_policy_view(assets: List[Asset]) -> None:
    """What each provider says happens to an account after death, gathered by the AI crawler."""
    ui.notice("AI-generated summaries. " + AI_NOTICE, "amber")
    if not assets:
        ui.muted("No accounts here.")
        return
    list_header(["Service", *POLICY_COLUMNS.values(), "Checked", ""], POLICY_ROW)
    for asset in assets:
        pol = asset.death_policy
        row_key = f"pol_{asset.id}"
        with st.container(key=f"row_{row_key}"):
            is_open = row_key in st.session_state.open_rows
            with st.container(key=f"rowhead_{row_key}"):
                cols = st.columns(POLICY_ROW, vertical_alignment="center")
                with cols[0]:
                    ui.cell(display_name(asset), policy_source(pol), strong=True)
                answers = policy_answers(pol) if pol.ai_generated and pol.policy_found else {}
                for col, label in zip(cols[1:5], POLICY_COLUMNS):
                    answer = answers.get(label, "–")
                    col.markdown(ui.status_label(answer, ui.ANSWER_TONES.get(answer, "muted")),
                                 unsafe_allow_html=True)
                with cols[5]:
                    ui.cell(pol.source_checked or "Not checked",
                            "Refresh due" if is_stale(pol.source_checked) else None)
                with cols[6]:
                    st.button("Hide" if is_open else "Details", type="tertiary", key=f"toggle_{row_key}",
                              on_click=toggle_row, args=(row_key,))
            if is_open:
                with st.container(key=f"details_{row_key}"):
                    policy_block(asset, row_key, "What the provider does after death")


def inventory_csv(assets: List[Asset]) -> str:
    """Basic export for the Share step."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Service", "Account", "Website", "Category", "Per month", "Responsible heir", "Status"])
    for a in assets:
        writer.writerow([a.service, a.username, a.service_address, categories_display(a), monthly_display(a),
                         a.heir if has_heir(a) else "", a.status])
    return out.getvalue()


# =============================================================================
# 5. Discovery
# =============================================================================
def _step_key(message: str) -> str:
    """'Reading emails (12/80)' and 'Reading emails (13/80)' are the same step."""
    return re.sub(r"\s*\(?\d+/\d+\)?", "", message).strip()


def run_scan(source: str, use_llm: bool = True, upload=None,
             on_success: Optional[Callable[[], None]] = None) -> None:
    """Runs the subscription finder on one source and adds new findings to the vault.

    `source` is "demo" (sample dataset), "gmail", or "file" (upload, plus Gmail if connected).
    `upload` overrides the Discover page's file; `on_success` runs just before the final rerun.
    """
    st.session_state.pop("scan_llm_error", None)
    placeholder = st.empty()
    steps: List[List[str]] = []

    def progress(message: str, fraction: float) -> None:
        key = _step_key(message)
        if key == "Done":
            for step in steps:
                step[1] = "done"
        elif steps and _step_key(steps[-1][0]) == key:
            steps[-1][0] = message
        else:
            for step in steps:
                step[1] = "done"
            steps.append([message, "current"])
        ui.step_list([tuple(s) for s in steps], placeholder)

    ui.step_list([("Starting", "current")], placeholder)
    gmail = st.session_state.get("gmail_credentials") if source in ("gmail", "file") else None
    if source == "demo":
        upload, filename, source_label = DEMO_DATASET.read_bytes(), DEMO_DATASET.name, "Demo dataset"
    elif source == "file":
        upload = upload or st.session_state.get("disc_page_file_uploader")
        filename, source_label = None, "Uploaded file"
    else:
        upload, filename, source_label = None, None, "Gmail"

    try:
        result = parse_and_extract(upload, filename, gmail_credentials=gmail, use_llm=use_llm, progress=progress)
    except DiscoveryInputError as exc:
        placeholder.empty()
        ui.notice(str(exc), "red")
        return
    except LLMConfigError as exc:
        placeholder.empty()
        st.session_state.scan_llm_error = (source, str(exc))
        st.rerun()
    except ReconnectRequired:
        placeholder.empty()
        st.session_state.pop("gmail_credentials", None)
        ui.notice("Gmail access has expired or was revoked. Connect Gmail again, then rescan.", "red")
        return
    except MalformedFinderResult as exc:
        placeholder.empty()
        ui.error_with_details("The scan returned an unexpected result, so nothing was added. Try again.", exc)
        return
    except Exception as exc:
        placeholder.empty()
        ui.error_with_details("The scan failed. Try again; if it keeps failing, check the finder setup.", exc)
        return

    by_key = {a.unique_key: a for a in st.session_state.assets}
    found_ids, added = [], 0
    for asset in result.extracted_assets:
        existing = by_key.get(asset.unique_key)
        if existing is None:
            st.session_state.assets.append(asset)
            by_key[asset.unique_key] = asset
            existing = asset
            added += 1
        found_ids.append(existing.id)

    st.session_state.scanned = True
    st.session_state.last_scan = {
        "source": source_label,
        "ids": found_ids,
        "added": added,
        "rules_only": not use_llm,
        "notes": result.notes or "",
        "steps": [s[0] for s in steps if _step_key(s[0]) != "Done"],
    }
    if on_success:
        on_success()
    st.rerun()


def queue_demo_scan() -> None:
    st.session_state.pending_scan = "demo"
    st.session_state.active_page = "Discover"


# =============================================================================
# GUIDED ONBOARDING (only with DLV_ONBOARDING=1)
# =============================================================================
REVEAL_SECONDS = 7
SIGN_IN_URL_MAX_AGE = 540  # the server forgets a started Google login after 10 minutes


def set_onboarding(step: str) -> None:
    st.session_state.onboarding = step
    st.session_state.pop("onb_reveal_shown", None)


def start_analysis() -> None:
    # Keep the file: Streamlit drops an uploader's value once the widget is no longer drawn.
    st.session_state.onb_file = st.session_state.get("onb_statement")
    set_onboarding("analyse")


def gmail_sign_in_url():
    """One Google sign-in link per session, renewed before the server forgets it.
    Returns (url, None) or (None, error message)."""
    cached = st.session_state.get("onb_sign_in")
    if cached and time.time() - cached[1] < SIGN_IN_URL_MAX_AGE:
        return cached[0], None
    resp = connect_email_provider(provider="gmail")
    if not resp["success"]:
        return None, resp["message"]
    st.session_state.onb_sign_in = (resp["auth_url"], time.time())
    return resp["auth_url"], None


def onboarding_landing() -> None:
    ui.hero(
        "Know what you leave behind.",
        "Find your digital accounts and subscriptions so your heirs don't have to.",
        eyebrow="Digital estate planning",
    )
    with st.container(key="cta_orange"):
        st.button("Get started", type="primary", key="onb_start", on_click=set_onboarding, args=("connect",))
    ui.muted("Takes about a minute. Read-only access, nothing is stored.")
    ui.step_rule(0)


def onboarding_connect() -> None:
    ui.step_rule(1)
    ui.hero("Connect your sources", "The more sources you add, the more complete the picture.", size="l")
    oauth_message = st.session_state.pop("oauth_message", None)
    if oauth_message:
        kind, text = oauth_message
        ui.notice(text, "green" if kind == "success" else "red")

    connected = bool(st.session_state.get("gmail_credentials"))
    gmail_col, bank_col = st.columns(2, gap="medium")
    with gmail_col, st.container(border=True, height="stretch", key="src_gmail"):
        ui.section_label("Step 1 · Email", first=True)
        st.subheader("Gmail", anchor=False)
        ui.muted("Read-only access to billing emails. They are processed in memory and never stored.")
        if connected:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(ui.status_label("Connected", "green"), unsafe_allow_html=True, width="content")
                st.button("Disconnect", type="tertiary", key="onb_disconnect",
                          on_click=lambda: st.session_state.pop("gmail_credentials", None))
        else:
            url, error = gmail_sign_in_url()
            if url:
                st.link_button("Connect Gmail", url, icon=":material/mail:")
                st.caption("Google opens in a new tab and brings you back here.")
            else:
                ui.notice(error, "red")

    with bank_col, st.container(border=True, height="stretch", key="src_statement"):
        ui.section_label("Step 2 · Bank", first=True)
        st.subheader("Bank statement", anchor=False)
        ui.muted("A transaction export from your bank, as JSON or JSONL. It is read in memory only.")
        statement = st.file_uploader("Bank statement", type=["jsonl", "json"], key="onb_statement",
                                     label_visibility="collapsed")

    ready = (["Gmail"] if connected else []) + ([statement.name] if statement is not None else [])
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("Analyse", type="primary", key="onb_analyse", disabled=not ready, on_click=start_analysis)
        st.caption(f"Ready: {' and '.join(ready)}" if ready else "Connect Gmail or upload a statement to continue.")


def onboarding_analyse() -> None:
    ui.step_rule(2)
    ui.hero("Analysing your footprint", "We look for recurring payments and the accounts behind them.", size="l")
    statement = st.session_state.get("onb_file")
    source = "file" if statement is not None else "gmail"

    llm_error = st.session_state.get("scan_llm_error")
    if llm_error:
        ui.notice(f"The AI model is not configured ({llm_error[1]}). You can analyse with rules only; "
                  "names and confidence are less precise.", "amber")
        with st.container(horizontal=True, vertical_alignment="center"):
            rules_only = st.button("Analyse with rules only", type="primary", key="onb_rules_only")
            st.button("Back to sources", type="tertiary", key="onb_back_llm", on_click=set_onboarding, args=("connect",))
        if rules_only:
            run_scan(source, use_llm=False, upload=statement, on_success=lambda: set_onboarding("reveal"))
        return

    run_scan(source, upload=statement, on_success=lambda: set_onboarding("reveal"))
    # Only reached when the scan failed; run_scan has said why.
    st.button("Back to sources", key="onb_back", on_click=set_onboarding, args=("connect",))


def onboarding_reveal() -> None:
    ui.step_rule(3)
    found = [a for a in st.session_state.assets if a.status != "Removed"]
    monthly = calculate_metrics(found)["active_monthly_spend_chf"]
    needs_review = sum(1 for a in found if a.review_label == "Needs review")
    # Largest monthly cost first: the finder files nearly everything under Subscriptions, so grouping by
    # category would leave one long column.
    costs = {a.id: monthly_cost_chf(a) for a in found}
    ranked = sorted(found, key=lambda a: (-costs[a.id], display_name(a).lower()))
    items = [(display_name(a), f"{chf(costs[a.id])} / mo" if costs[a.id] else categories_display(a)) for a in ranked]
    ui.reveal(len(found), monthly, needs_review, items, REVEAL_SECONDS)
    if st.session_state.yearly_reminder:
        today = date.today()
        ui.muted(f"Yearly reminder on: we'll ask you to update this in {today:%B} {today.year + 1}.")
    with st.container(key="cta_link"):
        st.button("Open my inventory", type="tertiary", key="onb_open", on_click=set_onboarding, args=("done",))
    advance_after_reveal()


@st.fragment(run_every=REVEAL_SECONDS)
def advance_after_reveal() -> None:
    """Opens the inventory on the fragment's first timed rerun, when the countdown line is full."""
    if st.session_state.get("onb_reveal_shown"):
        set_onboarding("done")
        st.rerun()
    st.session_state.onb_reveal_shown = True


if st.session_state.onboarding != "done":
    # While the scan runs, the Connect screen's leftovers would otherwise stay visible.
    ui.inject_onboarding_styles(hide_stale=st.session_state.onboarding == "analyse")
    ui.topbar()
    {
        "landing": onboarding_landing,
        "connect": onboarding_connect,
        "analyse": onboarding_analyse,
        "reveal": onboarding_reveal,
    }.get(st.session_state.onboarding, onboarding_landing)()
    st.stop()


# =============================================================================
# 2. Frame: role band, sidebar navigation
# =============================================================================
# The view switch sits above every page, not in the sidebar: switching changes the whole app.
ROLES = {
    "Owner": ("Owner view", "You keep the inventory up to date for your heirs.", "Your inventory",
              {"Assets": "Inventory", "Discover": "Find accounts"}),
    "Executor": ("Executor view", "The owner's inventory, released to you after their death.", "Estate settlement",
                 {"Assets": "Worklist", "Discover": "Find accounts"}),
}

with st.container(key="role_bar", horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
    view_name, view_text, _, _ = ROLES[st.session_state.get("role") or "Owner"]
    ui.role_banner(view_name, view_text)
    role = st.segmented_control("View as", list(ROLES), default="Owner", required=True, key="role",
                                label_visibility="collapsed", width="content")

_, _, sidebar_caption, nav_labels = ROLES[role]
if role == "Executor":
    ui.inject_executor_styles()
ui.wordmark(sidebar_caption)
# One radio per role: relabelling a single radio makes Streamlit draw it with nothing selected.
# `active_page` stays the source of truth, so buttons elsewhere can switch pages.
nav_key = f"nav_{role.lower()}"
st.session_state[nav_key] = st.session_state.active_page
with st.sidebar.container(key="nav"):
    st.radio("Navigation", PAGES, key=nav_key, format_func=nav_labels.get, label_visibility="collapsed",
             on_change=lambda: go_to(st.session_state[nav_key]))


def show_to_review() -> None:
    st.session_state.owner_filter = "To review"


active_pool = [a for a in current_assets if a.status != "Removed"]
removed_list = [a for a in current_assets if a.status == "Removed"]
page = st.session_state.active_page


# =============================================================================
# PAGE: INVENTORY (owner)
# =============================================================================
if page == "Assets" and role == "Owner":
    unconfirmed = [a for a in active_pool if not a.user_verified]
    scanned = st.session_state.get("scanned")

    action_col = ui.page_header("Accounts and subscriptions", eyebrow="Inventory")
    with action_col:
        with st.container(horizontal=True, horizontal_alignment="right"):
            if not scanned:
                st.button("Scan my digital footprint", type="primary", on_click=queue_demo_scan)
            elif unconfirmed:
                st.button(f"Review {len(unconfirmed)} detected", type="primary", key="btn_review",
                          on_click=show_to_review)
            if st.button("Add asset", type="secondary" if not scanned or unconfirmed else "primary",
                         icon=":material/add:", key="btn_add_asset"):
                modal_add_asset_dialog(default_category="Subscription")

    if scanned:
        metrics = calculate_metrics(current_assets)
        needs_review = [a for a in active_pool if a.review_label == "Needs review"]
        subscriptions = [a for a in active_pool if a.has_type("Subscription") and a.status not in CLOSED]
        ui.kpi_strip([
            (chf(metrics["active_monthly_spend_chf"]), "per month, recurring (approx.)", False),
            (str(len(subscriptions)), "active subscriptions", False),
            (str(len(needs_review)), "need your review", bool(needs_review)),
        ])
    else:
        st.caption("The scan uses a demo dataset of a fictional Zurich resident.")

    filters = ["All", "To review", "Subscriptions", "Finance", "Cloud", "Social", "Other"]
    with st.container(horizontal=True, vertical_alignment="center"):
        choice = st.segmented_control("Filter", filters, default="All", required=True, key="owner_filter",
                                      label_visibility="collapsed")
        show_removed = st.toggle(f"Show removed ({len(removed_list)})", key="show_removed")
        table_view = st.toggle("Table view", key="table_view")
        policy_view = st.toggle("Legacy policies", key="policy_view")

    pool = removed_list if show_removed else active_pool
    if choice == "All":
        shown = pool
    elif choice == "To review":
        shown = [a for a in pool if not a.user_verified]
    else:
        shown = [a for a in pool if matches_category(a, choice)]

    if policy_view:
        legacy_policy_view([a for a in shown if a.status not in ("Removed", "Wrongly Attributed")])
    elif table_view:
        df = pd.DataFrame([a.to_table_row() for a in shown])
        if not df.empty:  # the text of "Other" is edited on the account card
            df["My Wish"] = df["My Wish"].map(lambda wish: split_wish(wish)[0])
            df = df.drop(columns=["Action"])
        edited = st.data_editor(
            df,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "Service Address": st.column_config.LinkColumn("Website"),
                "Username": st.column_config.TextColumn("Account"),
                "My Wish": st.column_config.SelectboxColumn(
                    "Your wish", help="What should happen to this account after your death", options=WISH_OPTIONS[1:]
                ),
                "Cost": st.column_config.TextColumn("Cost / value"),
                "Status": st.column_config.SelectboxColumn("Status", options=STATUSES),
            },
        )
        # Wish edits are saved; the other columns are not saved yet.
        by_account = {(a.service, a.username): a for a in shown}
        wish_changed = False
        for row in edited.to_dict("records"):
            asset = by_account.get((row.get("Service"), row.get("Username")))
            new_wish = row.get("My Wish")
            new_wish = new_wish if isinstance(new_wish, str) else ""
            if asset and split_wish(asset.wish)[0] != new_wish:
                asset.wish = new_wish
                wish_changed = True
        if wish_changed:
            save_wishes(current_assets)
            st.rerun()
    elif shown:
        owner_rows(shown, "own")
    elif show_removed:
        ui.muted("Nothing removed. Assets you remove are kept here and can be restored.")
    elif choice == "To review":
        ui.muted("Nothing left to review.")
    else:
        ui.muted("No assets in this category yet.")
        st.button("Scan for subscriptions", key="empty_scan", on_click=go_to, args=("Discover",))

    ui.section_label("Keep it current")
    with st.container(horizontal=True, vertical_alignment="center"):
        st.toggle("Remind me every year to update this inventory", key="yearly_reminder")
        st.download_button(
            "Download inventory (CSV)",
            inventory_csv(active_pool),
            file_name="digital-legacy-inventory.csv",
            mime="text/csv",
            icon=":material/download:",
            type="tertiary",
            on_click="ignore",
        )


# =============================================================================
# PAGE: WORKLIST (executor)
# =============================================================================
elif page == "Assets":
    estate = [a for a in current_assets if a.status not in ("Removed", "Wrongly Attributed")]
    named = (st.session_state.get("deceased_name") or "").strip()
    eyebrow = "Estate settlement"

    if not estate:
        ui.page_header("Estate overview", "The owner's inventory is empty. Scan the deceased's bank "
                       "statements to find their accounts.", eyebrow=eyebrow)
        st.button("Find accounts", type="primary", key="exec_discover", on_click=go_to, args=("Discover",))
    else:
        # An overview, not a verdict: not every account has to be closed (some pass to an heir).
        title = f"Estate of {named}" if named else "Estate overview"
        action_col = ui.page_header(title, eyebrow=eyebrow)
        with action_col:
            with st.container(horizontal=True, horizontal_alignment="right"):
                st.download_button(
                    "Estate inventory (CSV)",
                    inventory_csv(estate),
                    file_name="estate-inventory.csv",
                    mime="text/csv",
                    icon=":material/download:",
                    key="exec_csv",
                    on_click="ignore",
                )

        st.text_input("Name of the deceased", key="deceased_name", placeholder="Full name",
                      width=420)
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.caption("You can flag an account but not remove it.", width="content")
            with st.popover("Why?", type="tertiary"):
                st.markdown(
                    "Every account the owner listed stays in the records, including ones the owner removed. "
                    "This keeps the estate transparent for the inheritance process and prevents assets "
                    "from being hidden. If an account did not belong to the deceased, flag it instead."
                )

        wrongly_attributed = [a for a in current_assets if a.status == "Wrongly Attributed"]
        filters = ["All", "Subscriptions", "Finance", "Cloud", "Social", "Other", "Flagged", "Removed by owner"]
        choice = st.segmented_control("Filter", filters, default="All", required=True, key="executor_filter",
                                      label_visibility="collapsed")
        if choice == "All":
            shown = current_assets
        elif choice == "Flagged":
            shown = wrongly_attributed
        elif choice == "Removed by owner":
            shown = removed_list
        else:
            shown = [a for a in active_pool if matches_category(a, choice)]

        if shown:
            executor_rows(shown, "exe")
        else:
            ui.muted("No accounts here.")


# =============================================================================
# PAGE: DISCOVER
# =============================================================================
else:
    ui.page_header("Find accounts", eyebrow="Discovery")

    oauth_message = st.session_state.pop("oauth_message", None)
    if oauth_message:
        kind, text = oauth_message
        ui.notice(text, "green" if kind == "success" else "red")

    ui.section_label("Sources")
    demo_col, gmail_col = st.columns(2, gap="medium")
    with demo_col, st.container(border=True, height="stretch"):
        st.subheader("Demo dataset", anchor=False)
        st.caption("18 months of card and bank transactions of a fictional Zurich resident.")
        demo_clicked = st.button("Scan demo dataset", type="primary", key="scan_demo")

    with gmail_col, st.container(border=True, height="stretch"):
        st.subheader("Gmail", anchor=False)
        connected = bool(st.session_state.get("gmail_credentials"))
        st.caption("Connected for this session." if connected else "Read-only access to billing emails. Nothing is stored.")
        gmail_clicked = False
        with st.container(horizontal=True, vertical_alignment="center"):
            if connected:
                gmail_clicked = st.button("Scan Gmail", key="scan_gmail")
                if st.button("Disconnect", type="tertiary", key="gmail_disconnect_btn"):
                    st.session_state.pop("gmail_credentials", None)
                    st.rerun()
            elif st.button("Connect Gmail", key="connect_gmail"):
                email_connection_dialog()

    with st.expander("Upload a transaction file"):
        st.caption("JSONL or JSON transactions. Gmail is scanned too when connected.")
        uploaded = st.file_uploader(
            "Transaction file", type=["jsonl", "json"], key="disc_page_file_uploader", label_visibility="collapsed"
        )
        file_clicked = st.button("Scan file", key="scan_file", disabled=uploaded is None)

    pending = st.session_state.pop("pending_scan", None)
    scan_source = pending or ("demo" if demo_clicked else "gmail" if gmail_clicked else "file" if file_clicked else None)
    llm_error = st.session_state.get("scan_llm_error")

    if scan_source:
        ui.section_label("Scan")
        run_scan(scan_source)
    elif llm_error:
        ui.section_label("Scan")
        ui.notice(f"The AI model is not configured ({llm_error[1]}). You can scan with rules only; "
                  "names and confidence are less precise.", "amber")
        if st.button("Scan with rules only", type="primary", key="disc_rules_only_btn"):
            run_scan(llm_error[0], use_llm=False)

    last_scan = st.session_state.get("last_scan")
    if last_scan and not scan_source:
        found = [a for a in current_assets if a.id in set(last_scan["ids"])]
        ui.section_label("Results")
        ui.step_list([(s, "done") for s in last_scan["steps"]])
        to_review = sum(1 for a in found if not a.user_verified and a.status != "Removed")
        summary = f"{last_scan['source']}: found {len(found)} subscriptions, {last_scan['added']} new."
        if to_review:
            summary += f" {to_review} waiting for your confirmation."
        ui.notice(summary, "navy")
        if last_scan["rules_only"]:
            st.caption("Scanned with rules only.")
        if found:
            owner_rows(found, "scan")
