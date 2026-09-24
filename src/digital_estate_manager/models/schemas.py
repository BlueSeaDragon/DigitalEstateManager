from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator


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

    def get_type_name(self) -> str:
        """Returns standard category name."""
        return "Other"

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

    def get_type_name(self) -> str:
        return "Subscription"

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

    def get_type_name(self) -> str:
        return "Crypto / Finance"

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

    def get_type_name(self) -> str:
        return "Cloud Storage"

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

    def get_type_name(self) -> str:
        return "Social Media"

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

    def get_type_name(self) -> str:
        return self.category_name or "Other"

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
    """Represents a discovered or cataloged digital asset supporting one or more types."""
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
    asset_info: Optional[AnyAssetInfo] = Field(
        default=None,
        description="Primary type-specific asset metadata (maintained for backward compatibility)",
    )
    asset_infos: List[AnyAssetInfo] = Field(
        default_factory=list,
        description="List of type-specific asset metadata models supporting multiple categories",
    )

    # Lifecycle & Ownership
    heir: str = Field(default="Unassigned", description="Designated heir or executor responsible")
    status: AssetStatus = Field(default="Active", description="Execution status")
    notes: Optional[str] = Field(default=None, description="Additional context or account notes")
    user_verified: bool = Field(
        default=True,
        description="Whether the owner has checked this asset themselves (False for automatically discovered assets)",
    )

    @model_validator(mode="before")
    @classmethod
    def sync_asset_infos_before(cls, data: Any) -> Any:
        if isinstance(data, dict):
            infos = list(data.get("asset_infos") or [])
            single = data.get("asset_info")
            if single is not None and single not in infos:
                infos.insert(0, single)
            elif infos and single is None:
                single = infos[0]
            elif not infos and single is None:
                single = GenericAssetInfo()
                infos = [single]
            data["asset_infos"] = infos
            data["asset_info"] = single
        return data

    @model_validator(mode="after")
    def sync_asset_infos_after(self) -> "Asset":
        if not self.asset_infos and self.asset_info:
            self.asset_infos = [self.asset_info]
        elif self.asset_infos and not self.asset_info:
            self.asset_info = self.asset_infos[0]
        elif not self.asset_infos and not self.asset_info:
            gen = GenericAssetInfo()
            self.asset_infos = [gen]
            self.asset_info = gen
        elif self.asset_info and self.asset_info not in self.asset_infos:
            self.asset_infos.insert(0, self.asset_info)
        return self

    # --- Multi-Type Helpers ---
    @property
    def types(self) -> List[str]:
        """List of all category/type names associated with this asset."""
        seen = set()
        res = []
        for info in self.asset_infos:
            t = info.get_type_name()
            if t not in seen:
                seen.add(t)
                res.append(t)
        return res or ["Other"]

    def has_type(self, type_identifier: Any) -> bool:
        """Checks if the asset has a specific category type.

        Accepts type name (e.g. 'Subscription', 'Cloud Storage', 'Crypto / Finance',
        'Social Media', 'Other') or class (e.g. SubscriptionAssetInfo).
        """
        if isinstance(type_identifier, type):
            return any(isinstance(info, type_identifier) for info in self.asset_infos)

        if not isinstance(type_identifier, str):
            return False

        t_clean = type_identifier.lower().strip()
        for t in self.types:
            if t_clean == t.lower().strip():
                return True
            if t_clean in ["crypto", "finance", "crypto / finance", "financial"] and t == "Crypto / Finance":
                return True
            if t_clean in ["cloud", "cloud storage", "storage"] and t == "Cloud Storage":
                return True
            if t_clean in ["social", "social media"] and t == "Social Media":
                return True
            if t_clean in ["sub", "subscription", "membership"] and t == "Subscription":
                return True
        return False

    def get_info(self, type_identifier: Any) -> Optional[AnyAssetInfo]:
        """Returns the specific AssetInfo model instance matching the requested type, or None."""
        if isinstance(type_identifier, type):
            for info in self.asset_infos:
                if isinstance(info, type_identifier):
                    return info
            return None

        if not isinstance(type_identifier, str):
            return None

        t_clean = type_identifier.lower().strip()
        for info in self.asset_infos:
            t = info.get_type_name()
            if t_clean == t.lower().strip():
                return info
            if t_clean in ["crypto", "finance", "crypto / finance", "financial"] and t == "Crypto / Finance":
                return info
            if t_clean in ["cloud", "cloud storage", "storage"] and t == "Cloud Storage":
                return info
            if t_clean in ["social", "social media"] and t == "Social Media":
                return info
            if t_clean in ["sub", "subscription", "membership"] and t == "Subscription":
                return info
        return None

    def add_type_info(self, new_info: AnyAssetInfo) -> None:
        """Adds or updates a type-specific metadata model on this asset."""
        type_name = new_info.get_type_name()
        for i, info in enumerate(self.asset_infos):
            if info.get_type_name() == type_name:
                self.asset_infos[i] = new_info
                if i == 0:
                    self.asset_info = new_info
                return
        self.asset_infos.append(new_info)
        if not self.asset_info:
            self.asset_info = self.asset_infos[0]

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
        """Display category string. If multiple types, joins them with commas."""
        types_list = self.types
        if not types_list:
            return "Other"
        return ", ".join(types_list)

    @property
    def cost_monthly(self) -> Optional[float]:
        """Total monthly recurring cost extracted from any subscription types."""
        costs = [info.get_monthly_cost() for info in self.asset_infos if info.get_monthly_cost() is not None]
        return sum(costs) if costs else None

    @property
    def cost_display(self) -> str:
        """Smart cost/value display across multiple types."""
        fin_info = self.get_info("Crypto / Finance")
        sub_info = self.get_info("Subscription")

        if fin_info and sub_info:
            fin_disp = fin_info.get_cost_display()
            sub_disp = sub_info.get_cost_display()
            if fin_disp != "N/A" and sub_disp != "$0.00/mo":
                return f"{fin_disp} (+{sub_disp})"
            elif fin_disp != "N/A":
                return fin_disp
            return sub_disp

        for info in self.asset_infos:
            disp = info.get_cost_display()
            if disp and disp != "N/A" and disp != "$0.00/mo":
                return disp

        if self.asset_info:
            return self.asset_info.get_cost_display()
        return "N/A"

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

    def display_details(self) -> Dict[str, Any]:
        """Aggregates all known details across all types for this asset."""
        merged: Dict[str, Any] = {}
        if len(self.asset_infos) <= 1:
            for info in self.asset_infos:
                merged.update(info.display_details())
            return merged

        for info in self.asset_infos:
            prefix = info.get_type_name()
            for k, v in info.display_details().items():
                merged[f"[{prefix}] {k}"] = v
        return merged

    @classmethod
    def from_table_row(cls, row: Dict[str, Any]) -> "Asset":
        """Converts a dictionary from st.data_editor into a typed Asset instance supporting multiple types."""
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
        category_raw = str(row.get("Type", row.get("Types", "Other"))).strip()
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

        category_parts = [p.strip() for p in category_raw.split(",") if p.strip()]
        if not category_parts:
            category_parts = [category_raw]

        infos: List[AnyAssetInfo] = []
        for cat in category_parts:
            cat_l = cat.lower()
            if "subscription" in cat_l:
                infos.append(SubscriptionAssetInfo(cost_monthly=cost_monthly or 0.0))
            elif "crypto" in cat_l or "finance" in cat_l:
                infos.append(FinancialAssetInfo(approximate_balance=cost_monthly))
            elif "cloud" in cat_l or "storage" in cat_l:
                infos.append(CloudStorageAssetInfo())
            elif "social" in cat_l:
                infos.append(SocialMediaAssetInfo())
            else:
                infos.append(GenericAssetInfo(category_name=cat))

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
            asset_infos=infos,
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

    def to_type_specific_dict(self, target_type: Optional[str] = None) -> Dict[str, Any]:
        """Returns a tailored dictionary with column names specific to its asset type(s)."""
        base = {
            "Service": self.service,
            "Service Address": self.service_address,
            "Username": self.username,
            "Types": self.category,
            "Status": self.status,
            "Heir": self.heir,
        }

        chosen_info = None
        if target_type:
            chosen_info = self.get_info(target_type)

        if not chosen_info:
            chosen_info = self.asset_info

        if isinstance(chosen_info, SubscriptionAssetInfo):
            base.update({
                "Plan": chosen_info.plan_tier or "Standard",
                "Monthly Cost": chosen_info.get_cost_display(),
                "Billing Cycle": chosen_info.billing_cycle.capitalize(),
                "Renewal Date": chosen_info.renewal_date or "N/A",
                "Payment Method": chosen_info.payment_method_hint or "N/A",
            })
        elif isinstance(chosen_info, FinancialAssetInfo):
            base.update({
                "Institution": chosen_info.institution_type.replace("_", " ").title(),
                "Approx. Value": chosen_info.get_cost_display(),
                "Custodial": "Custodial" if chosen_info.is_custodial else "Self-Custody",
                "Probate Required": "Yes" if chosen_info.requires_probate else "No",
                "Account Hint": chosen_info.account_number_hint or "N/A",
            })
        elif isinstance(chosen_info, CloudStorageAssetInfo):
            cap = f"{chosen_info.storage_capacity_gb:.0f} GB" if chosen_info.storage_capacity_gb else "Unknown"
            used = f"{chosen_info.used_storage_gb:.1f} GB" if chosen_info.used_storage_gb is not None else "N/A"
            base.update({
                "Capacity": cap,
                "Used": used,
                "Data Types": ", ".join(chosen_info.data_types) if chosen_info.data_types else "Files",
                "Sensitive Data": "Yes" if chosen_info.contains_sensitive_data else "No",
            })
        elif isinstance(chosen_info, SocialMediaAssetInfo):
            base.update({
                "Profile URL": chosen_info.profile_url or self.service_address or "N/A",
                "Handle": self.username,
                "Memorialization": "Supported" if chosen_info.memorialization_supported else "No",
                "Legacy Contact": "Configured" if chosen_info.has_legacy_contact_set else "Not Set",
            })
        elif chosen_info:
            base.update(chosen_info.display_details())

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
