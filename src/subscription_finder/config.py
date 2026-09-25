"""Configuration: environment loading, LLM endpoint and detection thresholds."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

TOOL_VERSION = "0.1.0"
DEFAULT_MODEL = "swiss-ai/Apertus-v1.5-70B"

# subscription_finder/ (the folder holding pyproject.toml and .env)
PROJECT_DIR = Path(__file__).resolve().parents[2]


def load_env() -> None:
    """Load `.env` from the project folder and the current directory (existing env wins)."""
    load_dotenv(PROJECT_DIR / ".env", override=False)
    load_dotenv(find_dotenv(usecwd=True), override=False)


@dataclass(frozen=True)
class Cycle:
    name: str
    period: int  # days
    tolerance: int  # days


CYCLES: tuple[Cycle, ...] = (
    Cycle("weekly", 7, 2),
    Cycle("biweekly", 14, 5),
    Cycle("monthly", 30, 5),
    Cycle("quarterly", 91, 7),
    Cycle("yearly", 365, 15),
)

# MCCs typical for subscriptions: telecom, cable/streaming, software, digital goods,
# continuity merchants, insurance, clubs/gyms, video rental.
SUBSCRIPTION_MCCS = frozenset(
    {"4814", "4899", "5734", "5815", "5816", "5817", "5818", "5968", "6300", "7997", "7841"}
)

SERVICE_TYPES = ("streaming", "music", "software", "cloud", "mobile", "gym", "insurance", "other")


@dataclass
class Settings:
    api_key: str | None = None
    base_url: str | None = None
    model: str = DEFAULT_MODEL
    cache_dir: Path = field(default_factory=lambda: PROJECT_DIR / ".cache" / "llm")
    max_requests_per_second: float = 4.0
    llm_retries: int = 3
    llm_max_tokens: int = 4096  # per request; larger jobs are split into batches
    interpret_batch_size: int = 15  # candidates per review call (~250 answer tokens each)
    email_body_chars: int = 1500
    snippet_chars: int = 200
    gmail_months: int = 24
    gmail_max_messages: int = 500
    # detection thresholds
    amount_tolerance: float = 0.10  # consecutive charges within ±10 %
    min_charges: int = 3
    min_charges_yearly: int = 2
    max_interval_cv: float = 0.25
    # series with the minimum number of charges need a subscription signal (MCC/wording)
    # and a stable price, or an exact price
    weak_series_max_amount_cv: float = 0.05
    exact_price_amount_cv: float = 0.01
    # billing emails from one sender: amounts may vary (utility/phone bills) and not every
    # bill reaches the mailbox, so gaps of up to 3 periods are allowed
    email_max_gap_periods: int = 3
    email_max_missed: int = 6
    high_confidence_cv: float = 0.10
    high_confidence_min_charges: int = 4
    merge_amount_tolerance: float = 0.05
    merge_date_days: int = 3
    refund_window_days: int = 10
    # digital footprint
    gmail_footprint_max_messages: int = 1500
    footprint_max_evidence_per_account: int = 10
    footprint_llm_batch_size: int = 40
    footprint_keep_unknown_weak: bool = False  # newsletters from senders not in the catalog

    @classmethod
    def from_env(cls) -> "Settings":
        load_env()
        return cls(
            api_key=os.environ.get("SWISSCOM_API_KEY") or None,
            base_url=os.environ.get("SWISSCOM_BASE_URL") or None,
            model=os.environ.get("SWISSCOM_MODEL") or DEFAULT_MODEL,
        )
