from typing import Dict, Optional
from digital_estate_manager.models.schemas import PolicyGuidance


KNOWN_POLICIES: Dict[str, PolicyGuidance] = {
    "spotify": PolicyGuidance(
        service="Spotify",
        service_address="https://spotify.com",
        company_policy=(
            "Subscriptions automatically lapse upon non-payment. However, immediate cancellation "
            "prevents credit card fraud and lingering charges."
        ),
        recommended_action="Cancel Subscription",
        required_documents=["Death Certificate (or proof of authority)", "Account email or billing address"],
        email_subject_template="Account Closure Notice - Deceased Account Holder: {service} ({account_email})",
        email_body_template=(
            "To Spotify Support,\n\n"
            "I am writing as the authorized legal representative / executor for {deceased_name}.\n"
            "Please terminate the premium subscription and close the account associated with the address: {account_email}.\n\n"
            "Attached please find documentation confirming executor authority.\n\n"
            "Sincerely,\n{executor_name}"
        ),
        portal_url="https://support.spotify.com/article/deceased-user/",
        security_warning="Never share login passwords over unencrypted email channels.",
    ),
    "google": PolicyGuidance(
        service="Google Drive",
        service_address="https://drive.google.com",
        company_policy=(
            "Google's Inactive Account Manager will trigger after the configured inactivity period "
            "(default 3 months) and email designated trusted contacts a secure download link."
        ),
        recommended_action="Transfer & Archive via Inactive Account Manager",
        required_documents=[
            "Death Certificate",
            "Proof of heirship / Court Order",
            "Government-issued ID of requester",
        ],
        email_subject_template="Google Deceased User Request - {service} ({account_email})",
        email_body_template=(
            "To Google Accounts Support,\n\n"
            "I am submitting a request regarding the digital legacy account for {account_email}.\n"
            "As the designated heir, I am seeking to initiate the inactive account workflow or archive retrieval.\n\n"
            "Sincerely,\n{executor_name}"
        ),
        portal_url="https://support.google.com/accounts/troubleshooter/6357590",
        security_warning="Google does NOT provide passwords or bypass 2-Factor Authentication directly.",
    ),
    "coinbase": PolicyGuidance(
        service="Coinbase",
        service_address="https://coinbase.com",
        company_policy=(
            "Crypto holdings are subject to formal probate. Coinbase requires court-certified letters "
            "testamentary or letters of administration to transfer or liquidate digital assets."
        ),
        recommended_action="Probate Recovery & Custodial Transfer",
        required_documents=[
            "Certified Copy of Death Certificate",
            "Letters Testamentary or Letters of Administration from Probate Court",
            "Valid Government ID of the Executor",
            "Signed formal closure letter",
        ],
        email_subject_template="Estate Resolution / Probate Notification - Coinbase Account ({account_email})",
        email_body_template=(
            "To Coinbase Estate Support Team,\n\n"
            "I am writing to notify you of the passing of the account holder ({deceased_name}) "
            "and to initiate the formal probate recovery process for their digital asset holdings.\n"
            "Account / Identifier Address: {account_email}\n\n"
            "Please advise on your secure portal upload link for submitting the court letters testamentary.\n\n"
            "Sincerely,\n{executor_name}"
        ),
        portal_url="https://help.coinbase.com/en/coinbase/managing-my-account/other/how-do-i-gain-access-to-a-deceased-family-members-coinbase-account",
        security_warning="High-risk target for impersonation fraud. Ensure all documents are verified.",
    ),
}


def lookup_policy(service_name: str, service_address: Optional[str] = None) -> Optional[PolicyGuidance]:
    """Look up policy guidance by service website domain or service name.

    Differentiates providers with similar names by checking the service address first.
    """
    cleaned_name = service_name.strip().lower()
    cleaned_address = (service_address or "").strip().lower()

    # 1. Match by provider website address / domain if present
    if cleaned_address:
        for key, policy in KNOWN_POLICIES.items():
            if key in cleaned_address:
                return policy

    # 2. Match by service name
    for key, policy in KNOWN_POLICIES.items():
        if key in cleaned_name:
            return policy

    # 3. Generic fallback
    return PolicyGuidance(
        service=service_name,
        service_address=service_address,
        company_policy="Standard post-mortem policy applies. Most providers require a death certificate and executor credentials.",
        recommended_action="Contact Customer Support & Request Account Memorialization/Closure",
        required_documents=["Death Certificate", "Executor Authorization Letter", "Photo ID"],
        email_subject_template=f"Account Closure Request - Deceased Account Holder: {service_name} ({{account_email}})",
        email_body_template=(
            f"To {service_name} Customer Support,\n\n"
            f"I am writing to request account closure for {deceased_name}.\n"
            f"Account identifier: {{account_email}}\n"
            f"Service Website: {service_address or 'N/A'}\n\n"
            "Please confirm the required steps and documentation needed from the executor.\n\n"
            "Sincerely,\n{executor_name}"
        ),
        portal_url=service_address if (service_address and service_address.startswith("http")) else None,
    )
