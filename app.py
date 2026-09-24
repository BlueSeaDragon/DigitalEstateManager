import streamlit as st
import pandas as pd

st.set_page_config(page_title="Digital Legacy Vault", page_icon="🔐", layout="wide")

# 1. State Management & Mock Fallback Data
if "assets" not in st.session_state:
    st.session_state.assets = [
        {"Service": "Spotify", "Type": "Subscription", "Cost": "$10.99/mo", "Heir": "Alex", "Action": "Cancel", "Status": "Active"},
        {"Service": "Google Drive", "Type": "Cloud Storage", "Cost": "$2.99/mo", "Heir": "Jordan", "Action": "Transfer & Archive", "Status": "Active"},
        {"Service": "Coinbase", "Type": "Crypto / Finance", "Cost": "N/A", "Heir": "Alex", "Action": "Probate Recovery", "Status": "Active"}
    ]

# 2. Sidebar Navigation & Role Simulation
st.sidebar.title("🔐 Legacy Manager")
mode = st.sidebar.radio("View Mode", ["Account Owner", "Heir / Executor"])

# --- OWNER VIEW ---
if mode == "Account Owner":
    st.header("Digital Asset Vault")
    st.caption("Identify, categorize, and assign your digital footprint.")
    
    # File ingestion trigger
    uploaded_file = st.file_uploader("Upload Bank Statement or Mail Export", type=["pdf", "json", "csv"])
    if st.button("Run AI Discovery"):
        with st.spinner("Analyzing statements for recurring charges..."):
            # Teammate 2 hook goes here:
            # new_assets = parse_and_extract(uploaded_file)
            st.success("Discovered 3 subscriptions and 1 financial account!")
    
    st.subheader("Your Cataloged Assets")
    df = pd.DataFrame(st.session_state.assets)
    edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
    st.session_state.assets = edited_df.to_dict("records")

# --- HEIR / EXECUTOR VIEW ---
else:
    st.header("Post-Mortem Execution Hub")
    st.caption("Secure access unlocked via Heir Verification Key.")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Identified Services", len(st.session_state.assets))
    col2.metric("Monthly Drain Prevented", "$13.98")
    col3.metric("Critical Recoveries", "1 (Coinbase)")
    
    st.divider()
    st.subheader("Actionable Steps & Legal Workflows")
    
    for idx, asset in enumerate(st.session_state.assets):
        with st.expander(f"⚙️ {asset['Service']} ({asset['Type']}) — Assigned to: {asset['Heir']}"):
            st.write(f"**Recommended Legal Action:** {asset['Action']}")
            
            # Policy guidance (Teammate 3 hook)
            if asset['Service'] == "Spotify":
                st.info("Spotify Policy: Subscriptions automatically lapse upon non-payment, but immediate cancellation prevents credit card fraud.")
                st.text_area("Generated Cancellation Request Email", 
                             f"Subject: Account Closure Notice - Deceased Account Holder\n\nPlease close account associated with user...", 
                             key=f"email_{idx}")
            elif asset['Service'] == "Google Drive":
                st.warning("Google Policy: Inactive Account Manager will trigger data download link to the designated heir after 3 months.")
            
            st.checkbox("Mark action complete", key=f"done_{idx}")