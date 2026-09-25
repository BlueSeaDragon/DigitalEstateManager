import os
import tempfile
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import pandas as pd
import streamlit as st

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
from digital_estate_manager.policies import generate_action_email
from digital_estate_manager.policies.rules import get_policies_for_service
from digital_estate_manager.vault import calculate_metrics, get_default_assets

try:
    from backend import pdf_generator, rag_engine
    CANCELLATION_ENGINE_ERROR = None
except ImportError as exc:  # backend dependencies missing: the cancellation guide falls back to static steps
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
    page_title="Digital Legacy Vault",
    page_icon="🔐",
    layout="wide",
)

# Global dialog styling to ensure fields remain aligned even when labels span multiple lines
st.markdown(
    """
    <style>
    /* Force dialog columns to stretch to equal height */
    div[data-testid="stDialog"] div[data-testid="stHorizontalBlock"] {
        align-items: stretch !important;
    }

    div[data-testid="stDialog"] .stColumn,
    div[data-testid="stDialog"] [data-testid="stColumn"],
    div[data-testid="stDialog"] [data-testid="column"] {
        display: flex !important;
        flex-direction: column !important;
    }

    div[data-testid="stDialog"] .stColumn > div,
    div[data-testid="stDialog"] [data-testid="stColumn"] > div,
    div[data-testid="stDialog"] [data-testid="column"] > div {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 1 auto !important;
        height: 100% !important;
    }

    /* Input widgets inside dialog columns stretch and align controls at the bottom */
    div[data-testid="stDialog"] .stColumn div[data-testid="stTextInput"],
    div[data-testid="stDialog"] .stColumn div[data-testid="stSelectbox"],
    div[data-testid="stDialog"] .stColumn div[data-testid="stNumberInput"],
    div[data-testid="stDialog"] .stColumn div[data-testid="stTextArea"],
    div[data-testid="stDialog"] .stColumn div[data-testid="stMultiSelect"],
    div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stTextInput"],
    div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stSelectbox"],
    div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stNumberInput"],
    div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stTextArea"],
    div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stMultiSelect"] {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 1 auto !important;
        justify-content: flex-end !important;
        height: 100% !important;
    }

    /* Consistent min-height for input labels so 1-line and multi-line labels keep fields aligned */
    div[data-testid="stDialog"] .stColumn label[data-testid="stWidgetLabel"],
    div[data-testid="stDialog"] [data-testid="stColumn"] label[data-testid="stWidgetLabel"],
    div[data-testid="stDialog"] [data-testid="column"] label[data-testid="stWidgetLabel"] {
        min-height: 2.85rem !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: flex-start !important;
        margin-bottom: auto !important;
    }

    div[data-testid="stDialog"] .stColumn label[data-testid="stWidgetLabel"] p,
    div[data-testid="stDialog"] [data-testid="stColumn"] label[data-testid="stWidgetLabel"] p,
    div[data-testid="stDialog"] [data-testid="column"] label[data-testid="stWidgetLabel"] p {
        font-size: 0.875rem !important;
        line-height: 1.35 !important;
        margin: 0 !important;
    }

    /* Checkboxes have inline labels and must not inherit the vertical min-height */
    div[data-testid="stDialog"] div[data-testid="stCheckbox"] label[data-testid="stWidgetLabel"] {
        min-height: unset !important;
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        margin-bottom: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# 1. State Management
# =============================================================================
if "assets" not in st.session_state:
    st.session_state.assets = get_default_assets()
elif len(st.session_state.assets) > 0 and isinstance(st.session_state.assets[0], dict):
    # Migrate any legacy dictionary state to typed models
    st.session_state.assets = [Asset.from_table_row(d) for d in st.session_state.assets]

if "active_page" not in st.session_state:
    st.session_state.active_page = "Catalogue"


def handle_oauth_redirect() -> None:
    """Completes the Gmail OAuth flow when Google redirects back with ?code=...&state=..."""
    params = st.query_params
    if "code" not in params and "error" not in params:
        return
    code, state, error = params.get("code"), params.get("state"), params.get("error")
    st.query_params.clear()
    st.session_state.active_page = "Find Assets"

    if error:
        st.session_state.oauth_message = ("error", f"Google sign-in was not completed ({error}).")
        return
    try:
        # Checks that the state was issued by this server (and only once) before exchanging the code.
        st.session_state.gmail_credentials = complete_email_connection(code, state)
        st.session_state.oauth_message = ("success", "Gmail connected for this session.")
    except EmailConnectionError as exc:
        st.session_state.oauth_message = ("error", str(exc))


handle_oauth_redirect()

current_assets: List[Asset] = st.session_state.assets
metrics = calculate_metrics(current_assets)


def get_assets_by_type():
    # Active accounts (excluding removed by owner)
    active_pool = [a for a in current_assets if a.status != "Removed"]
    subs = [a for a in active_pool if a.has_type("Subscription")]
    fin = [a for a in active_pool if a.has_type("Crypto / Finance")]
    cloud = [a for a in active_pool if a.has_type("Cloud Storage")]
    social = [a for a in active_pool if a.has_type("Social Media")]
    other = [
        a for a in active_pool
        if a.has_type("Other") or not any(a.has_type(t) for t in ["Subscription", "Crypto / Finance", "Cloud Storage", "Social Media"])
    ]
    removed = [a for a in current_assets if a.status == "Removed"]
    wrongly_attributed = [a for a in current_assets if a.status == "Wrongly Attributed"]
    return subs, fin, cloud, social, other, removed, wrongly_attributed


subs_list, fin_list, cloud_list, social_list, other_list, removed_list, wrongly_attributed_list = get_assets_by_type()

# =============================================================================
# 2. Sidebar Navigation & Roles
# =============================================================================
st.sidebar.title("🔐 Legacy Vault")

page_selection = st.sidebar.radio(
    "Navigation",
    ["Catalogue", "Find Assets"],
    index=0 if st.session_state.active_page == "Catalogue" else 1,
    key="nav_radio",
)
st.session_state.active_page = page_selection

st.sidebar.divider()
st.sidebar.subheader("View Role")
mode = st.sidebar.radio("View Mode", ["Account Owner", "Heir / Executor"])

st.sidebar.caption(
    "💡 **Account Owner** manages active subscriptions and cancellations; **Heir / Executor** manages post-mortem legal workflows."
)


# =============================================================================
# 3. Popup Dialogs
# =============================================================================
@st.dialog("Connect Email Account")
def email_connection_dialog():
    """Modal popup for connecting an email provider to find digital assets."""
    st.markdown("### 🔴 Gmail (Google)")
    st.caption(
        "Connect your Gmail account to discover recurring subscriptions, payment receipts, and digital account notices."
    )

    st.selectbox(
        "Email Provider",
        ["Gmail (Google Workspace & Personal)"],
        index=0,
        disabled=True,
        help="Only Gmail is currently supported in this prototype.",
    )

    if st.session_state.get("gmail_credentials"):
        st.success("✅ A Gmail account is already connected for this session.")

    target_email = st.text_input(
        "Enter Gmail Address (optional)",
        placeholder="e.g. john.doe@gmail.com",
    )

    st.info(
        "🔒 **Privacy & Read-Only Access**: DEM requests read-only Gmail access to scan billing emails for subscriptions. "
        "Emails are processed in memory and only short excerpts are sent to the Swiss-hosted AI model; email contents are "
        "not stored, and the connection ends with this browser session."
    )

    st.divider()
    c_cancel, c_auth = st.columns([1, 1], gap="medium", vertical_alignment="center")
    with c_cancel:
        if st.button("Cancel", width='stretch', key="email_cancel_btn"):
            st.rerun()

    with c_auth:
        auth_clicked = st.button("🔗 Authorize & Connect Gmail", type="primary", width='stretch', key="email_auth_btn")

    if auth_clicked:
        if target_email and "@" not in target_email:
            st.error("Please provide a valid Gmail address.")
            return
        resp = connect_email_provider(provider="gmail", email_address=target_email or None)
        if not resp["success"]:
            st.error(resp["message"])
            return
        st.session_state.oauth_state = resp["state"]
        st.link_button("Continue to Google →", resp["auth_url"], type="primary", width='stretch')
        st.caption(
            "Google opens in a new tab. After you grant access you are sent back to this app, "
            "already connected; continue in that tab."
        )



@st.dialog("Add Asset")
def modal_add_asset_dialog(default_category: str = "Subscription"):
    """Popup modal dialog for adding an asset.

    Pre-selects the category corresponding to the tab the user is viewing,
    while allowing dynamic switching of type-specific fields in real-time.
    """
    categories = ["Subscription", "Crypto / Finance", "Cloud Storage", "Social Media", "Other"]

    # When opening for a different default category, update session state key
    key_cat = "modal_dialog_category"
    if st.session_state.get("_last_dialog_default") != default_category:
        st.session_state[key_cat] = [default_category] if default_category in categories else ["Subscription"]
        st.session_state["_last_dialog_default"] = default_category

    current_cats = st.session_state.get(key_cat, [default_category])
    if isinstance(current_cats, str):
        current_cats = [current_cats] if current_cats in categories else ["Subscription"]

    # Row 1: Service Name and Provider Website / Address
    r1_c1, r1_c2 = st.columns(2, vertical_alignment="bottom")
    with r1_c1:
        service_input = st.text_input(
            "Service / Provider Name*",
            placeholder="e.g. Netflix, Dropbox, Coinbase, LinkedIn",
            key="modal_service",
        )
    with r1_c2:
        website_input = st.text_input(
            "Provider Website / Address",
            placeholder="e.g. https://service.com",
            key="modal_website",
        )

    # Row 2: Account Identifier and Asset Types (Multi-select)
    r2_c1, r2_c2 = st.columns(2, vertical_alignment="bottom")
    with r2_c1:
        username_input = st.text_input(
            "Account Identifier / Username / Email*",
            placeholder="e.g. user@gmail.com, @handle",
            key="modal_username",
        )
    with r2_c2:
        selected_categories = st.multiselect(
            "Asset Type(s)* (Select one or more)",
            categories,
            default=current_cats,
            key=key_cat,
            help="An asset can belong to multiple categories simultaneously (e.g. Subscription + Cloud Storage for Google One).",
        )
        if not selected_categories:
            selected_categories = ["Other"]

    st.markdown("###### Type-Specific Information")

    # DYNAMIC FIELDS - Displays fields for each selected category
    if "Subscription" in selected_categories:
        st.markdown("**💳 Subscription & Recurring Billing**")
        sub_c1, sub_c2, sub_c3 = st.columns(3, vertical_alignment="top")
        with sub_c1:
            cost_val = st.number_input("Monthly Cost ($)", min_value=0.0, value=12.99, step=1.0, key="modal_sub_cost")
        with sub_c2:
            billing_val = st.selectbox("Billing Frequency", ["monthly", "annual", "quarterly", "weekly"], key="modal_sub_billing")
        with sub_c3:
            tier_val = st.text_input("Plan Tier / Name", placeholder="e.g. Premium Individual, Family", key="modal_sub_tier")
        renewal_val = st.text_input("Next Renewal Date (Optional)", placeholder="YYYY-MM-DD", key="modal_sub_renewal")

    if "Crypto / Finance" in selected_categories:
        st.markdown("**💰 Financial & Crypto Accounts**")
        fin_c1, fin_c2, fin_c3 = st.columns(3, vertical_alignment="top")
        with fin_c1:
            balance_val = st.number_input("Estimated Value / Balance ($)", min_value=0.0, value=1500.0, step=100.0, key="modal_fin_balance")
        with fin_c2:
            inst_val = st.selectbox("Institution Type", ["crypto_exchange", "bank", "brokerage", "wallet", "fintech"], key="modal_fin_inst")
        with fin_c3:
            custody_val = st.selectbox("Custody Model", ["Custodial (Exchange/Bank)", "Self-Custody (Private Key/Wallet)"], key="modal_fin_custody")
        probate_val = st.checkbox("Requires Probate Court Resolution", value=True, key="modal_fin_probate")

    if "Cloud Storage" in selected_categories:
        st.markdown("**☁️ Cloud Storage & Document Vaults**")
        cl_c1, cl_c2 = st.columns(2, vertical_alignment="top")
        with cl_c1:
            cap_val = st.number_input("Storage Capacity (GB)", min_value=1.0, value=100.0, step=10.0, key="modal_cloud_cap")
        with cl_c2:
            used_val = st.number_input("Used Storage (GB)", min_value=0.0, value=30.0, step=5.0, key="modal_cloud_used")
        data_types_val = st.multiselect(
            "Content Types Stored",
            ["Documents", "Family Photos", "Tax Returns", "Backups", "Source Code", "Legal Contracts"],
            default=["Documents", "Family Photos"],
            key="modal_cloud_types",
        )
        sens_val = st.checkbox("Contains Confidential / Sensitive Documents", value=True, key="modal_cloud_sens")

    if "Social Media" in selected_categories:
        st.markdown("**📱 Social Media & Online Profiles**")
        soc_c1, soc_c2 = st.columns(2, vertical_alignment="top")
        with soc_c1:
            handle_val = st.text_input("Platform Handle / Profile Name", placeholder="@alex", key="modal_soc_handle")
        with soc_c2:
            profile_url_val = st.text_input("Profile URL", placeholder="https://linkedin.com/in/alex", key="modal_soc_url")
        soc_mem_val = st.checkbox("Platform Supports Memorialization Policy", value=True, key="modal_soc_mem")
        soc_leg_val = st.checkbox("Legacy Contact Pre-configured in Platform Settings", value=False, key="modal_soc_leg")

    if "Other" in selected_categories or not any(c in selected_categories for c in ["Subscription", "Crypto / Finance", "Cloud Storage", "Social Media"]):
        st.markdown("**📁 Other Account Details**")
        custom_cat_val = st.text_input("Custom Category Name", value="Digital Account", key="modal_other_name")
        custom_notes_val = st.text_area("Account Notes & Description", key="modal_other_notes")

    st.markdown("###### Heir Assignment & Post-Mortem Action")
    col_o1, col_o2 = st.columns(2, vertical_alignment="top")
    with col_o1:
        heir_input = st.text_input("Designated Heir / Responsible Person", value="Alex", key="modal_heir")
    with col_o2:
        action_input = st.selectbox(
            "Recommended Legal Action",
            ["Cancel", "Transfer & Archive", "Probate Recovery", "Memorialize", "Delete Account"],
            key="modal_action",
        )

    notes_input = st.text_input("Additional Notes (Optional)", key="modal_notes")

    st.divider()
    c_cancel, c_save = st.columns([1, 1], gap="medium", vertical_alignment="center")
    with c_cancel:
        if st.button("Cancel", width='stretch', key="modal_cancel_btn"):
            st.rerun()

    with c_save:
        save_clicked = st.button("Save Asset", type="primary", width='stretch', key="modal_save_btn")

    if save_clicked:
        if not service_input.strip() or not username_input.strip():
            st.error("Please enter both the Service Name and Account Identifier / Username.")
            return

        infos_to_add: List[AnyAssetInfo] = []
        if "Subscription" in selected_categories:
            infos_to_add.append(
                SubscriptionAssetInfo(
                    cost_monthly=cost_val,
                    billing_cycle=billing_val,
                    plan_tier=tier_val.strip() if tier_val else None,
                    renewal_date=renewal_val.strip() if renewal_val else None,
                )
            )
        if "Crypto / Finance" in selected_categories:
            infos_to_add.append(
                FinancialAssetInfo(
                    approximate_balance=balance_val,
                    institution_type=inst_val,
                    is_custodial=("Custodial" in custody_val),
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
                    category_name=custom_cat_val.strip() or "Digital Account",
                    notes=custom_notes_val.strip() if custom_notes_val else None,
                )
            )

        default_death, default_cancel = get_policies_for_service(service_input, website_input)
        default_cancel.action_name = action_input

        new_asset = Asset(
            service=service_input.strip(),
            service_address=website_input.strip(),
            username=username_input.strip(),
            death_policy=default_death,
            cancel_policy=default_cancel,
            asset_infos=infos_to_add,
            heir=heir_input.strip() or "Unassigned",
            status="Active",
            notes=notes_input.strip() if notes_input else None,
        )

        st.session_state.assets.append(new_asset)
        st.success(f"✅ Successfully cataloged **{new_asset.service}** ({new_asset.username}) with categories: {', '.join(new_asset.types)}!")
        st.rerun()


CHANNEL_LABELS = {
    "web_portal": "Online portal",
    "app_store": "App store subscription settings",
    "email": "Email",
    "registered_letter": "Registered letter (Einschreiben)",
    "phone_call": "Phone call",
}


def _asset_sub_type(asset: Asset) -> str:
    sub_info = asset.get_info("Subscription")
    return sub_info.plan_tier if sub_info and sub_info.plan_tier else "subscription"


def researched_cancel_policy(asset: Asset, sub_type: str):
    """Researches the provider's cancellation policy once per asset/plan and session.

    Returns the CancelPolicy, or an error message when the engine is unavailable or fails.
    """
    cache = st.session_state.setdefault("researched_cancel_policies", {})
    key = (asset.id, sub_type)
    if key not in cache:
        if rag_engine is None:
            cache[key] = f"The cancellation engine is not installed ({CANCELLATION_ENGINE_ERROR})."
        else:
            with st.spinner(f"Researching the current {asset.service} cancellation policy..."):
                try:
                    _, cancel_policy = rag_engine.search_web_cancellation_policy(
                        asset.service,
                        sub_type=sub_type,
                        mode="during_life",
                        service_address=asset.service_address or None,
                    )
                    cache[key] = cancel_policy
                except Exception as exc:
                    cache[key] = str(exc)
    return cache[key]


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


def render_written_notice(asset: Asset, policy: CancelPolicy, sub_type: str, kind: str) -> None:
    """Button that writes the cancellation email text or letter PDF, and shows the result."""
    mailing_address = policy.action_payload.get("mailing_address") or ""
    if kind == "email":
        st.markdown("#### ✉️ Cancellation Email")
        st.caption(f"{asset.service} accepts cancellations by email. Generate a ready-to-send text:")
    else:
        st.markdown("#### 📄 Cancellation Letter")
        st.caption(f"{asset.service} requires a written cancellation letter. Generate a ready-to-sign PDF:")

    n1, n2 = st.columns(2)
    sender_name = n1.text_input("Your full name", key=f"cxl_sender_{asset.id}")
    contract_id = n2.text_input(
        "Customer / contract number", value=asset.username, key=f"cxl_contract_{asset.id}"
    )

    notices = st.session_state.setdefault("generated_cancel_notices", {})
    button_label = "✍️ Write Cancellation Email" if kind == "email" else "📄 Generate Cancellation Letter"
    if st.button(
        button_label,
        type="primary",
        width="stretch",
        disabled=not sender_name.strip(),
        help=None if sender_name.strip() else "Enter your name first.",
        key=f"cxl_write_{asset.id}",
    ):
        with st.spinner("Writing your cancellation..."):
            try:
                letter = rag_engine.generate_cancellation_letter(
                    provider_name=asset.service,
                    sub_type=sub_type,
                    person_name=sender_name.strip(),
                    contract_id=contract_id.strip() or "-",
                    mode="during_life",
                    cancel_policy=policy,
                )
                pdf_bytes = None
                if kind == "letter":
                    pdf_bytes = _letter_pdf_bytes(
                        sender_name.strip(), asset.service, mailing_address or "Kundenservice", letter
                    )
                notices[asset.id] = {"kind": kind, "text": letter, "pdf": pdf_bytes}
            except Exception as exc:
                st.error(f"Could not write the cancellation: {exc}")

    notice = notices.get(asset.id)
    if not notice or notice["kind"] != kind:
        return

    if kind == "email":
        subject, body = _split_subject(notice["text"], f"Kündigung {asset.service} ({contract_id})")
        if policy.support_email:
            st.write(f"**Send to:** {policy.support_email}")
        st.write(f"**Subject:** {subject}")
        st.text_area("Email text", body, height=260, key=f"cxl_email_text_{asset.id}")
        if policy.support_email:
            st.link_button(
                f"✉️ Open in Mail App ({policy.support_email})",
                f"mailto:{policy.support_email}?subject={quote(subject)}&body={quote(body)}",
                width="stretch",
            )
    else:
        if mailing_address:
            st.write("**Send by registered mail (Einschreiben) to:**")
            st.code(mailing_address, language=None)
        st.text_area("Letter text", notice["text"], height=260, key=f"cxl_letter_text_{asset.id}")
        st.download_button(
            "⬇️ Download Letter (PDF)",
            data=notice["pdf"],
            file_name=f"Kuendigung_{asset.service}.pdf".replace(" ", "_"),
            mime="application/pdf",
            type="primary",
            width="stretch",
            on_click="ignore",
            key=f"cxl_pdf_{asset.id}",
        )


# Fewer researched steps than this counts as "not enough" and links to the provider's policy instead
MIN_STEPS_FOR_GUIDE = 2


def _set_state(key: str, value) -> None:
    """Button callback: runs before the dialog re-renders, so the new state shows immediately."""
    if value is None:
        st.session_state.pop(key, None)
    else:
        st.session_state[key] = value


def _needs_plan(policy: CancelPolicy) -> bool:
    """True when the cancellation rules differ per plan and the researched plan was not specific."""
    return bool(policy.action_payload.get("requires_sub_type_selection"))


def render_plan_picker(asset: Asset, policy: CancelPolicy, plan_key: str) -> None:
    """Asks which plan the user has: pick a researched option, type a name, or 'I don't know'."""
    st.info(f"**Which {asset.service} plan do you have?** The cancellation rules differ between plans.")

    options = policy.action_payload.get("sub_type_options") or []
    if options:
        o_cols = st.columns(min(len(options), 3))
        for idx, option in enumerate(options):
            o_cols[idx % len(o_cols)].button(
                option,
                key=f"cxl_plan_opt_{asset.id}_{idx}",
                width="stretch",
                on_click=_set_state,
                args=(plan_key, {"plan": option}),
            )

    t1, t2 = st.columns([3, 1], vertical_alignment="bottom")
    typed_key = f"cxl_plan_typed_{asset.id}"
    t1.text_input("Or enter your plan name", key=typed_key, placeholder="e.g. Swisscom blue Mobile M")

    def search_typed_plan() -> None:
        typed = (st.session_state.get(typed_key) or "").strip()
        if typed:
            _set_state(plan_key, {"plan": typed})

    t2.button("🔍 Search this plan", key=f"cxl_plan_search_{asset.id}", width="stretch", on_click=search_typed_plan)

    st.button(
        "🤷 I don't know my plan",
        key=f"cxl_plan_unknown_{asset.id}",
        width="stretch",
        on_click=_set_state,
        args=(plan_key, {"unknown": True}),
    )


def render_researched_cancellation(
    asset: Asset, policy: CancelPolicy, sub_type: str, general_policy: bool = False
) -> None:
    """Shows only what the RAG engine researched: facts, steps, links, contacts, documents.

    `general_policy` marks a plan-independent answer (user doesn't know their plan): the link to
    the provider's policy is then always shown so the user can look up their plan's details.
    """
    payload = policy.action_payload
    channel = payload.get("primary_channel")

    facts = [
        ("Cancel via", CHANNEL_LABELS.get(channel)),
        ("Notice period", payload.get("notice_period")),
        ("Minimum contract duration", payload.get("minimum_contract_duration")),
    ]
    facts = [(label, value) for label, value in facts if value]
    if facts:
        f_cols = st.columns(len(facts))
        for col, (label, value) in zip(f_cols, facts):
            col.write(f"**{label}:** {value}")

    if policy.target_url:
        st.link_button(
            f"🔗 Open {asset.service} Cancellation Page",
            policy.target_url,
            type="primary",
            width="stretch",
        )

    enough_steps = len(policy.steps) >= MIN_STEPS_FOR_GUIDE
    if enough_steps:
        st.markdown("#### 📋 Step-by-Step Instructions")
        for idx, step in enumerate(policy.steps, 1):
            st.markdown(f"**{idx}.** {step}")
    else:
        for step in policy.steps:
            st.markdown(f"- {step}")

    if general_policy or not enough_steps:
        policy_url = payload.get("policy_url") or policy.target_url
        if general_policy:
            reason = f"This is {asset.service}'s general policy; the exact rules depend on your plan."
        else:
            reason = "Not enough details found for step-by-step instructions."
        if policy_url:
            st.warning(f"{reason} See {asset.service}'s official policy:")
            st.link_button(f"📄 {asset.service} Cancellation Policy", policy_url, width="stretch")
        else:
            st.warning(f"{reason} No link to {asset.service}'s policy was found.")

    contacts = []
    if policy.support_email:
        contacts.append(f"✉️ **Email:** [{policy.support_email}](mailto:{policy.support_email})")
    if payload.get("contact_phone"):
        contacts.append(f"📞 **Phone:** {payload['contact_phone']}")
    if payload.get("mailing_address"):
        contacts.append(f"🏢 **Postal address:** {payload['mailing_address'].replace(chr(10), ', ')}")
    if contacts:
        st.markdown("##### 📇 Contact")
        for contact in contacts:
            st.markdown(f"- {contact}")

    if policy.required_documents:
        st.markdown("##### 📑 Required Documentation")
        for doc in policy.required_documents:
            st.markdown(f"- {doc}")

    kind = _letter_kind(policy)
    if kind:
        st.divider()
        render_written_notice(asset, policy, sub_type, kind)


@st.dialog("Cancellation & Account Closure Guide", width="large")
def cancellation_guide_dialog(asset: Asset):
    """Researches the provider's current cancellation policy on open (RAG engine) and shows only
    that content, plus a generator for the cancellation email or letter PDF when one is required.
    """
    st.markdown(f"### 🚫 Cancel / Close: **{asset.service}**")

    # Research runs on open with the account's plan (if known). When the rules differ per plan,
    # the user picks or types a plan (researched again) or continues with the general policy.
    sub_type = _asset_sub_type(asset)
    plan_key = f"cxl_plan_{asset.id}"
    choice = st.session_state.get(plan_key)  # None, {"plan": name} or {"unknown": True}
    researched = researched_cancel_policy(asset, sub_type)
    general_policy = False

    if isinstance(researched, CancelPolicy) and _needs_plan(researched):
        if choice and choice.get("plan"):
            plan_result = researched_cancel_policy(asset, choice["plan"])
            if isinstance(plan_result, CancelPolicy) and _needs_plan(plan_result):
                st.warning(f"No specific policy found for the plan '{choice['plan']}'. Please pick another option.")
                choice = None
            else:
                sub_type, researched = choice["plan"], plan_result
        elif choice and choice.get("unknown"):
            general_policy = True

        if not choice:
            render_plan_picker(asset, researched, plan_key)
            researched = None
        else:
            p1, p2 = st.columns([3, 1], vertical_alignment="center")
            p1.write(f"**Plan:** {'Unknown (general policy)' if general_policy else sub_type}")
            p2.button(
                "Change plan",
                key=f"cxl_change_plan_{asset.id}",
                width="stretch",
                on_click=_set_state,
                args=(plan_key, None),
            )

    if isinstance(researched, CancelPolicy):
        render_researched_cancellation(asset, researched, sub_type, general_policy)
    elif researched is not None:
        st.error(f"Could not research the cancellation policy: {researched}")
        if rag_engine is not None:
            st.button(
                "🔄 Retry Research",
                key=f"cxl_retry_{asset.id}",
                on_click=lambda: st.session_state.researched_cancel_policies.pop((asset.id, sub_type), None),
            )

    st.divider()

    # Confirmation buttons
    c_cancel, c_confirm = st.columns([1, 1], gap="medium", vertical_alignment="center")
    with c_cancel:
        if st.button("Keep Active / Dismiss", width="stretch", key=f"dlg_close_cancel_{asset.id}"):
            st.rerun()
    with c_confirm:
        if st.button("✅ Confirm & Mark as Cancelled", type="primary", width="stretch", key=f"dlg_confirm_cancel_{asset.id}"):
            asset.status = "Cancelled"
            asset.cancel_policy.status = "Completed"
            st.success(f"{asset.service} successfully marked as cancelled! Monthly spend updated.")
            st.rerun()

    if st.button("🗑️ Remove Account from Vault Instead", key=f"dlg_switch_remove_{asset.id}", width="stretch"):
        remove_account_dialog(asset)


@st.dialog("Remove Account from Vault", width="medium")
def remove_account_dialog(asset: Asset):
    """Dialogue box for removing an account that was wrongly added.

    Warns the user that removing from vault does not automatically cancel provider billing,
    provides portal links if they also need to cancel, and allows safe removal to the Removed tab.
    """
    st.markdown(f"### 🗑️ Remove **{asset.service}** from Estate Vault")

    b1, b2 = st.columns(2)
    b1.write(f"**Account Identifier:** `{asset.username or 'N/A'}`")
    b2.write(f"**Category:** {asset.category} | **Cost/Value:** {asset.cost_display}")

    details = asset.display_details()
    if details:
        det_summary = " • ".join([f"{k}: {v}" for k, v in details.items()])
        st.caption(f"📌 Known details: {det_summary}")

    st.warning(
        "⚠️ **Important Provider Billing Advisory**:\n\n"
        f"Removing this account from the **Digital Estate Vault** only deletes it from this tracking system. "
        f"**It does NOT cancel your recurring subscription or close your account with {asset.service}.**\n\n"
        f"If you have an active paid plan, you must still cancel it directly with {asset.service} to avoid future charges."
    )

    portal_url = asset.cancel_policy.target_url or asset.service_address
    if portal_url and portal_url.startswith("http"):
        st.link_button(
            f"🔗 Visit {asset.service} to Cancel Billing Directly",
            portal_url,
            width="stretch",
            help="Open the provider website to cancel subscription before removing.",
        )

    st.markdown("#### ℹ️ What happens when you remove this account?")
    st.markdown(
        "- The account will be **hidden from your active catalog** and excluded from monthly recurring spend.\n"
        "- It will be safely archived in the **'🗑️ Removed'** tab.\n"
        "- You can **restore it anytime** with 1 click if you made a mistake.\n"
        "- For estate safety, executors can still see it in the audit records to prevent asset concealment."
    )

    st.divider()

    c_keep, c_remove = st.columns([1, 1], gap="medium", vertical_alignment="center")
    with c_keep:
        if st.button("Keep in Vault", width="stretch", key=f"dlg_keep_{asset.id}"):
            st.rerun()
    with c_remove:
        if st.button("🗑️ Confirm Removal", type="primary", width="stretch", key=f"dlg_confirm_remove_{asset.id}"):
            asset.status = "Removed"
            st.success(f"{asset.service} moved to the 'Removed' tab. You can restore it anytime.")
            st.rerun()

    st.caption("Looking to cancel the subscription rather than removing it from tracking?")
    if st.button("🚫 Open Cancellation Guide Instead", key=f"dlg_switch_cancel_{asset.id}", width="stretch"):
        cancellation_guide_dialog(asset)


# =============================================================================
# =============================================================================
# PAGE 1: CATALOGUE PAGE
# =============================================================================
# =============================================================================
if st.session_state.active_page == "Catalogue":
    c_head, c_btn = st.columns([3, 1])
    with c_head:
        st.header("Digital Asset Catalogue")
        st.caption("Review, categorize, and execute actions for your digital estate assets by category.")
    #with c_btn:
        # Standard "Add Asset" button opening the dialog box
    #    if st.button("➕ Add Asset", key="btn_add_header", type="primary", width='stretch'):
    #        modal_add_asset_dialog(default_category="Subscription")

    # Overview metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Subscriptions Spend", metrics.get("active_monthly_spend", "$0.00") + "/mo")
    m2.metric("Monthly Drain Prevented", metrics.get("monthly_drain_prevented", "$0.00"))
    m3.metric("Total Cataloged Assets", metrics.get("total_services", 0))
    m4.metric("Critical Recoveries", metrics.get("critical_recovery_count", 0))

    st.divider()

    # -------------------------------------------------------------------------
    # Owner View in Catalogue
    # -------------------------------------------------------------------------
    if mode == "Account Owner":
        st.subheader("Your Cataloged Assets (Separated by Type)")
        st.caption(
            "Select an asset category below to review items, cancel active services, or add a new asset."
        )

        tab_sub, tab_fin, tab_cloud, tab_social, tab_other, tab_removed, tab_all = st.tabs([
            f"💳 Subscriptions ({len(subs_list)})",
            f"💰 Financial & Crypto ({len(fin_list)})",
            f"☁️ Cloud Storage ({len(cloud_list)})",
            f"📱 Social Media ({len(social_list)})",
            f"📁 Other ({len(other_list)})",
            f"🗑️ Removed ({len(removed_list)})",
            f"📋 Master Catalog ({len(current_assets)})",
        ])

        # --- TAB 1: SUBSCRIPTIONS ---
        with tab_sub:
            col_t_title, col_t_add = st.columns([3, 1])
            with col_t_title:
                st.markdown("#### 💳 Recurring Subscriptions & Memberships")
                st.caption("Track recurring costs, renewal dates, and cancel subscriptions to stop billing.")
            with col_t_add:
                # Add Asset button opening the dialog box pre-configured for Subscription
                if st.button("➕ Add Asset", key="btn_add_sub", width='stretch'):
                    modal_add_asset_dialog(default_category="Subscription")

            if subs_list:
                sub_rows = [
                    {
                        **a.to_type_specific_dict(target_type="Subscription"),
                        "Checked": "✅" if a.user_verified else "🔍 Not yet",
                    }
                    for a in subs_list
                ]
                st.dataframe(pd.DataFrame(sub_rows), width='stretch')

                st.markdown("##### ⚙️ Subscription Actions & Cancellation Center")
                for sub in subs_list:
                    sub_info = sub.get_info("Subscription") or sub.asset_info
                    status_badge = {"Cancelled": "🔴 Cancelled", "Pending Review": "🟡 Pending Review"}.get(
                        sub.status, "🟢 Active"
                    )
                    check_marker = "" if sub.user_verified else "🔍 "
                    multi_badge = f" [🏷️ {sub.category}]" if len(sub.types) > 1 else ""
                    card_title = (
                        f"{check_marker}{sub.service} — {sub.username} [{status_badge} | {sub.cost_display}]{multi_badge}"
                    )

                    with st.expander(card_title, expanded=(sub.status != "Cancelled")):
                        c1, c2, c3 = st.columns([2, 1, 1])
                        c1.write(f"**Plan Tier:** {getattr(sub_info, 'plan_tier', 'Standard')} | **Billing:** {getattr(sub_info, 'billing_cycle', 'monthly').capitalize()}")
                        c1.write(f"**Next Renewal Date:** {getattr(sub_info, 'renewal_date', 'N/A')}")
                        if len(sub.types) > 1:
                            other_types = [t for t in sub.types if t != "Subscription"]
                            c1.caption(f"ℹ️ Also cataloged under: **{', '.join(other_types)}**")
                        c1.write(f"**Assigned Heir:** {sub.heir}")
                        verified = c1.checkbox(
                            "I checked this subscription myself",
                            value=sub.user_verified,
                            key=f"cat_verified_{sub.id}",
                        )
                        if verified != sub.user_verified:
                            sub.user_verified = verified
                            st.rerun()
                        if sub.notes:
                            c1.caption(sub.notes.replace("\n", "  \n"))

                        with c2:
                            portal = sub.cancel_policy.target_url or sub.service_address
                            if portal and portal.startswith("http"):
                                st.link_button("🔗 Open Provider Portal", portal, width='stretch')

                        with c3:
                            if sub.status != "Cancelled":
                                if st.button("🚫 Cancel Subscription", key=f"cat_cancel_{sub.id}", width='stretch'):
                                    cancellation_guide_dialog(sub)
                            else:
                                if st.button("🔄 Reactivate", key=f"cat_react_{sub.id}", width='stretch'):
                                    sub.status = "Active"
                                    sub.cancel_policy.status = "Pending"
                                    st.rerun()
                                if st.button("📋 Cancellation Guide", key=f"cat_guide_sub_{sub.id}", width='stretch'):
                                    cancellation_guide_dialog(sub)

                            if st.button("🗑️ Remove Account", key=f"cat_remove_sub_{sub.id}", width='stretch', help="Remove this account if added by mistake. You can view or restore it in the Removed tab."):
                                remove_account_dialog(sub)

                        # Owner cancellation steps & email template
                        owner_plan = sub.cancel_policy.get_owner_cancellation_plan(
                            service=sub.service,
                            service_address=sub.service_address,
                            username=sub.username,
                        )
                        with st.expander("📝 View Cancellation Steps & Support Email Draft"):
                            st.write("**Owner Step-by-Step Instructions:**")
                            for s_idx, step in enumerate(owner_plan.get("steps", [])):
                                st.write(f"{s_idx + 1}. {step}")
                            st.text_area(
                                "Customer Support Cancellation Template",
                                owner_plan.get("email_draft", ""),
                                height=120,
                                key=f"email_draft_{sub.id}",
                            )
            else:
                st.info("No subscriptions cataloged yet. Click '➕ Add Asset' above to add one.")

        # --- TAB 2: FINANCIAL & CRYPTO ---
        with tab_fin:
            col_f_title, col_f_add = st.columns([3, 1])
            with col_f_title:
                st.markdown("#### 💰 Cryptocurrency, Exchanges & Financial Accounts")
                st.caption("Custodial vs self-custody accounts, balance estimates, and probate requirements.")
            with col_f_add:
                # Add Asset button opening the dialog box pre-configured for Crypto / Finance
                if st.button("➕ Add Asset", key="btn_add_fin", width='stretch'):
                    modal_add_asset_dialog(default_category="Crypto / Finance")

            if fin_list:
                fin_rows = [a.to_type_specific_dict(target_type="Crypto / Finance") for a in fin_list]
                st.dataframe(pd.DataFrame(fin_rows), width='stretch')

                for fin in fin_list:
                    fin_info = fin.get_info("Crypto / Finance") or fin.asset_info
                    status_badge = "🔴 Closed" if fin.status == "Completed" else "🟢 Active"
                    multi_badge = f" [🏷️ {fin.category}]" if len(fin.types) > 1 else ""
                    with st.expander(f"{fin.service} — {fin.username} [{status_badge} | {fin.cost_display}]{multi_badge}"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Institution:** {getattr(fin_info, 'institution_type', '').title()}")
                        c1.write(f"**Approx. Balance / Valuation:** {fin.cost_display}")
                        c1.write(f"**Custody Type:** {'Custodial (Exchange/Bank)' if getattr(fin_info, 'is_custodial', True) else 'Self-Custody (Wallet)'}")
                        c1.write(f"**Probate Required:** {'Yes' if getattr(fin_info, 'requires_probate', True) else 'No'}")
                        if len(fin.types) > 1:
                            other_types = [t for t in fin.types if t != "Crypto / Finance"]
                            c1.caption(f"ℹ️ Also cataloged under: **{', '.join(other_types)}**")
                        c1.write(f"**Designated Heir:** {fin.heir}")

                        with c2:
                            if fin.service_address.startswith("http"):
                                st.link_button("🔗 Open Platform", fin.service_address, width='stretch')
                            if fin.status != "Completed":
                                if st.button("🚫 Close Account", key=f"cat_close_fin_{fin.id}", width='stretch'):
                                    cancellation_guide_dialog(fin)
                            else:
                                if st.button("🔄 Reopen Account", key=f"cat_reopen_fin_{fin.id}", width='stretch'):
                                    fin.status = "Active"
                                    st.rerun()
                                if st.button("📋 Closure Guide", key=f"cat_guide_fin_{fin.id}", width='stretch'):
                                    cancellation_guide_dialog(fin)
                            if st.button("🗑️ Remove Account", key=f"cat_remove_fin_{fin.id}", width='stretch', help="Remove this account if added by mistake. You can view or restore it in the Removed tab."):
                                remove_account_dialog(fin)
            else:
                st.info("No financial or crypto accounts cataloged. Click '➕ Add Asset' above to add one.")

        # --- TAB 3: CLOUD STORAGE ---
        with tab_cloud:
            col_c_title, col_c_add = st.columns([3, 1])
            with col_c_title:
                st.markdown("#### ☁️ Cloud Storage & Document Vaults")
                st.caption("Track storage capacities, used volume, sensitive files, and takeout archives.")
            with col_c_add:
                # Add Asset button opening the dialog box pre-configured for Cloud Storage
                if st.button("➕ Add Asset", key="btn_add_cloud", width='stretch'):
                    modal_add_asset_dialog(default_category="Cloud Storage")

            if cloud_list:
                cloud_rows = [a.to_type_specific_dict(target_type="Cloud Storage") for a in cloud_list]
                st.dataframe(pd.DataFrame(cloud_rows), width='stretch')

                for cl in cloud_list:
                    cl_info = cl.get_info("Cloud Storage") or cl.asset_info
                    multi_badge = f" [🏷️ {cl.category}]" if len(cl.types) > 1 else ""
                    with st.expander(f"{cl.service} — {cl.username} [{cl.status}]{multi_badge}"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Storage Capacity:** {getattr(cl_info, 'storage_capacity_gb', 'N/A')} GB | **Used:** {getattr(cl_info, 'used_storage_gb', 'N/A')} GB")
                        c1.write(f"**Stored Content:** {', '.join(getattr(cl_info, 'data_types', []))}")
                        c1.write(f"**Contains Sensitive Documents:** {'Yes' if getattr(cl_info, 'contains_sensitive_data', True) else 'No'}")
                        if len(cl.types) > 1:
                            other_types = [t for t in cl.types if t != "Cloud Storage"]
                            c1.caption(f"ℹ️ Also cataloged under: **{', '.join(other_types)}**")
                        c1.write(f"**Designated Heir:** {cl.heir}")

                        with c2:
                            if cl.service_address.startswith("http"):
                                st.link_button("🔗 Manage Storage", cl.service_address, width='stretch')
                            if cl.status != "Cancelled":
                                if st.button("🚫 Cancel Plan", key=f"cat_cancel_cloud_{cl.id}", width='stretch'):
                                    cancellation_guide_dialog(cl)
                            else:
                                if st.button("🔄 Reactivate Plan", key=f"cat_react_cloud_{cl.id}", width='stretch'):
                                    cl.status = "Active"
                                    st.rerun()
                                if st.button("📋 Closure Guide", key=f"cat_guide_cloud_{cl.id}", width='stretch'):
                                    cancellation_guide_dialog(cl)
                            if st.button("🗑️ Remove Account", key=f"cat_remove_cloud_{cl.id}", width='stretch', help="Remove this account if added by mistake. You can view or restore it in the Removed tab."):
                                remove_account_dialog(cl)
            else:
                st.info("No cloud storage assets cataloged. Click '➕ Add Asset' above to add one.")

        # --- TAB 4: SOCIAL MEDIA ---
        with tab_social:
            col_s_title, col_s_add = st.columns([3, 1])
            with col_s_title:
                st.markdown("#### 📱 Social Media, Online Presence & Public Handles")
                st.caption("Verify platform memorialization options and configure legacy contacts.")
            with col_s_add:
                # Add Asset button opening the dialog box pre-configured for Social Media
                if st.button("➕ Add Asset", key="btn_add_soc", width='stretch'):
                    modal_add_asset_dialog(default_category="Social Media")

            if social_list:
                social_rows = [a.to_type_specific_dict(target_type="Social Media") for a in social_list]
                st.dataframe(pd.DataFrame(social_rows), width='stretch')

                for soc in social_list:
                    soc_info = soc.get_info("Social Media") or soc.asset_info
                    multi_badge = f" [🏷️ {soc.category}]" if len(soc.types) > 1 else ""
                    with st.expander(f"{soc.service} — {soc.username} [{soc.status}]{multi_badge}"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Platform Profile:** {getattr(soc_info, 'profile_url', soc.service_address)}")
                        c1.write(f"**Handle:** {getattr(soc_info, 'platform_handle', soc.username)}")
                        c1.write(f"**Memorialization Supported:** {'Yes' if getattr(soc_info, 'memorialization_supported', True) else 'No'}")
                        c1.write(f"**Legacy Contact Set:** {'Yes' if getattr(soc_info, 'has_legacy_contact_set', False) else 'Not Configured'}")
                        if len(soc.types) > 1:
                            other_types = [t for t in soc.types if t != "Social Media"]
                            c1.caption(f"ℹ️ Also cataloged under: **{', '.join(other_types)}**")
                        c1.write(f"**Designated Heir:** {soc.heir}")

                        with c2:
                            portal = getattr(soc_info, "profile_url", None) or soc.service_address
                            if portal and portal.startswith("http"):
                                st.link_button("🔗 View Profile", portal, width='stretch')
                            if soc.status != "Archived":
                                if st.button("🗄️ Archive / Close Profile", key=f"cat_close_soc_{soc.id}", width='stretch'):
                                    cancellation_guide_dialog(soc)
                            else:
                                if st.button("🔄 Unarchive Profile", key=f"cat_unarchive_soc_{soc.id}", width='stretch'):
                                    soc.status = "Active"
                                    st.rerun()
                                if st.button("📋 Closure Guide", key=f"cat_guide_soc_{soc.id}", width='stretch'):
                                    cancellation_guide_dialog(soc)
                            if st.button("🗑️ Remove Account", key=f"cat_remove_soc_{soc.id}", width='stretch', help="Remove this account if added by mistake. You can view or restore it in the Removed tab."):
                                remove_account_dialog(soc)
            else:
                st.info("No social media accounts cataloged. Click '➕ Add Asset' above to add one.")

        # --- TAB 5: OTHER ACCOUNTS ---
        with tab_other:
            col_o_title, col_o_add = st.columns([3, 1])
            with col_o_title:
                st.markdown("#### 📁 Other Digital Accounts & Utilities")
            with col_o_add:
                # Add Asset button opening the dialog box pre-configured for Other
                if st.button("➕ Add Asset", key="btn_add_oth", width='stretch'):
                    modal_add_asset_dialog(default_category="Other")

            if other_list:
                other_rows = [a.to_type_specific_dict() for a in other_list]
                st.dataframe(pd.DataFrame(other_rows), width='stretch')

                for oth in other_list:
                    with st.expander(f"{oth.service} — {oth.username} [{oth.status}]"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Website / Address:** {oth.service_address or 'N/A'}")
                        c1.write(f"**Account Identifier:** {oth.username or 'N/A'}")
                        c1.write(f"**Assigned Heir:** {oth.heir}")
                        if oth.notes:
                            c1.write(f"**Notes:** {oth.notes}")
                        with c2:
                            if oth.service_address.startswith("http"):
                                st.link_button("🔗 Open Service", oth.service_address, width='stretch')
                            if oth.status != "Cancelled":
                                if st.button("🚫 Cancel Service", key=f"cat_cancel_oth_{oth.id}", width='stretch'):
                                    cancellation_guide_dialog(oth)
                            else:
                                if st.button("🔄 Reactivate", key=f"cat_react_oth_{oth.id}", width='stretch'):
                                    oth.status = "Active"
                                    st.rerun()
                                if st.button("📋 Closure Guide", key=f"cat_guide_oth_{oth.id}", width='stretch'):
                                    cancellation_guide_dialog(oth)
                            if st.button("🗑️ Remove Account", key=f"cat_remove_oth_{oth.id}", width='stretch', help="Remove this account if added by mistake. You can view or restore it in the Removed tab."):
                                remove_account_dialog(oth)
            else:
                st.info("No other accounts cataloged. Click '➕ Add Asset' above to add one.")

        # --- TAB 6: REMOVED ACCOUNTS ---
        with tab_removed:
            st.markdown("#### 🗑️ Removed Accounts & Restoration")
            st.caption(
                "Accounts removed by the owner are saved here. You can review them anytime or restore them back to your active catalog if removed by mistake."
            )

            if removed_list:
                rem_rows = [a.to_type_specific_dict() for a in removed_list]
                st.dataframe(pd.DataFrame(rem_rows), width='stretch')

                for rem in removed_list:
                    with st.expander(f"🗑️ {rem.service} — {rem.username} ({rem.category}) [Removed]"):
                        c_info, c_action = st.columns([2, 1])
                        with c_info:
                            c_info.write(f"**Service / Provider:** {rem.service}")
                            c_info.write(f"**Website / URL:** {rem.service_address or 'N/A'}")
                            c_info.write(f"**Account / Identifier:** {rem.username or 'N/A'}")
                            c_info.write(f"**Category:** {rem.category}")
                            c_info.write(f"**Cost / Balance:** {rem.cost_display}")
                            c_info.write(f"**Assigned Heir:** {rem.heir}")
                            st.caption("ℹ️ *This account is excluded from active recurring spend and active estate assets.*")
                        with c_action:
                            if st.button("♻️ Restore Account", key=f"cat_restore_{rem.id}", type="primary", width='stretch'):
                                rem.status = "Active"
                                st.success(f"Restored {rem.service} back to the active catalog!")
                                st.rerun()
                            if st.button("📋 Cancellation Guide", key=f"cat_rem_guide_{rem.id}", width='stretch', help="View steps and email format to cancel recurring billing directly with provider."):
                                cancellation_guide_dialog(rem)
            else:
                st.info("No removed accounts. Any accounts removed from the categories above will be held safely here and can be restored at any time.")

        # --- TAB 7: MASTER CATALOG ---
        with tab_all:
            col_m_title, col_m_add = st.columns([3, 1])
            with col_m_title:
                st.markdown("#### 📋 Master Asset Catalog")
                st.caption("Tabular view of all assets in your estate vault.")
            with col_m_add:
                if st.button("➕ Add Asset", key="btn_add_master", width='stretch'):
                    modal_add_asset_dialog(default_category="Subscription")

            df = pd.DataFrame([a.to_table_row() for a in current_assets])
            edited_df = st.data_editor(
                df,
                width='stretch',
                num_rows="dynamic",
                column_config={
                    "Service Address": st.column_config.LinkColumn("Service Address"),
                    "Username": st.column_config.TextColumn("Username"),
                    "Cost": st.column_config.TextColumn("Cost / Value"),
                    "Action": st.column_config.SelectboxColumn(
                        "Action",
                        options=["Cancel", "Transfer & Archive", "Probate Recovery", "Memorialize", "Delete Account"],
                    ),
                    "Status": st.column_config.SelectboxColumn(
                        "Status",
                        options=["Active", "Pending Review", "In Progress", "Completed", "Cancelled", "Archived", "Removed", "Wrongly Attributed"],
                    ),
                },
            )

    # -------------------------------------------------------------------------
    # Heir / Executor View in Catalogue
    # -------------------------------------------------------------------------
    else:
        st.subheader("Post-Mortem Execution Hub (Heir / Executor)")
        st.caption("Organized legal workflows, death policies, and dispatch notices separated by asset category.")

        st.info(
            "🛡️ **Estate Safety & Audit Policy**: Confirmed accounts cannot be removed by an executor. "
            "If an account was incorrectly included or does not belong to the estate, flag it as **'Wrongly Attributed'**. "
            "All cataloged accounts are retained in the vault for probate transparency and anti-fraud safety (preventing concealment of assets)."
        )

        e_tab_all, e_tab_sub, e_tab_fin, e_tab_cloud, e_tab_social, e_tab_other, e_tab_wrong, e_tab_rem = st.tabs([
            f"All Workflows ({len(current_assets)})",
            f"💳 Subscriptions ({len(subs_list)})",
            f"💰 Financial & Probate ({len(fin_list)})",
            f"☁️ Cloud Data Takeout ({len(cloud_list)})",
            f"📱 Memorialization ({len(social_list)})",
            f"📁 Other ({len(other_list)})",
            f"⚠️ Wrongly Attributed ({len(wrongly_attributed_list)})",
            f"🗑️ Removed by Owner ({len(removed_list)})",
        ])

        def render_executor_cards(assets_subset: List[Asset], tab_prefix: str = "all"):
            if not assets_subset:
                st.info("No accounts cataloged in this category.")
                return

            for asset_obj in assets_subset:
                death_pol = asset_obj.death_policy
                cancel_pol = asset_obj.cancel_policy

                is_wrong = asset_obj.status == "Wrongly Attributed"
                is_rem_owner = asset_obj.status == "Removed"
                is_done = asset_obj.status in ["Completed", "Cancelled", "Archived"]

                if is_wrong:
                    status_emoji = "⚠️"
                elif is_rem_owner:
                    status_emoji = "🗑️"
                elif is_done:
                    status_emoji = "✅"
                else:
                    status_emoji = "⚙️"

                user_label = f" [{asset_obj.username}]" if asset_obj.username else ""
                expander_title = (
                    f"{status_emoji} {asset_obj.service}{user_label} ({asset_obj.category}) — "
                    f"Assigned: {asset_obj.heir} [{asset_obj.status}]"
                )

                with st.expander(expander_title, expanded=not is_done):
                    if is_wrong:
                        st.warning("⚠️ **Flagged as Wrongly Attributed**: This account is flagged as not belonging to the deceased estate. It remains locked in the audit log for legal protection and safety.")
                    elif is_rem_owner:
                        st.warning("🗑️ **Marked as Removed by Account Owner**: This account was removed from active view by the owner before passing. It is retained in the estate records to prevent fraudulent concealment of assets.")

                    details = asset_obj.display_details()
                    d1, d2 = st.columns(2)
                    d1.write(f"**Provider URL:** {asset_obj.service_address or 'N/A'}")
                    d2.write(f"**Username / Identifier:** {asset_obj.username or 'N/A'}")
                    if details:
                        det_cols = st.columns(min(len(details), 4))
                        for idx, (k, v) in enumerate(details.items()):
                            det_cols[idx % min(len(details), 4)].write(f"**{k}:** {v}")

                    st.divider()

                    st.info(f"**{asset_obj.service} Posthumous Policy:** {death_pol.summary}")
                    if death_pol.security_warning:
                        st.warning(f"**Security Alert:** {death_pol.security_warning}")

                    portal = death_pol.official_portal_url or cancel_pol.target_url or asset_obj.service_address
                    if portal and portal.startswith("http"):
                        st.markdown(f"🔗 [Direct Support / Deceased Account Portal]({portal})")

                    st.write(f"**Action Plan:** {cancel_pol.action_name} (`{cancel_pol.execution_method}`)")
                    if cancel_pol.steps:
                        st.write("**Executor Checklist:**")
                        for s_idx, step in enumerate(cancel_pol.steps):
                            st.markdown(f"{s_idx + 1}. {step}")

                    if cancel_pol.required_documents:
                        st.write("**Required Documentation:**")
                        for doc in cancel_pol.required_documents:
                            st.markdown(f"- {doc}")

                    action_text = generate_action_email(
                        asset=asset_obj,
                        executor_name=asset_obj.heir if asset_obj.heir != "Unassigned" else "Authorized Heir",
                        deceased_name="John Doe",
                        account_email=asset_obj.username or None,
                    )
                    st.text_area(
                        "Legal Notice / Execution Dispatcher",
                        action_text,
                        height=140,
                        key=f"cat_exec_notice_{tab_prefix}_{asset_obj.id}",
                    )

                    c_chk, c_attrib = st.columns([1, 1], vertical_alignment="center")
                    with c_chk:
                        toggle = st.checkbox(
                            "Mark action complete",
                            value=is_done,
                            key=f"cat_exec_done_{tab_prefix}_{asset_obj.id}",
                            disabled=is_wrong,
                        )
                        if toggle != is_done:
                            asset_obj.status = "Completed" if toggle else "In Progress"
                            asset_obj.cancel_policy.status = "Completed" if toggle else "In Progress"
                            st.rerun()

                    with c_attrib:
                        if is_wrong:
                            if st.button("↩️ Re-attribute to Estate", key=f"cat_exec_reattrib_{tab_prefix}_{asset_obj.id}", width='stretch'):
                                asset_obj.status = "Active"
                                st.rerun()
                        else:
                            if st.button("⚠️ Flag as Wrongly Attributed", key=f"cat_exec_wrong_{tab_prefix}_{asset_obj.id}", width='stretch', help="Flag this account if it does not belong to the deceased. It will be kept in the audit log for safety."):
                                asset_obj.status = "Wrongly Attributed"
                                st.rerun()

        with e_tab_all:
            render_executor_cards(current_assets, tab_prefix="all")
        with e_tab_sub:
            render_executor_cards(subs_list, tab_prefix="sub")
        with e_tab_fin:
            render_executor_cards(fin_list, tab_prefix="fin")
        with e_tab_cloud:
            render_executor_cards(cloud_list, tab_prefix="cloud")
        with e_tab_social:
            render_executor_cards(social_list, tab_prefix="social")
        with e_tab_other:
            render_executor_cards(other_list, tab_prefix="other")
        with e_tab_wrong:
            render_executor_cards(wrongly_attributed_list, tab_prefix="wrong")
        with e_tab_rem:
            render_executor_cards(removed_list, tab_prefix="rem")


# =============================================================================
# =============================================================================
# PAGE 2: FIND ASSETS (Automated Discovery & Email Connectors)
# =============================================================================
# =============================================================================
else:
    c_back, c_title = st.columns([1, 4])
    with c_back:
        if st.button("⬅️ Back to Catalogue", width='stretch'):
            st.session_state.active_page = "Catalogue"
            st.rerun()
    with c_title:
        st.header("Find & Discover Digital Assets")
        st.caption("Scan email inboxes or upload statement files to auto-detect subscriptions and digital services.")

    st.divider()

    # Section A: Email Provider Discovery
    st.markdown("#### 📧 Connect Email Provider")
    st.write(
        "Connect an email account to discover recurring subscriptions, service receipts, and registered accounts automatically."
    )

    col_email_btn, col_email_info = st.columns([1, 2])
    with col_email_btn:
        # Button: 'Add email account' -> opens the popup dialog
        if st.button("📧 Add email account", type="primary", width='stretch'):
            email_connection_dialog()

    with col_email_info:
        st.caption("Supported providers: **Gmail** (Google Workspace and Personal). More providers coming soon.")
        if st.session_state.get("gmail_credentials"):
            st.caption("✅ Gmail connected for this session — it is scanned when you run discovery.")
            if st.button("Disconnect Gmail", key="gmail_disconnect_btn"):
                st.session_state.pop("gmail_credentials", None)
                st.rerun()

    oauth_message = st.session_state.pop("oauth_message", None)
    if oauth_message:
        kind, text = oauth_message
        (st.success if kind == "success" else st.error)(text)

    st.divider()

    # Section B: File Statement Ingestion
    st.markdown("#### 📄 Upload Statements or Invoice Exports")
    st.write("Upload a transaction export for AI parsing. Gmail (if connected) and the file are scanned together.")
    st.caption("Currently supported: transactions as **JSONL** or **JSON**. PDF, CSV and TXT statements are not supported yet.")

    uploaded_disc_file = st.file_uploader(
        "Upload Bank Statement, Invoices, or Mail Export",
        type=["jsonl", "json", "pdf", "csv", "txt"],
        key="disc_page_file_uploader",
    )

    def run_discovery(use_llm: bool) -> None:
        """Runs the subscription finder and adds new subscriptions to the vault."""
        bar = st.progress(0.0, text="Starting discovery...")
        try:
            result = parse_and_extract(
                uploaded_disc_file,
                gmail_credentials=st.session_state.get("gmail_credentials"),
                use_llm=use_llm,
                progress=lambda message, fraction: bar.progress(min(max(fraction, 0.0), 1.0), text=message),
            )
        except DiscoveryInputError as exc:
            bar.empty()
            st.error(str(exc))
            return
        except LLMConfigError as exc:
            bar.empty()
            st.session_state.discovery_llm_error = str(exc)
            return
        except ReconnectRequired:
            bar.empty()
            st.session_state.pop("gmail_credentials", None)
            st.warning("Gmail access has expired or was revoked. Please connect your Gmail account again.")
            return
        except MalformedFinderResult:
            bar.empty()
            st.error("The subscription finder returned an unexpected result. Nothing was added to the vault.")
            return
        except Exception as exc:
            bar.empty()
            st.error(f"Discovery failed ({type(exc).__name__}): {exc}")
            return

        st.session_state.pop("discovery_llm_error", None)
        existing_keys = {a.unique_key for a in st.session_state.assets}
        added_count = 0
        for asset in result.extracted_assets:
            if asset.unique_key not in existing_keys:
                st.session_state.assets.append(asset)
                existing_keys.add(asset.unique_key)
                added_count += 1

        st.session_state.discovery_message = (
            f"Discovery complete! Extracted {len(result.extracted_assets)} items "
            f"({added_count} new cataloged). Detected potential recurring drain: "
            f"{result.detected_recurring_monthly_drain:.2f}/mo. Detected subscriptions are marked 🔍 until you check them. "
            f"{result.notes or ''}"
        )
        st.rerun()

    col_run_disc, _ = st.columns([1, 3])
    with col_run_disc:
        run_clicked = st.button("Run AI Discovery", width='stretch')
    if run_clicked:
        run_discovery(use_llm=True)

    if st.session_state.get("discovery_llm_error"):
        st.warning(
            f"The AI model is not configured: {st.session_state.discovery_llm_error} "
            "You can run discovery with rules only (less precise names and confidence)."
        )
        if st.button("Run discovery without AI (rules only)", key="disc_rules_only_btn"):
            run_discovery(use_llm=False)

    discovery_message = st.session_state.pop("discovery_message", None)
    if discovery_message:
        st.success(discovery_message)

    st.divider()

    # Section C: Direct Manual Asset Entry Option
    st.markdown("#### ➕ Manual Asset Entry")
    st.caption("Manually add a single digital service directly to your estate vault.")
    if st.button("➕ Add Asset", key="btn_add_find_page", width='stretch'):
        modal_add_asset_dialog(default_category="Subscription")