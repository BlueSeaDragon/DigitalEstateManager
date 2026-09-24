from typing import Optional
from digital_estate_manager.models.schemas import Asset


def generate_action_email(
    asset: Asset,
    executor_name: str = "Authorized Executor",
    deceased_name: str = "[Deceased Account Holder]",
    account_email: Optional[str] = None,
) -> str:
    """Dispatches the action execution via asset.cancel_policy and returns a ready-to-use notice or execution plan."""
    username = account_email or asset.username or "[Account Identifier]"
    result = asset.cancel_policy.execute_action(
        service=asset.service,
        service_address=asset.service_address,
        username=username,
        executor_name=executor_name,
        deceased_name=deceased_name,
    )

    if result.get("method") == "email_notice":
        return f"Subject: {result.get('email_subject')}\n\n{result.get('email_body')}"

    # For web portals, probate filings, or manual steps: format an actionable executor guide
    steps_list = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(result.get("steps", [])))
    docs_list = "\n".join(f"- {doc}" for doc in result.get("required_documents", []))

    guide_lines = [
        f"Action Plan: {asset.cancel_policy.action_name}",
        f"Execution Method: {result.get('method')}",
        f"Service: {asset.service} ({asset.service_address or 'N/A'})",
        f"Target Account: {username}",
    ]
    if result.get("portal_url"):
        guide_lines.append(f"Portal URL: {result.get('portal_url')}")

    guide_lines.append(f"\nExecution Steps:\n{steps_list}")
    if docs_list:
        guide_lines.append(f"\nRequired Legal Documents:\n{docs_list}")

    return "\n".join(guide_lines)
