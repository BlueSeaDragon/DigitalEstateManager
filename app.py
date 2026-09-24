from typing import List, Optional
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
    subs = [a for a in current_assets if isinstance(a.asset_info, SubscriptionAssetInfo)]
    fin = [a for a in current_assets if isinstance(a.asset_info, FinancialAssetInfo)]
    cloud = [a for a in current_assets if isinstance(a.asset_info, CloudStorageAssetInfo)]
    social = [a for a in current_assets if isinstance(a.asset_info, SocialMediaAssetInfo)]
    other = [
        a for a in current_assets
        if not isinstance(
            a.asset_info,
            (SubscriptionAssetInfo, FinancialAssetInfo, CloudStorageAssetInfo, SocialMediaAssetInfo),
        )
    ]
    return subs, fin, cloud, social, other


subs_list, fin_list, cloud_list, social_list, other_list = get_assets_by_type()

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
        if st.button("Cancel", use_container_width=True, key="email_cancel_btn"):
            st.rerun()

    with c_auth:
        auth_clicked = st.button("🔗 Authorize & Connect Gmail", type="primary", use_container_width=True, key="email_auth_btn")

    if auth_clicked:
        if target_email and "@" not in target_email:
            st.error("Please provide a valid Gmail address.")
            return
        resp = connect_email_provider(provider="gmail", email_address=target_email or None)
        if not resp["success"]:
            st.error(resp["message"])
            return
        st.session_state.oauth_state = resp["state"]
        st.link_button("Continue to Google →", resp["auth_url"], type="primary", use_container_width=True)
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
        st.session_state[key_cat] = default_category
        st.session_state["_last_dialog_default"] = default_category

    current_cat = st.session_state.get(key_cat, default_category)
    default_index = categories.index(current_cat) if current_cat in categories else 0

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

    # Row 2: Account Identifier and Asset Type
    r2_c1, r2_c2 = st.columns(2, vertical_alignment="bottom")
    with r2_c1:
        username_input = st.text_input(
            "Account Identifier / Username / Email*",
            placeholder="e.g. user@gmail.com, @handle",
            key="modal_username",
        )
    with r2_c2:
        # Category dropdown immediately updates type-specific fields below
        selected_category = st.selectbox(
            "Asset Type*",
            categories,
            index=default_index,
            key=key_cat,
            help="Selecting a type dynamically displays the specialized fields for that category.",
        )

    st.markdown("###### Type-Specific Information")

    # DYNAMIC FIELDS - Re-renders immediately when selected_category changes
    if selected_category == "Subscription":
        sub_c1, sub_c2, sub_c3 = st.columns(3, vertical_alignment="top")
        with sub_c1:
            cost_val = st.number_input("Monthly Cost ($)", min_value=0.0, value=12.99, step=1.0, key="modal_sub_cost")
        with sub_c2:
            billing_val = st.selectbox("Billing Frequency", ["monthly", "annual", "quarterly", "weekly"], key="modal_sub_billing")
        with sub_c3:
            tier_val = st.text_input("Plan Tier / Name", placeholder="e.g. Premium Individual, Family", key="modal_sub_tier")
        renewal_val = st.text_input("Next Renewal Date (Optional)", placeholder="YYYY-MM-DD", key="modal_sub_renewal")

    elif selected_category == "Crypto / Finance":
        fin_c1, fin_c2, fin_c3 = st.columns(3, vertical_alignment="top")
        with fin_c1:
            balance_val = st.number_input("Estimated Value / Balance ($)", min_value=0.0, value=1500.0, step=100.0, key="modal_fin_balance")
        with fin_c2:
            inst_val = st.selectbox("Institution Type", ["crypto_exchange", "bank", "brokerage", "wallet", "fintech"], key="modal_fin_inst")
        with fin_c3:
            custody_val = st.selectbox("Custody Model", ["Custodial (Exchange/Bank)", "Self-Custody (Private Key/Wallet)"], key="modal_fin_custody")
        probate_val = st.checkbox("Requires Probate Court Resolution", value=True, key="modal_fin_probate")

    elif selected_category == "Cloud Storage":
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

    elif selected_category == "Social Media":
        soc_c1, soc_c2 = st.columns(2, vertical_alignment="top")
        with soc_c1:
            handle_val = st.text_input("Platform Handle / Profile Name", placeholder="@alex", key="modal_soc_handle")
        with soc_c2:
            profile_url_val = st.text_input("Profile URL", placeholder="https://linkedin.com/in/alex", key="modal_soc_url")
        soc_mem_val = st.checkbox("Platform Supports Memorialization Policy", value=True, key="modal_soc_mem")
        soc_leg_val = st.checkbox("Legacy Contact Pre-configured in Platform Settings", value=False, key="modal_soc_leg")

    else:
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
        if st.button("Cancel", use_container_width=True, key="modal_cancel_btn"):
            st.rerun()

    with c_save:
        save_clicked = st.button("Save Asset", type="primary", use_container_width=True, key="modal_save_btn")

    if save_clicked:
        if not service_input.strip() or not username_input.strip():
            st.error("Please enter both the Service Name and Account Identifier / Username.")
            return

        if selected_category == "Subscription":
            info_obj = SubscriptionAssetInfo(
                cost_monthly=cost_val,
                billing_cycle=billing_val,
                plan_tier=tier_val.strip() if tier_val else None,
                renewal_date=renewal_val.strip() if renewal_val else None,
            )
        elif selected_category == "Crypto / Finance":
            info_obj = FinancialAssetInfo(
                approximate_balance=balance_val,
                institution_type=inst_val,
                is_custodial=("Custodial" in custody_val),
                requires_probate=probate_val,
            )
        elif selected_category == "Cloud Storage":
            info_obj = CloudStorageAssetInfo(
                storage_capacity_gb=cap_val,
                used_storage_gb=used_val,
                data_types=data_types_val,
                contains_sensitive_data=sens_val,
            )
        elif selected_category == "Social Media":
            info_obj = SocialMediaAssetInfo(
                platform_handle=handle_val.strip() if handle_val else None,
                profile_url=profile_url_val.strip() if profile_url_val else None,
                memorialization_supported=soc_mem_val,
                has_legacy_contact_set=soc_leg_val,
            )
        else:
            info_obj = GenericAssetInfo(
                category_name=custom_cat_val.strip() or "Digital Account",
                notes=custom_notes_val.strip() if custom_notes_val else None,
            )

        default_death, default_cancel = get_policies_for_service(service_input, website_input)
        default_cancel.action_name = action_input

        new_asset = Asset(
            service=service_input.strip(),
            service_address=website_input.strip(),
            username=username_input.strip(),
            death_policy=default_death,
            cancel_policy=default_cancel,
            asset_info=info_obj,
            heir=heir_input.strip() or "Unassigned",
            status="Active",
            notes=notes_input.strip() if notes_input else None,
        )

        st.session_state.assets.append(new_asset)
        st.success(f"✅ Successfully cataloged **{new_asset.service}** ({new_asset.username})!")
        st.rerun()


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
    #    if st.button("➕ Add Asset", key="btn_add_header", type="primary", use_container_width=True):
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

        tab_sub, tab_fin, tab_cloud, tab_social, tab_other, tab_all = st.tabs([
            f"💳 Subscriptions ({len(subs_list)})",
            f"💰 Financial & Crypto ({len(fin_list)})",
            f"☁️ Cloud Storage ({len(cloud_list)})",
            f"📱 Social Media ({len(social_list)})",
            f"📁 Other ({len(other_list)})",
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
                if st.button("➕ Add Asset", key="btn_add_sub", use_container_width=True):
                    modal_add_asset_dialog(default_category="Subscription")

            if subs_list:
                sub_rows = [
                    {**a.to_type_specific_dict(), "Checked": "✅" if a.user_verified else "🔍 Not yet"}
                    for a in subs_list
                ]
                st.dataframe(pd.DataFrame(sub_rows), use_container_width=True)

                st.markdown("##### ⚙️ Subscription Actions & Cancellation Center")
                for sub in subs_list:
                    status_badge = {"Cancelled": "🔴 Cancelled", "Pending Review": "🟡 Pending Review"}.get(
                        sub.status, "🟢 Active"
                    )
                    check_marker = "" if sub.user_verified else "🔍 "
                    card_title = f"{check_marker}{sub.service} — {sub.username} [{status_badge} | {sub.cost_display}]"

                    with st.expander(card_title, expanded=(sub.status != "Cancelled")):
                        c1, c2, c3 = st.columns([2, 1, 1])
                        c1.write(f"**Plan Tier:** {getattr(sub.asset_info, 'plan_tier', 'Standard')} | **Billing:** {getattr(sub.asset_info, 'billing_cycle', 'monthly').capitalize()}")
                        c1.write(f"**Next Renewal Date:** {getattr(sub.asset_info, 'renewal_date', 'N/A')}")
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
                                st.link_button("🔗 Open Provider Portal", portal, use_container_width=True)

                        with c3:
                            if sub.status != "Cancelled":
                                if st.button("🚫 Cancel Subscription", key=f"cat_cancel_{sub.id}", use_container_width=True):
                                    sub.status = "Cancelled"
                                    sub.cancel_policy.status = "Completed"
                                    st.success(f"{sub.service} marked as cancelled! Monthly spend updated.")
                                    st.rerun()
                            else:
                                if st.button("🔄 Reactivate", key=f"cat_react_{sub.id}", use_container_width=True):
                                    sub.status = "Active"
                                    sub.cancel_policy.status = "Pending"
                                    st.rerun()

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
                if st.button("➕ Add Asset", key="btn_add_fin", use_container_width=True):
                    modal_add_asset_dialog(default_category="Crypto / Finance")

            if fin_list:
                fin_rows = [a.to_type_specific_dict() for a in fin_list]
                st.dataframe(pd.DataFrame(fin_rows), use_container_width=True)

                for fin in fin_list:
                    status_badge = "🔴 Closed" if fin.status == "Completed" else "🟢 Active"
                    with st.expander(f"{fin.service} — {fin.username} [{status_badge}]"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Institution:** {getattr(fin.asset_info, 'institution_type', '').title()}")
                        c1.write(f"**Approx. Balance:** {fin.cost_display}")
                        c1.write(f"**Custody Type:** {'Custodial (Exchange/Bank)' if getattr(fin.asset_info, 'is_custodial', True) else 'Self-Custody (Wallet)'}")
                        c1.write(f"**Probate Required:** {'Yes' if getattr(fin.asset_info, 'requires_probate', True) else 'No'}")
                        c1.write(f"**Designated Heir:** {fin.heir}")

                        with c2:
                            if fin.service_address.startswith("http"):
                                st.link_button("🔗 Open Platform", fin.service_address, use_container_width=True)
                            if fin.status != "Completed":
                                if st.button("Close Account", key=f"cat_close_fin_{fin.id}", use_container_width=True):
                                    fin.status = "Completed"
                                    st.rerun()
                            else:
                                if st.button("Reopen Account", key=f"cat_reopen_fin_{fin.id}", use_container_width=True):
                                    fin.status = "Active"
                                    st.rerun()
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
                if st.button("➕ Add Asset", key="btn_add_cloud", use_container_width=True):
                    modal_add_asset_dialog(default_category="Cloud Storage")

            if cloud_list:
                cloud_rows = [a.to_type_specific_dict() for a in cloud_list]
                st.dataframe(pd.DataFrame(cloud_rows), use_container_width=True)

                for cl in cloud_list:
                    with st.expander(f"{cl.service} — {cl.username} [{cl.status}]"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Storage Capacity:** {getattr(cl.asset_info, 'storage_capacity_gb', 'N/A')} GB | **Used:** {getattr(cl.asset_info, 'used_storage_gb', 'N/A')} GB")
                        c1.write(f"**Stored Content:** {', '.join(getattr(cl.asset_info, 'data_types', []))}")
                        c1.write(f"**Contains Sensitive Documents:** {'Yes' if getattr(cl.asset_info, 'contains_sensitive_data', True) else 'No'}")
                        c1.write(f"**Designated Heir:** {cl.heir}")

                        with c2:
                            if cl.service_address.startswith("http"):
                                st.link_button("🔗 Manage Storage", cl.service_address, use_container_width=True)
                            if cl.status != "Cancelled":
                                if st.button("Cancel Plan", key=f"cat_cancel_cloud_{cl.id}", use_container_width=True):
                                    cl.status = "Cancelled"
                                    st.rerun()
                            else:
                                if st.button("Reactivate Plan", key=f"cat_react_cloud_{cl.id}", use_container_width=True):
                                    cl.status = "Active"
                                    st.rerun()
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
                if st.button("➕ Add Asset", key="btn_add_soc", use_container_width=True):
                    modal_add_asset_dialog(default_category="Social Media")

            if social_list:
                social_rows = [a.to_type_specific_dict() for a in social_list]
                st.dataframe(pd.DataFrame(social_rows), use_container_width=True)

                for soc in social_list:
                    with st.expander(f"{soc.service} — {soc.username} [{soc.status}]"):
                        c1, c2 = st.columns([2, 1])
                        c1.write(f"**Platform Profile:** {getattr(soc.asset_info, 'profile_url', soc.service_address)}")
                        c1.write(f"**Handle:** {getattr(soc.asset_info, 'platform_handle', soc.username)}")
                        c1.write(f"**Memorialization Supported:** {'Yes' if getattr(soc.asset_info, 'memorialization_supported', True) else 'No'}")
                        c1.write(f"**Legacy Contact Set:** {'Yes' if getattr(soc.asset_info, 'has_legacy_contact_set', False) else 'Not Configured'}")
                        c1.write(f"**Designated Heir:** {soc.heir}")

                        with c2:
                            portal = getattr(soc.asset_info, "profile_url", None) or soc.service_address
                            if portal and portal.startswith("http"):
                                st.link_button("🔗 View Profile", portal, use_container_width=True)
                            if soc.status != "Archived":
                                if st.button("Archive Profile", key=f"cat_close_soc_{soc.id}", use_container_width=True):
                                    soc.status = "Archived"
                                    st.rerun()
                            else:
                                if st.button("Unarchive Profile", key=f"cat_unarchive_soc_{soc.id}", use_container_width=True):
                                    soc.status = "Active"
                                    st.rerun()
            else:
                st.info("No social media accounts cataloged. Click '➕ Add Asset' above to add one.")

        # --- TAB 5: OTHER ACCOUNTS ---
        with tab_other:
            col_o_title, col_o_add = st.columns([3, 1])
            with col_o_title:
                st.markdown("#### 📁 Other Digital Accounts & Utilities")
            with col_o_add:
                # Add Asset button opening the dialog box pre-configured for Other
                if st.button("➕ Add Asset", key="btn_add_oth", use_container_width=True):
                    modal_add_asset_dialog(default_category="Other")

            if other_list:
                other_rows = [a.to_type_specific_dict() for a in other_list]
                st.dataframe(pd.DataFrame(other_rows), use_container_width=True)
            else:
                st.info("No other accounts cataloged. Click '➕ Add Asset' above to add one.")

        # --- TAB 6: MASTER CATALOG ---
        with tab_all:
            col_m_title, col_m_add = st.columns([3, 1])
            with col_m_title:
                st.markdown("#### 📋 Master Asset Catalog")
                st.caption("Tabular view of all assets in your estate vault.")
            with col_m_add:
                if st.button("➕ Add Asset", key="btn_add_master", use_container_width=True):
                    modal_add_asset_dialog(default_category="Subscription")

            df = pd.DataFrame([a.to_table_row() for a in current_assets])
            edited_df = st.data_editor(
                df,
                use_container_width=True,
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
                        options=["Active", "Pending Review", "In Progress", "Completed", "Cancelled", "Archived"],
                    ),
                },
            )

    # -------------------------------------------------------------------------
    # Heir / Executor View in Catalogue
    # -------------------------------------------------------------------------
    else:
        st.subheader("Post-Mortem Execution Hub (Heir / Executor)")
        st.caption("Organized legal workflows, death policies, and dispatch notices separated by asset category.")

        e_tab_all, e_tab_sub, e_tab_fin, e_tab_cloud, e_tab_social, e_tab_other = st.tabs([
            f"All Workflows ({len(current_assets)})",
            f"💳 Subscriptions ({len(subs_list)})",
            f"💰 Financial & Probate ({len(fin_list)})",
            f"☁️ Cloud Data Takeout ({len(cloud_list)})",
            f"📱 Memorialization ({len(social_list)})",
            f"📁 Other ({len(other_list)})",
        ])

        def render_executor_cards(assets_subset: List[Asset], tab_prefix: str = "all"):
            if not assets_subset:
                st.info("No accounts cataloged in this category.")
                return

            for asset_obj in assets_subset:
                death_pol = asset_obj.death_policy
                cancel_pol = asset_obj.cancel_policy

                is_done = asset_obj.status in ["Completed", "Cancelled", "Archived"]
                status_emoji = "✅" if is_done else "⚙️"
                user_label = f" [{asset_obj.username}]" if asset_obj.username else ""
                expander_title = (
                    f"{status_emoji} {asset_obj.service}{user_label} ({asset_obj.category}) — "
                    f"Assigned: {asset_obj.heir} [{asset_obj.status}]"
                )

                with st.expander(expander_title, expanded=not is_done):
                    details = asset_obj.asset_info.display_details()
                    d_cols = st.columns(len(details) + 2)
                    d_cols[0].write(f"**Provider URL:** {asset_obj.service_address or 'N/A'}")
                    d_cols[1].write(f"**Username:** {asset_obj.username or 'N/A'}")
                    for c, (k, v) in zip(d_cols[2:], details.items()):
                        c.write(f"**{k}:** {v}")

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

                    toggle = st.checkbox(
                        "Mark action complete",
                        value=is_done,
                        key=f"cat_exec_done_{tab_prefix}_{asset_obj.id}",
                    )
                    if toggle != is_done:
                        asset_obj.status = "Completed" if toggle else "In Progress"
                        asset_obj.cancel_policy.status = "Completed" if toggle else "In Progress"
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


# =============================================================================
# =============================================================================
# PAGE 2: FIND ASSETS (Automated Discovery & Email Connectors)
# =============================================================================
# =============================================================================
else:
    c_back, c_title = st.columns([1, 4])
    with c_back:
        if st.button("⬅️ Back to Catalogue", use_container_width=True):
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
        if st.button("📧 Add email account", type="primary", use_container_width=True):
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
        run_clicked = st.button("Run AI Discovery", use_container_width=True)
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
    if st.button("➕ Add Asset", key="btn_add_find_page", use_container_width=True):
        modal_add_asset_dialog(default_category="Subscription")