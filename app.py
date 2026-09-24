import pandas as pd
import streamlit as st

from digital_estate_manager.discovery import parse_and_extract
from digital_estate_manager.models import Asset
from digital_estate_manager.policies import generate_action_email
from digital_estate_manager.vault import calculate_metrics, get_default_assets

st.set_page_config(
    page_title="Digital Legacy Vault",
    page_icon="🔐",
    layout="wide",
)

# 1. State Management & Initial Vault Population
if "assets" not in st.session_state:
    st.session_state.assets = [asset.to_table_row() for asset in get_default_assets()]

# 2. Sidebar Navigation & Role Simulation
st.sidebar.title("🔐 Legacy Manager")
mode = st.sidebar.radio("View Mode", ["Account Owner", "Heir / Executor"])

# Convert current table rows to typed domain models
current_assets = [Asset.from_table_row(row) for row in st.session_state.assets]

# --- OWNER VIEW ---
if mode == "Account Owner":
    st.header("Digital Estate Manager")
    st.caption("Identify, categorize, and assign your digital footprint to designated heirs.")

    # File Ingestion & AI Discovery
    st.subheader("1. AI Asset Discovery")
    uploaded_file = st.file_uploader(
        "Upload Bank Statement, Invoices, or Mail Export",
        type=["pdf", "json", "csv", "txt"],
    )

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        run_discovery = st.button("Run AI Discovery", use_container_width=True)

    if run_discovery:
        with st.spinner("Analyzing statements for recurring charges & digital accounts..."):
            # Teammate 2 hook: src/digital_estate_manager/discovery/extractor.py
            result = parse_and_extract(uploaded_file)

            # Avoid duplicates based on composite unique_key (Service + Service Address + Username)
            existing_keys = {Asset.from_table_row(a).unique_key for a in st.session_state.assets}
            added_count = 0

            for asset in result.extracted_assets:
                if asset.unique_key not in existing_keys:
                    st.session_state.assets.append(asset.to_table_row())
                    existing_keys.add(asset.unique_key)
                    added_count += 1

            st.success(
                f"Discovery complete! Extracted {len(result.extracted_assets)} items "
                f"({added_count} new cataloged). Estimated recurring monthly drain: "
                f"${result.detected_recurring_monthly_drain:.2f}."
            )
            st.rerun()

    st.divider()

    # Catalog Management
    st.subheader("2. Your Cataloged Assets")
    st.caption(
        "Manage services, provider addresses (websites), and account usernames (emails/handles)."
    )
    df = pd.DataFrame(st.session_state.assets)
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Service Address": st.column_config.LinkColumn(
                "Service Address",
                help="Website of provider (e.g. https://spotify.com) to distinguish same-name services",
            ),
            "Username": st.column_config.TextColumn(
                "Username",
                help="Account username, email address, or handle to separate multiple accounts under one provider",
            ),
            "Cost": st.column_config.TextColumn("Monthly / Value"),
            "Action": st.column_config.SelectboxColumn(
                "Action",
                options=[
                    "Cancel",
                    "Transfer & Archive",
                    "Probate Recovery",
                    "Memorialize",
                    "Delete Account",
                ],
            ),
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=["Active", "Pending Review", "In Progress", "Completed", "Archived"],
            ),
        },
    )
    st.session_state.assets = edited_df.to_dict("records")

# --- HEIR / EXECUTOR VIEW ---
else:
    st.header("Post-Mortem Execution Hub")
    st.caption("Secure access unlocked via Heir Verification Key.")

    # Dynamic metrics powered by vault service
    metrics = calculate_metrics(current_assets)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Identified Services", metrics["total_services"])
    col2.metric("Monthly Drain Prevented", metrics["monthly_drain_prevented"])
    col3.metric("Critical Recoveries", metrics["critical_services_summary"])

    st.divider()
    st.subheader("Actionable Steps & Legal Workflows")

    for idx, asset_data in enumerate(st.session_state.assets):
        asset_obj = Asset.from_table_row(asset_data)
        death_pol = asset_obj.death_policy
        cancel_pol = asset_obj.cancel_policy

        status_emoji = "✅" if asset_obj.status == "Completed" else "⚙️"
        user_label = f" [{asset_obj.username}]" if asset_obj.username else ""
        expander_title = (
            f"{status_emoji} {asset_obj.service}{user_label} ({asset_obj.category}) — "
            f"Assigned to: {asset_obj.heir} [{asset_obj.status}]"
        )

        with st.expander(expander_title):
            # Display polymorphic asset details
            details = asset_obj.asset_info.display_details()
            detail_cols = st.columns(len(details) + 2)
            detail_cols[0].write(f"**Provider URL:** {asset_obj.service_address or 'N/A'}")
            detail_cols[1].write(f"**Username:** {asset_obj.username or 'N/A'}")
            for col, (k, v) in zip(detail_cols[2:], details.items()):
                col.write(f"**{k}:** {v}")

            st.divider()

            # Platform Death Policy & Posthumous Rules
            st.info(f"**{asset_obj.service} Death Policy:** {death_pol.summary}")

            if death_pol.security_warning:
                st.warning(f"**Security Notice:** {death_pol.security_warning}")

            portal = death_pol.official_portal_url or cancel_pol.target_url or asset_obj.service_address
            if portal and portal.startswith("http"):
                st.markdown(f"🔗 [Direct Support / Deceased Account Portal]({portal})")

            # Execution Plan & Checklist from Cancel Policy
            st.write(f"**Configured Action:** {cancel_pol.action_name} (`{cancel_pol.execution_method}`)")
            if cancel_pol.steps:
                st.write("**Execution Steps:**")
                for s_idx, step in enumerate(cancel_pol.steps):
                    st.markdown(f"{s_idx + 1}. {step}")

            if cancel_pol.required_documents:
                st.write("**Required Documentation:**")
                for doc in cancel_pol.required_documents:
                    st.markdown(f"- {doc}")

            # Generated legal action notice / email via cancel policy
            action_text = generate_action_email(
                asset=asset_obj,
                executor_name=asset_obj.heir if asset_obj.heir != "Unassigned" else "Authorized Heir",
                deceased_name="John Doe",
                account_email=asset_obj.username or None,
            )
            st.text_area(
                "Execution Dispatcher / Action Notice",
                action_text,
                height=150,
                key=f"email_{idx}",
            )

            is_completed = asset_obj.status == "Completed"
            toggle = st.checkbox("Mark action complete", value=is_completed, key=f"done_{idx}")

            if toggle != is_completed:
                st.session_state.assets[idx]["Status"] = "Completed" if toggle else "In Progress"
                st.rerun()