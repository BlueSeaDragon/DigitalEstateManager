"""Prompts for Apertus. All answers are strict JSON."""

from __future__ import annotations

import json
from typing import Any

from ..config import SERVICE_TYPES

EXTRACT_SYSTEM = """You extract billing facts from one email. Reply with ONLY a JSON object:
{"is_billing_email": bool, "merchant": string|null, "amount": number|null, "currency": string|null,
 "billing_cycle_hint": "weekly"|"monthly"|"quarterly"|"yearly"|null, "date": "YYYY-MM-DD"|null}
Rules:
- is_billing_email is true only if the email documents a payment by THIS recipient for a PAID
  recurring service (subscription, membership, plan, contract): a receipt, invoice, bill,
  payment confirmation, renewal confirmation or upcoming-charge notice for their own account.
- Advertising is NEVER a billing email, even when it names a price or a plan: offers, discounts,
  "upgrade to", "get X for $Y/year", trial invitations, price announcements, newsletters.
  If the email tries to sell something rather than confirm a charge, answer false.
- Also false: one-off shop orders, shipping notices, login codes, password resets, security notices.
- merchant: the service's brand name as written in the email, else null.
- amount: the total charged in this email, as a number (e.g. 12.9). currency: ISO code (CHF, EUR, USD, GBP).
- Never guess. Use null for anything the email does not state."""


def extract_user(sender: str, subject: str, date: str, body: str) -> str:
    return f"From: {sender}\nSubject: {subject}\nDate: {date}\n\n{body}"


INTERPRET_SYSTEM = f"""You review candidate recurring charges found by rules in ONE person's bank
transactions and billing emails. For each candidate decide whether it is a PAID recurring subscription
and describe it for the person's heirs. Reply with ONLY a JSON object:
{{"candidates": [{{"id": string, "is_subscription": bool,
  "service_type": one of {list(SERVICE_TYPES)},
  "name": string|null, "url": string|null, "cancel_url": string|null,
  "explanation": string, "llm_reasons": [string]}}]}}
Rules:
- One entry per input candidate, same "id".
- name/url: ONLY if the candidate lists email sender domains or merchant names that identify the
  service; url must be on that sender's domain. Otherwise null. Never invent them.
- cancel_url: copy one of "links_found_in_emails" that manages or cancels the subscription, else null.
- service_type "mobile" covers all telecom contracts: mobile, landline, internet, TV bundles.
- Amounts may vary between bills (see amount_range); mention the range in the explanation.
- explanation: 1-2 plain sentences for a non-technical reader: what is charged, how often, since when,
  and what the evidence is.
- llm_reasons: short factual reasons for your judgement (e.g. "descriptions mention gym membership").
- Groceries, restaurants, transport, cash withdrawals and shopping are not subscriptions even if regular.
- Emails that advertise a price or plan (offers, discounts, "upgrade") are marketing, not subscriptions."""


def interpret_user(candidates: list[dict[str, Any]]) -> str:
    return "Candidates:\n" + json.dumps(candidates, ensure_ascii=False, indent=None)
