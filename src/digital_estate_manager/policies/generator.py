from typing import Optional
from digital_estate_manager.models.schemas import Asset, PolicyGuidance
from digital_estate_manager.policies.rules import lookup_policy


def generate_action_email(
    asset: Asset,
    executor_name: str = "Authorized Executor",
    deceased_name: str = "[Deceased Account Holder]",
    account_email: Optional[str] = None,
) -> str:
    """Generates an email template ready to send to a service provider's legal team,

    disambiguating by account address and provider URL.
    """
    policy: PolicyGuidance = lookup_policy(
        service_name=asset.service,
        service_address=asset.service_address,
    )
    email_addr = account_email or asset.address or asset.notes or "[Account Email / Username]"
    provider_url = asset.service_address or policy.portal_url or "[Provider Website]"

    template = policy.email_body_template or (
        "To Support,\n\n"
        "I am writing regarding the account closure for {deceased_name}.\n"
        "Service: {service} ({provider_url})\n"
        "Account Identifier / Address: {account_email}\n\n"
        "Sincerely,\n{executor_name}"
    )

    rendered_body = template.format(
        service=asset.service,
        provider_url=provider_url,
        executor_name=executor_name,
        deceased_name=deceased_name,
        account_email=email_addr,
    )

    subject = (
        policy.email_subject_template
        or f"Estate Notification: {asset.service} ({email_addr})"
    ).format(
        service=asset.service,
        provider_url=provider_url,
        deceased_name=deceased_name,
        account_email=email_addr,
    )

    return f"Subject: {subject}\n\n{rendered_body}"
