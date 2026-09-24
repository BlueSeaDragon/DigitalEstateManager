"""Detector protocol: the extension point for new kinds of findings.

Each detector receives all evidence of one person and returns candidates tagged
with its own `category` (e.g. "paid_subscription"; later "online_account", ...).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ..config import Settings
from ..models import Candidate, Evidence


class Detector(Protocol):
    category: str

    def detect(self, evidence: list[Evidence], reference_date: date, settings: Settings) -> list[Candidate]: ...
