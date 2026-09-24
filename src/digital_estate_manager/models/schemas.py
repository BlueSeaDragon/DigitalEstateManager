from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


AssetCategory = Literal[
    "Subscription",
    "Cloud Storage",
    "Crypto / Finance",
    "Social Media",
    "Email & Domain",
    "Utilities & Bills",
    "Other",
]

ActionType = Literal[
    "Cancel",
    "Transfer & Archive",
    "Probate Recovery",
    "Memorialize",
    "Delete Account",
    "Custom Action",
]

AssetStatus = Literal[
    "Active",
    "Pending Review",
    "In Progress",
    "Completed",
    "Archived",
]


class Asset(BaseModel):
    """Represents a discovered or cataloged digital asset."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    service: str = Field(..., description="Name of the service (e.g., Spotify, Google Drive, Coinbase)")
    service_address: str = Field(
        default="",
        description="Address / website of the service provider (e.g. https://spotify.com) to distinguish providers with similar names",
    )
    address: str = Field(
        default="",
        description="Account address or identifier (e.g., email address, handle, wallet address) to separate multiple assets from the same provider",
    )
    category: AssetCategory = Field(default="Subscription", description="Category of digital asset")
    cost_monthly: Optional[float] = Field(default=None, description="Normalized monthly cost in USD if recurring")
    cost_display: str = Field(default="N/A", description="Human-readable cost string e.g. '$10.99/mo'")
    heir: str = Field(default="Unassigned", description="Designated heir or executor responsible")
    action: ActionType = Field(default="Cancel", description="Recommended or chosen legal action")
    status: AssetStatus = Field(default="Active", description="Execution status")
    notes: Optional[str] = Field(default=None, description="Additional context or account identifier hints")

    @property
    def account_address(self) -> str:
        """Alias for address (account-specific identifier/email)."""
        return self.address

    @property
    def service_url(self) -> str:
        """Alias for service_address (provider website)."""
        return self.service_address

    @property
    def unique_key(self) -> str:
        """Returns a composite identifier for distinguishing duplicate services and distinct accounts."""
        return (
            f"{self.service.lower().strip()}|"
            f"{self.service_address.lower().strip()}|"
            f"{self.address.lower().strip()}"
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
        address = str(
            row.get("Address")
            or row.get("Account Address")
            or row.get("address", "")
        ).strip()

        category = row.get("Type", "Other")
        cost_raw = str(row.get("Cost", "N/A")).strip()
        heir = str(row.get("Heir", "Unassigned")).strip()
        action = row.get("Action", "Cancel")
        status = row.get("Status", "Active")
        asset_id = str(row.get("id", str(uuid.uuid4())[:8]))

        # Attempt to parse numeric monthly cost if available
        cost_monthly = None
        match = re.search(r"(\d+(\.\d+)?)", cost_raw)
        if match:
            try:
                cost_monthly = float(match.group(1))
            except ValueError:
                cost_monthly = None

        return cls(
            id=asset_id,
            service=service,
            service_address=service_address,
            address=address,
            category=category if category in AssetCategory.__args__ else "Other",
            cost_monthly=cost_monthly,
            cost_display=cost_raw,
            heir=heir,
            action=action if action in ActionType.__args__ else "Cancel",
            status=status if status in AssetStatus.__args__ else "Active",
            notes=str(row.get("Notes", "")) if "Notes" in row else None,
        )

    def to_table_row(self) -> Dict[str, Any]:
        """Converts this Asset instance into a clean dict matching the Streamlit data table."""
        return {
            "Service": self.service,
            "Service Address": self.service_address,
            "Address": self.address,
            "Type": self.category,
            "Cost": self.cost_display,
            "Heir": self.heir,
            "Action": self.action,
            "Status": self.status,
        }


class PolicyGuidance(BaseModel):
    """Platform policy and post-mortem legal workflow guidance."""
    service: str
    service_address: Optional[str] = None
    company_policy: str
    recommended_action: str
    required_documents: List[str] = Field(default_factory=list)
    email_subject_template: Optional[str] = None
    email_body_template: Optional[str] = None
    portal_url: Optional[str] = None
    security_warning: Optional[str] = None


class DiscoveryResult(BaseModel):
    """Output contract for document and email extraction."""
    source_name: str
    extracted_assets: List[Asset] = Field(default_factory=list)
    confidence_score: float = 1.0
    detected_recurring_monthly_drain: float = 0.0
    notes: Optional[str] = None
