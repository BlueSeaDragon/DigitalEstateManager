"""Currency formatting and a fixed demo FX table for CHF totals.

Rows keep their original currency; only totals are converted, and the UI marks them "approx.".
The rates are fixed demo values, not live market data.
"""

from typing import Optional

BASE_CURRENCY = "CHF"

# 1 unit of the currency in CHF (approximate, fixed for the demo).
FX_TO_CHF = {
    "CHF": 1.0,
    "EUR": 0.94,
    "USD": 0.80,
    "GBP": 1.07,
}


def to_chf(amount: Optional[float], currency: Optional[str] = BASE_CURRENCY) -> Optional[float]:
    """Converts `amount` to CHF with the fixed FX table; None if the amount or currency is unknown."""
    if amount is None:
        return None
    rate = FX_TO_CHF.get((currency or BASE_CURRENCY).upper())
    return None if rate is None else amount * rate


def money(amount: float, currency: Optional[str] = BASE_CURRENCY, decimals: int = 2) -> str:
    """Swiss number format with the currency code first: `CHF 1'234.50`."""
    number = f"{abs(amount):,.{decimals}f}".replace(",", "'")
    sign = "-" if amount < 0 else ""
    return f"{sign}{(currency or BASE_CURRENCY).upper()} {number}"


def chf(amount: float, decimals: int = 2) -> str:
    """`CHF 1'234.50`."""
    return money(amount, BASE_CURRENCY, decimals)
