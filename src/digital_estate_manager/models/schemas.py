from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# =============================================================================
# 1. Type-Specific Asset Information (Base & Subclasses)
# =============================================================================

class AssetInfo(BaseModel):
    """Base class for asset-specific metadata.

    Inherited to generate specialized information depending on the type of asset
    (e.g., Subscription, Financial / Crypto, Cloud Storage, Social Media).
    """
    asset_type: str = Field(default="generic", description="Discriminator for the asset type")
    notes: Optional[str] = Field(default=None, description="General context or metadata")

    def display_details(self) -> Dict[str, Any]:
        """Returns human-readable key-value pairs representing the asset information for display."""
        return {"Asset Type": self.asset_type.replace("_", " ").title()}

    def get_monthly_cost(self) -> Optional[float]:
        """Returns monthly cost if applicable, else None."""
        return None

    def get_cost_display(self) -> str:
        """Returns formatted string for cost display."""
        return "N/A"


class SubscriptionAssetInfo(AssetInfo):
    """Specialized info for recurring subscriptions and memberships."""
    asset_type: Literal["subscription"] = "subscription"
    cost_monthly: float = Field(default=0.0, description="Monthly cost in USD or specified currency")
    currency: str = Field(default="USD", description="Currency code (USD, EUR, GBP, etc.)")
    billing_cycle: Literal["monthly", "annual", "quarterly", "weekly"] = Field(
        default="monthly", description="Billing frequency"
    )
    plan_tier: Optional[str] = Field(default=None, description="Plan name/tier (e.g. Premium, Family, Pro)")
    auto_renew: bool = Field(default=True, description="Whether auto-renewal is enabled")
    renewal_date: Optional[str] = Field(default=None, description="Next billing / renewal date")
    payment_method_hint: Optional[str] = Field(default=None, description="e.g. Visa ending 4242 or PayPal")

    def get_monthly_cost(self) -> Optional[float]:
        return self.cost_monthly

    def get_cost_display(self) -> str:
        if self.cost_monthly <= 0:
            return "Free / Included"
        symbol = "$" if self.currency == "USD" else f"{self.currency} "
        return f"{symbol}{self.cost_monthly:.2f}/mo"

    def display_details(self) -> Dict[str, Any]:
        details = {
            "Asset Type": "Subscription",
            "Cost": self.get_cost_display(),
            "Billing Cycle": self.billing_cycle.capitalize(),
        }
        if self.plan_tier:
            details["Plan Tier"] = self.plan_tier
        if self.payment_method_hint:
            details["Payment Method"] = self.payment_method_hint
        if self.renewal_date:
            details["Next Renewal"] = self.renewal_date
        return details


class FinancialAssetInfo(AssetInfo):
    """Specialized info for cryptocurrency, bank accounts, brokerages, and wallets."""
    asset_type: Literal["financial"] = "financial"
    institution_type: Literal["crypto_exchange", "bank", "brokerage", "wallet", "fintech", "other"] = Field(
        default="crypto_exchange", description="Type of financial institution or protocol"
    )
    approximate_balance: Optional[float] = Field(default=None, description="Estimated total balance or valuation")
    currency: str = Field(default="USD", description="Currency or token code (USD, BTC, ETH, etc.)")
    account_number_hint: Optional[str] = Field(default=None, description="Masked account or public wallet address hint")
    is_custodial: bool = Field(default=True, description="Whether assets are held by a custodian or self-custodied")
    requires_probate: bool = Field(default=True, description="Whether court letters of administration are required")

    def get_cost_display(self) -> str:
        if self.approximate_balance is not None:
            symbol = "$" if self.currency == "USD" else f"{self.currency} "
            return f"{symbol}{self.approximate_balance:,.2f}"
        return "Financial Asset (Valuation Pending)"

    def display_details(self) -> Dict[str, Any]:
        details = {
            "Asset Type": "Crypto / Financial",
            "Institution": self.institution_type.replace("_", " ").title(),
            "Custody": "Custodial (Exchange/Bank)" if self.is_custodial else "Self-Custody (Private Key/Seed)",
            "Probate Required": "Yes" if self.requires_probate else "No",
        }
        if self.approximate_balance is not None:
            details["Approx. Value"] = self.get_cost_display()
        if self.account_number_hint:
            details["Account / Wallet Hint"] = self.account_number_hint
        return details


class CloudStorageAssetInfo(AssetInfo):
    """Specialized info for cloud storage, documents, and backups."""
    asset_type: Literal["cloud_storage"] = "cloud_storage"
    storage_capacity_gb: Optional[float] = Field(default=None, description="Total storage limit in GB")
    used_storage_gb: Optional[float] = Field(default=None, description="Used storage in GB")
    contains_sensitive_data: bool = Field(default=True, description="Whether storage contains private documents/photos")
    data_types: List[str] = Field(
        default_factory=lambda: ["Documents", "Photos", "Backups"],
        description="Types of digital content stored",
    )

    def display_details(self) -> Dict[str, Any]:
        details = {
            "Asset Type": "Cloud Storage",
            "Stored Data Types": ", ".join(self.data_types) if self.data_types else "Various Files",
            "Sensitive Data": "Yes" if self.contains_sensitive_data else "No",
        }
        if self.storage_capacity_gb:
            details["Storage Capacity"] = f"{self.storage_capacity_gb:.0f} GB"
        if self.used_storage_gb is not None:
            details["Storage Used"] = f"{self.used_storage_gb:.1f} GB"
        return details


class SocialMediaAssetInfo(AssetInfo):
    """Specialized info for social networks, domains, and public presence."""
    asset_type: Literal["social_media"] = "social_media"
    profile_url: Optional[str] = Field(default=None, description="Direct URL to public profile")
    has_legacy_contact_set: bool = Field(default=False, description="Whether account holder designated a legacy contact")
    memorialization_supported: bool = Field(default=True, description="Whether platform supports memorialization")

    def display_details(self) -> Dict[str, Any]:
        details = {
            "Asset Type": "Social Media / Online Profile",
            "Memorialization": "Supported" if self.memorialization_supported else "Account Closure Only",
            "Legacy Contact Pre-configured": "Yes" if self.has_legacy_contact_set else "No",
        }
        if self.profile_url:
            details["Profile URL"] = self.profile_url
        return details


class GenericAssetInfo(AssetInfo):
    """Fallback info for general digital accounts and utilities."""
    asset_type: Literal["generic"] = "generic"
    category_name: str = Field(default="Other", description="General category label")
    custom_properties: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary custom properties")

    def display_details(self) -> Dict[str, Any]:
        details = {"Asset Type": self.category_name}
        details.update(self.custom_properties)
        return details


AnyAssetInfo = Annotated[
    Union[
        SubscriptionAssetInfo,
        FinancialAssetInfo,
        CloudStorageAssetInfo,
        SocialMediaAssetInfo,
        GenericAssetInfo,
    ],
    Field(discriminator="asset_type"),
]


# =============================================================================
# 2. Death Policy (Terms of Service upon Deceased Account Holder)
# =============================================================================

class DeathPolicy(BaseModel):
    """Provider's posthumous policy, inactive user terms, and legal requirements upon death."""
    summary: str = Field(..., description="Summary of provider policy regarding deceased users")
    inactivity_period_days: Optional[int] = Field(default=None, description="Days of inactivity before provider acts")
    supports_legacy_contact: bool = Field(default=False, description="Whether service has a built-in legacy contact")
    requires_probate: bool = Field(default=False, description="Whether court letters of administration are required")
    required_documents: List[str] = Field(
        default_factory=lambda: ["Death Certificate", "Proof of Executor Authority", "Government ID"],
        description="Documents required by provider",
    )
    data_disposition: Literal["delete", "transfer_to_heir", "memorialize", "lapse_on_nonpayment", "unspecified"] = Field(
        default="unspecified", description="Default provider data handling"
    )
    official_portal_url: Optional[str] = Field(default=None, description="Direct URL to provider's deceased request portal")
    security_warning: Optional[str] = Field(default=None, description="Security alert (e.g. 2FA restrictions, impersonation fraud)")


# =============================================================================
# 3. Cancel Policy (Flexible Action Execution & Dispatcher)
# =============================================================================

ActionCategory = Literal[
    "cancel_subscription",
    "delete_account",
    "transfer_and_archive",
    "probate_recovery",
    "memorialize",
    "custom_action",
]

ExecutionMethod = Literal[
    "email_notice",
    "web_portal",
    "probate_filing",
    "automated_api",
    "manual_steps",
]


class CancelPolicy(BaseModel):
    """Flexible policy model capable of configuring and executing a large variety of actions.

    Supports:
    - Email notifications with customized legal templates
    - Web portal workflows with prerequisite documents
    - Formal probate court filings
    - Automated API / webhook calls
    - Step-by-step manual procedures
    """
    action_type: ActionCategory = Field(default="cancel_subscription", description="Action classification")
    action_name: str = Field(default="Cancel Subscription", description="Human-readable title for the action")
    execution_method: ExecutionMethod = Field(default="email_notice", description="Method used to execute action")
    target_url: Optional[str] = Field(default=None, description="Direct URL to cancellation page or provider portal")
    support_email: Optional[str] = Field(default=None, description="Contact email for closure requests")
    required_documents: List[str] = Field(default_factory=list, description="Documents required (e.g. Death Certificate)")
    steps: List[str] = Field(default_factory=list, description="Ordered step-by-step instructions for the executor")
    email_template: Optional[str] = Field(default=None, description="Pre-filled email template")
    action_payload: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary configuration parameters for custom actions")
    status: Literal["Pending", "In Progress", "Completed", "Failed"] = Field(default="Pending", description="Execution status")
    resolution_notes: Optional[str] = None

    def execute_action(
        self,
        service: str,
        service_address: str,
        username: str,
        executor_name: str = "Authorized Executor",
        deceased_name: str = "Deceased Account Holder",
    ) -> Dict[str, Any]:
        """Prepares or dispatches execution for the configured action."""
        if self.execution_method == "email_notice":
            template = self.email_template or (
                "To Support,\n\n"
                "I am writing as the authorized executor for {deceased_name}.\n"
                "Service: {service} ({service_address})\n"
                "Account: {username}\n\n"
                "Please execute {action_name} for this account.\n\n"
                "Sincerely,\n{executor_name}"
            )
            body = template.format(
                service=service,
                service_address=service_address or "N/A",
                username=username or "N/A",
                action_name=self.action_name,
                executor_name=executor_name,
                deceased_name=deceased_name,
            )
            subject = f"Legal Notice / Account Action: {self.action_name} - {service} ({username})"
            return {
                "method": "email_notice",
                "ready": True,
                "email_subject": subject,
                "email_body": body,
                "recipient": self.support_email or "Provider Support",
                "required_documents": self.required_documents,
            }

        elif self.execution_method == "web_portal":
            return {
                "method": "web_portal",
                "ready": bool(self.target_url),
                "portal_url": self.target_url,
                "steps": self.steps or ["Navigate to the portal", "Upload documentation", "Submit request"],
                "required_documents": self.required_documents,
            }

        elif self.execution_method == "probate_filing":
            return {
                "method": "probate_filing",
                "ready": True,
                "steps": self.steps or [
                    "Obtain court-certified Letters Testamentary",
                    "Submit estate affidavit to provider legal department",
                    "Request asset liquidation or custodial transfer",
                ],
                "required_documents": self.required_documents or ["Certified Death Certificate", "Letters Testamentary", "Executor ID"],
            }

        elif self.execution_method == "automated_api":
            return {
                "method": "automated_api",
                "ready": True,
                "endpoint": self.target_url,
                "payload": self.action_payload,
                "instructions": "Automated API call prepared.",
            }

        else:
            return {
                "method": "manual_steps",
                "ready": True,
                "steps": self.steps or ["Follow provider standard instructions"],
                "required_documents": self.required_documents,
            }

    def get_owner_cancellation_plan(
        self,
        service: str,
        service_address: str,
        username: str,
    ) -> Dict[str, Any]:
        """Provides direct cancellation instructions, portal links, and customer service email drafts

        for the live account owner.
        """
        portal_url = self.target_url or service_address
        steps = [
            f"Sign in to your {service} account using '{username}'.",
            "Go to Account Settings > Subscriptions / Billing.",
            "Click 'Cancel Subscription' or 'Manage Plan' and confirm cancellation.",
            "Verify confirmation email to ensure recurring charges are terminated.",
        ]
        if self.support_email:
            steps.append(f"If direct cancellation is unavailable, contact support at {self.support_email}.")

        email_draft = (
            f"Subject: Request to Cancel Service / Subscription - {service} ({username})\n\n"
            f"To {service} Customer Support,\n\n"
            f"I am requesting the immediate cancellation of my account / subscription associated with {username}.\n"
            f"Please stop all recurring billing authorizations and send confirmation of cancellation.\n\n"
            f"Thank you,\nAccount Owner"
        )

        return {
            "portal_url": portal_url if (portal_url and portal_url.startswith("http")) else None,
            "steps": steps,
            "email_draft": email_draft,
            "support_email": self.support_email,
        }


# =============================================================================
# 4. Asset Model (Core Aggregate)
# =============================================================================

AssetStatus = Literal[
    "Active",
    "Pending Review",
    "In Progress",
    "Completed",
    "Cancelled",
    "Archived",
    "Removed",
    "Wrongly Attributed",
]


class Asset(BaseModel):
    """Represents a discovered or cataloged digital asset."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    service: str = Field(..., description="Name of the service (e.g. Spotify, Google Drive, Coinbase)")
    service_address: str = Field(
        default="",
        description="Address / website of the service provider (e.g. https://spotify.com)",
    )
    username: str = Field(
        default="",
        description="Account username, email address, handle, or identifier",
    )
    death_policy: DeathPolicy = Field(
        ...,
        description="Provider's terms and policy regarding deceased users",
    )
    cancel_policy: CancelPolicy = Field(
        ...,
        description="Actionable policy for canceling, transferring, or resolving this asset",
    )
    asset_info: AnyAssetInfo = Field(
        default_factory=GenericAssetInfo,
        description="Type-specific asset metadata (e.g. Subscription, Financial, CloudStorage)",
    )

    # Lifecycle & Ownership
    heir: str = Field(default="Unassigned", description="Designated heir or executor responsible")
    status: AssetStatus = Field(default="Active", description="Execution status")
    notes: Optional[str] = Field(default=None, description="Additional context or account notes")

    # --- Backward-compatibility and convenience aliases ---
    @property
    def address(self) -> str:
        """Alias for username."""
        return self.username

    @address.setter
    def address(self, val: str) -> None:
        self.username = val

    @property
    def account_address(self) -> str:
        """Alias for username."""
        return self.username

    @property
    def service_url(self) -> str:
        """Alias for service_address."""
        return self.service_address

    @property
    def category(self) -> str:
        """Display category name derived from asset_info."""
        if isinstance(self.asset_info, SubscriptionAssetInfo):
            return "Subscription"
        elif isinstance(self.asset_info, FinancialAssetInfo):
            return "Crypto / Finance"
        elif isinstance(self.asset_info, CloudStorageAssetInfo):
            return "Cloud Storage"
        elif isinstance(self.asset_info, SocialMediaAssetInfo):
            return "Social Media"
        elif isinstance(self.asset_info, GenericAssetInfo):
            return self.asset_info.category_name
        return "Other"

    @property
    def cost_monthly(self) -> Optional[float]:
        """Monthly cost extracted from asset_info."""
        return self.asset_info.get_monthly_cost()

    @property
    def cost_display(self) -> str:
        """Cost display string extracted from asset_info."""
        return self.asset_info.get_cost_display()

    @property
    def action(self) -> str:
        """Current action title from cancel_policy."""
        return self.cancel_policy.action_name

    @property
    def unique_key(self) -> str:
        """Composite identifier for distinguishing duplicate services and distinct accounts."""
        return (
            f"{self.service.lower().strip()}|"
            f"{self.service_address.lower().strip()}|"
            f"{self.username.lower().strip()}"
        )

    @classmethod
    def from_table_row(cls, row: Dict[str, Any]) -> "Asset":
        """Converts a dictionary from st.data_editor into a typed Asset instance."""
        service = str(row.get("Service", "")).strip()
        service_address = str(
            row.get("Service Address")
            or row.get("Service URL")
            or row.get("service_address", "")
        ).strip()
        username = str(
            row.get("Username")
            or row.get("Address")
            or row.get("Account Address")
            or row.get("username", "")
        ).strip()
        category = str(row.get("Type", "Other")).strip()
        cost_raw = str(row.get("Cost", "N/A")).strip()
        heir = str(row.get("Heir", "Unassigned")).strip()
        action_name = str(row.get("Action", "Cancel")).strip()
        status = row.get("Status", "Active")
        asset_id = str(row.get("id", str(uuid.uuid4())[:8]))

        # Parse cost
        cost_monthly = None
        match = re.search(r"(\d+(\.\d+)?)", cost_raw)
        if match:
            try:
                cost_monthly = float(match.group(1))
            except ValueError:
                cost_monthly = None

        # Build asset_info
        if "subscription" in category.lower():
            info: AnyAssetInfo = SubscriptionAssetInfo(cost_monthly=cost_monthly or 0.0)
        elif "crypto" in category.lower() or "finance" in category.lower():
            info = FinancialAssetInfo(approximate_balance=cost_monthly)
        elif "cloud" in category.lower() or "storage" in category.lower():
            info = CloudStorageAssetInfo()
        elif "social" in category.lower():
            info = SocialMediaAssetInfo()
        else:
            info = GenericAssetInfo(category_name=category)

        # Build death_policy
        death_policy = DeathPolicy(
            summary=f"Standard deceased policy for {service}.",
            official_portal_url=service_address if service_address.startswith("http") else None,
        )

        # Build cancel_policy
        method: ExecutionMethod = "email_notice"
        if "probate" in action_name.lower():
            method = "probate_filing"
        elif "archive" in action_name.lower() or "portal" in action_name.lower():
            method = "web_portal"

        cancel_policy = CancelPolicy(
            action_name=action_name,
            execution_method=method,
            target_url=service_address if service_address.startswith("http") else None,
            required_documents=["Death Certificate", "Proof of Heirship"],
        )

        return cls(
            id=asset_id,
            service=service,
            service_address=service_address,
            username=username,
            death_policy=death_policy,
            cancel_policy=cancel_policy,
            asset_info=info,
            heir=heir,
            status=status if status in ["Active", "Pending Review", "In Progress", "Completed", "Cancelled", "Archived", "Removed", "Wrongly Attributed"] else "Active",
            notes=str(row.get("Notes", "")) if "Notes" in row else None,
        )

    def to_table_row(self) -> Dict[str, Any]:
        """Converts this Asset instance into a clean dict matching the Streamlit data table."""
        return {
            "Service": self.service,
            "Service Address": self.service_address,
            "Username": self.username,
            "Type": self.category,
            "Cost": self.cost_display,
            "Heir": self.heir,
            "Action": self.action,
            "Status": self.status,
        }

    def to_type_specific_dict(self) -> Dict[str, Any]:
        """Returns a tailored dictionary with column names specific to its asset type."""
        base = {
            "Service": self.service,
            "Service Address": self.service_address,
            "Username": self.username,
            "Status": self.status,
            "Heir": self.heir,
        }
        if isinstance(self.asset_info, SubscriptionAssetInfo):
            base.update({
                "Plan": self.asset_info.plan_tier or "Standard",
                "Monthly Cost": self.cost_display,
                "Billing Cycle": self.asset_info.billing_cycle.capitalize(),
                "Renewal Date": self.asset_info.renewal_date or "N/A",
                "Payment Method": self.asset_info.payment_method_hint or "N/A",
            })
        elif isinstance(self.asset_info, FinancialAssetInfo):
            base.update({
                "Institution": self.asset_info.institution_type.replace("_", " ").title(),
                "Approx. Value": self.cost_display,
                "Custodial": "Custodial" if self.asset_info.is_custodial else "Self-Custody",
                "Probate Required": "Yes" if self.asset_info.requires_probate else "No",
                "Account Hint": self.asset_info.account_number_hint or "N/A",
            })
        elif isinstance(self.asset_info, CloudStorageAssetInfo):
            cap = f"{self.asset_info.storage_capacity_gb:.0f} GB" if self.asset_info.storage_capacity_gb else "Unknown"
            used = f"{self.asset_info.used_storage_gb:.1f} GB" if self.asset_info.used_storage_gb is not None else "N/A"
            base.update({
                "Capacity": cap,
                "Used": used,
                "Data Types": ", ".join(self.asset_info.data_types) if self.asset_info.data_types else "Files",
                "Sensitive Data": "Yes" if self.asset_info.contains_sensitive_data else "No",
            })
        elif isinstance(self.asset_info, SocialMediaAssetInfo):
            base.update({
                "Profile URL": self.asset_info.profile_url or self.service_address or "N/A",
                "Handle": self.username,
                "Memorialization": "Supported" if self.asset_info.memorialization_supported else "No",
                "Legacy Contact": "Configured" if self.asset_info.has_legacy_contact_set else "Not Set",
            })
        else:
            base.update(self.asset_info.display_details())

        return base



# =============================================================================
# 5. Discovery Contract
# =============================================================================

class DiscoveryResult(BaseModel):
    """Output contract for document and email extraction."""
    source_name: str
    extracted_assets: List[Asset] = Field(default_factory=list)
    confidence_score: float = 1.0
    detected_recurring_monthly_drain: float = 0.0
    notes: Optional[str] = None
