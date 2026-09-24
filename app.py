import pandas as pd
import streamlit as st

from digital_estate_manager.discovery import parse_and_extract
from digital_estate_manager.models import Asset
from digital_estate_manager.policies import generate_action_email, lookup_policy
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

            # Avoid duplicate service entries
            existing_services = {a["Service"].strip().lower() for a in st.session_state.assets}
            added_count = 0

            for asset in result.extracted_assets:
                if asset.service.lower() not in existing_services:
                    st.session_state.assets.append(asset.to_table_row())
                    existing_services.add(asset.service.lower())
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
    st.caption("Review and edit services, heirs, and assigned post-mortem actions.")
    df = pd.DataFrame(st.session_state.assets)
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
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
        # Teammate 3 hook: src/digital_estate_manager/policies/rules.py
        policy = lookup_policy(asset_obj.service)

        status_emoji = "✅" if asset_obj.status == "Completed" else "⚙️"
        expander_title = (
            f"{status_emoji} {asset_obj.service} ({asset_obj.category}) — "
            f"Assigned to: {asset_obj.heir} [{asset_obj.status}]"
        )

        with st.expander(expander_title):
            st.write(f"**Recommended Legal Action:** {asset_obj.action}")

            # Platform policy guidance
            if policy:
                st.info(f"**{policy.service} Policy:** {policy.company_policy}")

                if policy.security_warning:
                    st.warning(f"**Security Notice:** {policy.security_warning}")

                if policy.required_documents:
                    st.write("**Required Documentation:**")
                    for doc in policy.required_documents:
                        st.markdown(f"- {doc}")

                if policy.portal_url:
                    st.markdown(f"🔗 [Direct Support / Deceased Account Portal]({policy.portal_url})")

            # Generated legal email draft (Teammate 3 hook: policies/generator.py)
            email_draft = generate_action_email(
                asset=asset_obj,
                executor_name=asset_obj.heir if asset_obj.heir != "Unassigned" else "Authorized Heir",
                deceased_name="John Doe",
            )
            st.text_area(
                "Generated Legal Request / Notice",
                email_draft,
                height=150,
                key=f"email_{idx}",
            )

            is_completed = asset_obj.status == "Completed"
            toggle = st.checkbox("Mark action complete", value=is_completed, key=f"done_{idx}")

            if toggle != is_completed:
                st.session_state.assets[idx]["Status"] = "Completed" if toggle else "In Progress"
                st.rerun()