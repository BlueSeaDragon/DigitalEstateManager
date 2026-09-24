from typing import Dict, Optional, Tuple
from digital_estate_manager.models.schemas import CancelPolicy, DeathPolicy


# =============================================================================
# Knowledge Base: Deceased Policies by Provider
# =============================================================================

KNOWN_DEATH_POLICIES: Dict[str, DeathPolicy] = {
    "spotify": DeathPolicy(
        summary=(
            "Subscriptions automatically lapse upon non-payment. However, immediate cancellation "
            "prevents credit card fraud and lingering recurring charges."
        ),
        inactivity_period_days=30,
        supports_legacy_contact=False,
        requires_probate=False,
        required_documents=["Death Certificate (or proof of authority)", "Account email or billing address"],
        data_disposition="lapse_on_nonpayment",
        official_portal_url="https://support.spotify.com/article/deceased-user/",
        security_warning="Never share login passwords over unencrypted email channels.",
    ),
    "google": DeathPolicy(
        summary=(
            "Google's Inactive Account Manager automatically triggers after the configured inactivity period "
            "(default 3 months) and emails designated trusted contacts a secure download link."
        ),
        inactivity_period_days=90,
        supports_legacy_contact=True,
        requires_probate=False,
        required_documents=[
            "Death Certificate",
            "Proof of heirship / Court Order",
            "Government-issued ID of requester",
        ],
        data_disposition="transfer_to_heir",
        official_portal_url="https://support.google.com/accounts/troubleshooter/6357590",
        security_warning="Google does NOT provide passwords or bypass 2-Factor Authentication directly.",
    ),
    "coinbase": DeathPolicy(
        summary=(
            "Crypto holdings are subject to formal probate. Coinbase requires court-certified letters "
            "testamentary or letters of administration to transfer or liquidate digital assets."
        ),
        inactivity_period_days=None,
        supports_legacy_contact=False,
        requires_probate=True,
        required_documents=[
            "Certified Copy of Death Certificate",
            "Letters Testamentary or Letters of Administration from Probate Court",
            "Valid Government ID of the Executor",
            "Signed formal closure letter",
        ],
        data_disposition="transfer_to_heir",
        official_portal_url="https://help.coinbase.com/en/coinbase/managing-my-account/other/how-do-i-gain-access-to-a-deceased-family-members-coinbase-account",
        security_warning="High-risk target for impersonation fraud. Ensure all documents are verified.",
    ),
}

KNOWN_POLICIES = KNOWN_DEATH_POLICIES

KNOWN_CANCEL_POLICIES: Dict[str, CancelPolicy] = {
    "spotify": CancelPolicy(
        action_type="cancel_subscription",
        action_name="Cancel Subscription",
        execution_method="email_notice",
        target_url="https://support.spotify.com/article/deceased-user/",
        support_email="support@spotify.com",
        required_documents=["Death Certificate", "Proof of Executor Authority"],
        steps=[
            "Generate formal account closure request notice",
            "Attach death certificate documentation",
            "Transmit notice to Spotify customer billing support",
            "Confirm termination of recurring payment authorization",
        ],
        email_template=(
            "To Spotify Support,\n\n"
            "I am writing as the authorized legal representative / executor for {deceased_name}.\n"
            "Service: {service} ({service_address})\n"
            "Account / Username: {username}\n\n"
            "Please terminate the premium subscription immediately and close the account.\n"
            "Attached please find documentation confirming executor authority.\n\n"
            "Sincerely,\n{executor_name}"
        ),
    ),
    "google": CancelPolicy(
        action_type="transfer_and_archive",
        action_name="Transfer & Archive",
        execution_method="web_portal",
        target_url="https://support.google.com/accounts/troubleshooter/6357590",
        required_documents=[
            "Certified Death Certificate",
            "Proof of Heirship / Court Order",
            "Requester Photo ID",
        ],
        steps=[
            "Access the Google Deceased User Request troubleshooter portal",
            "Select 'Obtain data from a deceased user's account'",
            "Upload government ID and certified death certificate",
            "Wait for Google Trust & Safety review and secure archive link generation",
        ],
    ),
    "coinbase": CancelPolicy(
        action_type="probate_recovery",
        action_name="Probate Recovery",
        execution_method="probate_filing",
        target_url="https://help.coinbase.com/en/coinbase/managing-my-account/other/how-do-i-gain-access-to-a-deceased-family-members-coinbase-account",
        required_documents=[
            "Certified Copy of Death Certificate",
            "Letters Testamentary or Letters of Administration from Probate Court",
            "Government Photo ID of Executor",
            "Formal signed closure demand letter",
        ],
        steps=[
            "File petition in probate court to obtain Letters Testamentary",
            "Initiate an estate case on the Coinbase Deceased Support portal",
            "Upload certified court documentation and executor verification",
            "Authorize asset liquidation or transfer to an estate bank account",
        ],
        email_template=(
            "To Coinbase Estate Support Team,\n\n"
            "I am writing to notify you of the passing of the account holder ({deceased_name}) "
            "and to initiate the formal probate recovery process for their digital asset holdings.\n"
            "Platform: {service} ({service_address})\n"
            "Account / Identifier Address: {username}\n\n"
            "Please advise on your secure portal upload link for submitting the court letters testamentary.\n\n"
            "Sincerely,\n{executor_name}"
        ),
    ),
}


def get_policies_for_service(
    service_name: str,
    service_address: Optional[str] = None,
) -> Tuple[DeathPolicy, CancelPolicy]:
    """Retrieves or synthesizes the appropriate DeathPolicy and CancelPolicy for a service."""
    cleaned_name = service_name.strip().lower()
    cleaned_address = (service_address or "").strip().lower()

    # 1. Match by provider website address
    if cleaned_address:
        for key in KNOWN_DEATH_POLICIES:
            if key in cleaned_address:
                return KNOWN_DEATH_POLICIES[key].model_copy(), KNOWN_CANCEL_POLICIES[key].model_copy()

    # 2. Match by service name
    for key in KNOWN_DEATH_POLICIES:
        if key in cleaned_name:
            return KNOWN_DEATH_POLICIES[key].model_copy(), KNOWN_CANCEL_POLICIES[key].model_copy()

    # 3. Dynamic generic fallback
    death_pol = DeathPolicy(
        summary=f"Standard deceased policy applies for {service_name}. Most providers require death certificate and executor credentials.",
        official_portal_url=service_address if (service_address and service_address.startswith("http")) else None,
    )
    cancel_pol = CancelPolicy(
        action_name=f"Cancel {service_name}",
        action_type="cancel_subscription",
        execution_method="email_notice",
        target_url=service_address if (service_address and service_address.startswith("http")) else None,
        required_documents=["Death Certificate", "Proof of Executor Authority"],
        steps=[
            f"Contact {service_name} customer support",
            "Provide proof of account holder death and executor identity",
            "Request full account closure and cancellation of recurring billing",
        ],
    )
    return death_pol, cancel_pol


def lookup_policy(service_name: str, service_address: Optional[str] = None) -> DeathPolicy:
    """Convenience lookup returning the DeathPolicy for a service."""
    death_policy, _ = get_policies_for_service(service_name, service_address)
    return death_policy
