"""Storage and Estate Metrics Helper."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from digital_estate_manager.currency import chf, to_chf
from digital_estate_manager.models.schemas import (
    Asset,
    CancelPolicy,
    CloudStorageAssetInfo,
    DeathPolicy,
    FinancialAssetInfo,
    GenericAssetInfo,
    SocialMediaAssetInfo,
    SubscriptionAssetInfo,
)
from digital_estate_manager.policies.legacy import provider_key, with_legacy_record
from digital_estate_manager.policies.rules import get_policies_for_service

# Choices for the owner's wish; "" means no wish set.
WISH_OPTIONS = ["", "Cancel/Deactivate", "Memorialize", "Pass to heir", "Other"]
_OLD_WISHES = {  # options that were merged into "Cancel/Deactivate" after wishes were saved
    "Cancel": "Cancel/Deactivate",
    "Deactivate": "Cancel/Deactivate",
    "Delete account": "Cancel/Deactivate",
}
WISH_FILE = Path(__file__).resolve().parents[3] / "data" / "wishes.json"


def split_wish(wish: str) -> tuple:
    """'Other: give the photos to my sister' -> ('Other', 'give the photos to my sister'); any other wish -> (wish, '')."""
    choice, _, detail = wish.partition(":")
    return ("Other", detail.strip()) if choice == "Other" else (wish, "")


def join_wish(choice: str, detail: str = "") -> str:
    """The wish as saved: the choice, plus the owner's short text for 'Other'."""
    detail = detail.strip()
    return f"Other: {detail}" if choice == "Other" and detail else choice


def _wish_key(asset: Asset) -> str:
    """Stable id of an account: 'drive.google.com|jordan.backup@gmail.com' (asset ids change per session)."""
    return f"{provider_key(asset.service_address) or asset.service.strip().lower()}|{asset.username.strip().lower()}"


def load_wishes() -> Dict[str, str]:
    """The saved wishes; empty if the file is missing or broken."""
    try:
        data = json.loads(WISH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_wishes(assets: List[Asset]) -> None:
    """Save the wish of every given account (empty ones too, so they override the demo defaults)."""
    wishes = load_wishes()
    wishes.update({_wish_key(a): a.wish for a in assets})
    WISH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WISH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(wishes, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, WISH_FILE)


def apply_saved_wishes(assets: List[Asset]) -> List[Asset]:
    """Put the saved wishes on matching accounts (in place)."""
    wishes = load_wishes()
    for asset in assets:
        saved = wishes.get(_wish_key(asset))
        if isinstance(saved, str):
            asset.wish = _OLD_WISHES.get(saved, saved)
    return assets


# Demo persona: Martina Keller, Zurich (docs/design/demo-persona.md). The starter inventory holds the
# accounts she entered herself, paid with her Mastercard, PayPal, Amex or by invoice. The demo scan
# (samples/demo_transactions.jsonl) reads her PostFinance Visa and finds the subscriptions she forgot.
PERSONA_NAME = "Martina Keller"


def _account(service: str, address: str, username: str, infos: list, **fields: Any) -> Asset:
    """One starter account, with the provider's policies looked up."""
    death, cancel = get_policies_for_service(service, address)
    return Asset(service=service, service_address=address, username=username,
                 death_policy=death, cancel_policy=cancel, asset_infos=infos, **fields)


def get_default_assets() -> List[Asset]:
    """The demo persona's starter inventory, with any wishes saved in data/wishes.json on top."""
    assets = [
        _account(
            "Google Drive", "https://drive.google.com", "martina.keller@gmail.com",
            [
                CloudStorageAssetInfo(
                    storage_capacity_gb=2000.0,
                    used_storage_gb=612.4,
                    contains_sensitive_data=True,
                    data_types=["Family Photos", "Tax Returns 2009-2025", "Architecture Portfolio", "Gmail Archive"],
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=10.00,
                    plan_tier="Google One Premium 2 TB",
                    billing_cycle="monthly",
                    renewal_date="2026-10-08",
                    payment_method_hint="Mastercard ending 3309",
                ),
            ],
            heir="Lea Keller",
            wish="Pass to heir",
            notes="Main Google account: Gmail since 2006, Drive and Photos. Inactive Account Manager names Lea.",
        ),
        _account(
            "iCloud", "https://apple.com", "martina.keller@icloud.com",
            [
                CloudStorageAssetInfo(
                    storage_capacity_gb=200.0,
                    used_storage_gb=148.7,
                    contains_sensitive_data=True,
                    data_types=["iPhone Photos", "Notes", "Health Data", "Device Backups"],
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=3.00,
                    plan_tier="iCloud+ 200 GB",
                    billing_cycle="monthly",
                    renewal_date="2026-10-15",
                    payment_method_hint="Mastercard ending 3309",
                ),
            ],
            wish="Other: give the photo library to Thomas, then delete the account",
            notes="Apple ID of her iPhone and iPad. No Legacy Contact set up yet.",
        ),
        _account(
            "Spotify", "https://spotify.com", "martina.keller@gmail.com",
            [
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=17.95,
                    plan_tier="Premium Duo",
                    billing_cycle="monthly",
                    renewal_date="2026-10-03",
                    payment_method_hint="PayPal (martina.keller@gmail.com)",
                ),
            ],
            wish="Other: move the Duo plan to Thomas so he keeps our shared playlists",
            notes="Duo plan shared with Thomas.",
        ),
        _account(
            "Coinbase", "https://coinbase.com", "martina.keller@gmail.com",
            [
                FinancialAssetInfo(
                    currency="CHF",
                    institution_type="crypto_exchange",
                    approximate_balance=18340.00,
                    is_custodial=True,
                    requires_probate=True,
                    account_number_hint="BTC 0.21, ETH 2.4",
                ),
            ],
            heir="Jonas Keller",
            wish="Pass to heir",
            notes="Bought in 2021. 2FA with the authenticator app on her iPhone.",
        ),
        _account(
            "PostFinance e-finance", "https://postfinance.ch", "e-finance ID 7731-0482",
            [
                FinancialAssetInfo(
                    currency="CHF",
                    institution_type="bank",
                    approximate_balance=42800.00,
                    is_custodial=True,
                    requires_probate=True,
                    account_number_hint="CH93 0900 0000 **** 4821",
                ),
            ],
            heir="Thomas Keller",
            wish="Pass to heir",
            notes="Private and savings account. Salary and the Visa card run over this account.",
        ),
        _account(
            "UBS key4 custody account", "https://ubs.com", "Contract 0235-****-01",
            [
                FinancialAssetInfo(
                    currency="CHF",
                    institution_type="brokerage",
                    approximate_balance=96500.00,
                    is_custodial=True,
                    requires_probate=True,
                    account_number_hint="Depot 0235-****-01",
                ),
            ],
            heir="Lea and Jonas Keller",
            wish="Pass to heir",
            notes="ETF savings plan, CHF 500 per month. Split equally between the children, as in the will.",
        ),
        _account(
            "Facebook", "https://facebook.com", "m.keller@bluewin.ch",
            [
                SocialMediaAssetInfo(
                    profile_url="https://facebook.com/martina.keller.zh",
                    memorialization_supported=True,
                    has_legacy_contact_set=True,
                ),
            ],
            wish="Memorialize",
            notes="Legacy contact: Lea Keller. Logs in with the old Bluewin address.",
        ),
        _account(
            "Instagram", "https://instagram.com", "@martina.baut",
            [
                SocialMediaAssetInfo(
                    profile_url="https://instagram.com/martina.baut",
                    memorialization_supported=True,
                    has_legacy_contact_set=False,
                ),
            ],
            wish="Cancel/Deactivate",
            notes="Architecture sketches and site visits, about 1'200 followers.",
        ),
        Asset(
            service="LinkedIn",
            service_address="https://linkedin.com",
            username="martina.keller@gmail.com",
            death_policy=with_legacy_record(
                DeathPolicy(
                    summary="LinkedIn allows accounts to be memorialized or closed upon submission of executor verification and death certificate.",
                    supports_legacy_contact=False,
                    official_portal_url="https://www.linkedin.com/help/linkedin/answer/a1340639",
                ),
                "https://linkedin.com",
            ),
            cancel_policy=CancelPolicy(
                action_name="Memorialize Profile",
                action_type="memorialize",
                execution_method="web_portal",
                target_url="https://www.linkedin.com/help/linkedin/answer/a1340639",
                steps=[
                    "Visit LinkedIn Deceased Member Request form",
                    "Provide link to member profile",
                    "Attach death certificate or obituary link",
                    "Choose whether to memorialize or delete the account",
                ],
            ),
            asset_infos=[
                SocialMediaAssetInfo(
                    profile_url="https://linkedin.com/in/martina-keller-architektin",
                    memorialization_supported=True,
                    has_legacy_contact_set=False,
                ),
                SubscriptionAssetInfo(
                    currency="USD",
                    cost_monthly=39.99,
                    plan_tier="Premium Business",
                    billing_cycle="monthly",
                    renewal_date="2026-10-21",
                    payment_method_hint="American Express ending 1006",
                ),
            ],
            wish="Memorialize",
            notes="Professional profile; founder of Keller Architektur GmbH.",
        ),
        _account(
            "1Password", "https://1password.com", "martina.keller@gmail.com",
            [
                GenericAssetInfo(
                    category_name="Password Manager",
                    custom_properties={"Emergency Kit": "Printed, in the home safe (envelope 'Digital')"},
                ),
                SubscriptionAssetInfo(
                    currency="USD",
                    cost_monthly=4.99,
                    plan_tier="Families",
                    billing_cycle="annual",
                    renewal_date="2027-02-11",
                    payment_method_hint="American Express ending 1006",
                ),
            ],
            heir="Thomas Keller",
            wish="Pass to heir",
            notes="Holds the logins of every other account. Thomas is a member of the family vault.",
        ),
        _account(
            "Hostpoint (keller-architektur.ch)", "https://hostpoint.ch", "Customer no. 418-2207",
            [
                GenericAssetInfo(
                    category_name="Domain & Website",
                    custom_properties={"Domain": "keller-architektur.ch", "Mailboxes": 3},
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=14.90,
                    plan_tier="Business hosting + domain",
                    billing_cycle="annual",
                    renewal_date="2027-01-31",
                    payment_method_hint="Invoice (PostFinance)",
                ),
            ],
            wish="Other: keep the website online for 12 months, then let the domain lapse",
            notes="Website and email of the architecture practice.",
        ),
        Asset(
            service="SBB GA Travelcard",
            service_address="https://sbb.ch",
            username="SwissPass 7AB3-K9XQ (martina.keller@gmail.com)",
            death_policy=with_legacy_record(
                DeathPolicy(
                    summary=(
                        "The GA is personal and cannot be passed on. It ends with the holder's death; the executor "
                        "asks SBB to stop the subscription and to refund the months not yet used."
                    ),
                    supports_legacy_contact=False,
                    requires_probate=False,
                    required_documents=["Death Certificate", "SwissPass card or customer number", "Proof of Executor Authority"],
                    data_disposition="delete",
                    official_portal_url="https://www.sbb.ch/en/help-and-contact.html",
                    security_warning="Block the SwissPass card too: it also holds the ski pass and the PubliBike login.",
                ),
                "https://sbb.ch",
            ),
            cancel_policy=CancelPolicy(
                action_name="Cancel GA subscription",
                action_type="cancel_subscription",
                execution_method="email_notice",
                target_url="https://www.sbb.ch/en/help-and-contact.html",
                required_documents=["Death Certificate", "SwissPass card or customer number", "Proof of Executor Authority"],
                steps=[
                    "Contact SBB customer service (online form or any staffed SBB ticket office)",
                    "Give the SwissPass customer number and send the death certificate",
                    "Ask SBB to end the GA subscription and refund the unused months",
                    "Return or destroy the SwissPass card once SBB confirms",
                ],
                email_template=(
                    "To SBB Customer Service,\n\n"
                    "I am the executor of the estate of {deceased_name}, who has passed away.\n"
                    "Service: {service} ({service_address})\n"
                    "SwissPass / customer account: {username}\n\n"
                    "Please end the GA subscription as of the date of death and refund the months not yet used "
                    "to the estate. The death certificate and my executor authority are attached.\n\n"
                    "Sincerely,\n{executor_name}"
                ),
            ),
            asset_infos=[
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=332.92,
                    plan_tier="GA Travelcard 2nd class, adult (CHF 3'995 per year)",
                    billing_cycle="annual",
                    auto_renew=True,
                    renewal_date="2027-03-01",
                    payment_method_hint="Mastercard ending 3309",
                ),
                GenericAssetInfo(
                    category_name="Public Transport",
                    custom_properties={
                        "SwissPass card": "7AB3-K9XQ, valid until 03/2030",
                        "Also on the card": "Ski pass Flumserberg, PubliBike",
                    },
                ),
            ],
            heir="Thomas Keller",
            wish="Cancel/Deactivate",
            notes="Commutes Zurich-Winterthur for site visits. Renews every March unless cancelled.",
        ),
        Asset(
            service="PureGym",
            service_address="https://puregym.ch",
            username="Member no. 30418877 (martina.keller@gmail.com)",
            death_policy=with_legacy_record(
                DeathPolicy(
                    summary=(
                        "The membership is personal and ends with the member's death. The monthly direct debit continues "
                        "until the executor cancels it, so cancel early and ask for any amount charged after the date "
                        "of death to be refunded."
                    ),
                    supports_legacy_contact=False,
                    requires_probate=False,
                    required_documents=["Death Certificate", "Member number", "Proof of Executor Authority"],
                    data_disposition="lapse_on_nonpayment",
                    official_portal_url="https://puregym.ch",
                ),
                "https://puregym.ch",
            ),
            cancel_policy=CancelPolicy(
                action_name="Cancel gym membership",
                action_type="cancel_subscription",
                execution_method="email_notice",
                target_url="https://puregym.ch",
                required_documents=["Death Certificate", "Member number", "Proof of Executor Authority"],
                steps=[
                    "Send the cancellation notice with the member number to PureGym customer service",
                    "Attach the death certificate and ask for cancellation as of the date of death",
                    "Ask for a refund of any monthly fee charged after the date of death",
                    "Check the next Mastercard statement for a further charge",
                ],
                email_template=(
                    "To PureGym Customer Service,\n\n"
                    "I am the executor of the estate of {deceased_name}, who has passed away.\n"
                    "Service: {service} ({service_address})\n"
                    "Member: {username}\n\n"
                    "Please cancel the membership as of the date of death, stop the monthly payment and refund any "
                    "fee charged after that date. The death certificate is attached.\n\n"
                    "Sincerely,\n{executor_name}"
                ),
            ),
            asset_infos=[
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=49.90,
                    plan_tier="Flex monthly, all Swiss gyms",
                    billing_cycle="monthly",
                    auto_renew=True,
                    renewal_date="2026-12-01",
                    payment_method_hint="Mastercard ending 3309",
                ),
                GenericAssetInfo(
                    category_name="Gym",
                    custom_properties={"Home gym": "PureGym Zürich Oerlikon", "Entry": "App QR code, no card"},
                ),
            ],
            wish="Cancel/Deactivate",
            notes="Monthly membership, cancellable at the end of any month. Goes twice a week before work.",
        ),
        Asset(
            service="Swiss Post customer account",
            service_address="https://post.ch",
            username="SwissID martina.keller@gmail.com",
            death_policy=with_legacy_record(
                DeathPolicy(
                    summary=(
                        "The account is free and tied to her SwissID login. Before closing it, the executor can set up "
                        "mail redirection so letters to Martina reach the estate, then delete the SwissID."
                    ),
                    supports_legacy_contact=False,
                    requires_probate=False,
                    required_documents=["Death Certificate", "Proof of Executor Authority", "Government ID of the executor"],
                    data_disposition="delete",
                    official_portal_url="https://www.post.ch/en/customer-center",
                    security_warning="Mail redirection reroutes bank and tax letters: only the executor should set it up.",
                ),
                "https://post.ch",
            ),
            cancel_policy=CancelPolicy(
                action_name="Redirect mail, then close account",
                action_type="delete_account",
                execution_method="manual_steps",
                target_url="https://www.post.ch/en/customer-center",
                required_documents=["Death Certificate", "Proof of Executor Authority", "Government ID of the executor"],
                steps=[
                    "Order mail redirection to the executor's address at a post office (bring the death certificate)",
                    "Cancel the parcel delivery instructions and the PickPost point",
                    "Ask Swiss Post customer service to close the customer account",
                    "Delete the SwissID login, which other Swiss services also use",
                ],
            ),
            asset_infos=[
                GenericAssetInfo(
                    category_name="Postal Services",
                    custom_properties={
                        "Login": "SwissID (also used for the tax return)",
                        "Delivery address": "Rotbuchstrasse 42, 8037 Zürich",
                        "PickPost point": "Zürich Wipkingen post office",
                        "Parcel instructions": "Leave at the door when absent",
                    },
                ),
            ],
            heir="Thomas Keller",
            wish="Other: redirect mail to Thomas, then close the account",
            notes="Tracks parcels and manages deliveries. Her SwissID login is used for other services too.",
        ),
        _account(
            "Dropbox", "https://dropbox.com", "m.keller@bluewin.ch",
            [
                CloudStorageAssetInfo(
                    storage_capacity_gb=2.0,
                    used_storage_gb=1.6,
                    contains_sensitive_data=False,
                    data_types=["Old Project Plans"],
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=11.99,
                    plan_tier="Plus (cancelled, now Basic)",
                    billing_cycle="monthly",
                    auto_renew=False,
                    payment_method_hint="Mastercard ending 3309",
                ),
            ],
            status="Cancelled",
            notes="Plus plan cancelled in March 2026. The free Basic account with old plans remains.",
        ),
        _account(
            "Galaxus", "https://galaxus.ch", "martina.keller@gmail.com",
            [GenericAssetInfo(category_name="Online Shop", custom_properties={"Saved card": "Mastercard ending 3309"})],
            notes="Shopping account with a saved card and order history. No wish set yet.",
        ),
    ]
    return apply_saved_wishes(assets)


def monthly_cost_chf(asset: Asset) -> float:
    """Monthly recurring cost in CHF (approx.), converting each subscription from its own currency.

    Amounts in currencies missing from the FX table are left out.
    """
    total = 0.0
    for info in asset.asset_infos:
        converted = to_chf(info.get_monthly_cost(), getattr(info, "currency", None))
        if converted:
            total += converted
    return round(total, 2)


def calculate_metrics(assets: List[Asset]) -> Dict[str, Any]:
    """Computes estate overview statistics."""
    # Active accounts (excluding cancelled, removed, and wrongly attributed)
    active_services = [a for a in assets if a.status not in ["Cancelled", "Removed", "Wrongly Attributed"]]
    cancelled_services = [a for a in assets if a.status == "Cancelled"]
    removed_services = [a for a in assets if a.status == "Removed"]
    wrongly_attributed_services = [a for a in assets if a.status == "Wrongly Attributed"]

    valid_estate_assets = [a for a in assets if a.status != "Removed"]
    total_services = len(valid_estate_assets)
    unique_providers = len({f"{a.service.lower()}|{a.service_address.lower()}" for a in valid_estate_assets})

    # Active monthly recurring drain, in CHF (rows can be in different currencies)
    active_monthly_spend = round(sum(monthly_cost_chf(a) for a in active_services), 2)

    # Monthly drain prevented (cancelled items or flagged for cancellation, excluding removed)
    drain_prevented = round(
        sum(
            monthly_cost_chf(a) for a in valid_estate_assets
            if a.status == "Cancelled" or "cancel" in a.cancel_policy.action_name.lower()
        ),
        2,
    )

    critical_recoveries = [
        a for a in valid_estate_assets
        if a.has_type("Crypto / Finance")
        or a.death_policy.requires_probate
        or a.cancel_policy.action_type == "probate_recovery"
    ]

    return {
        "total_services": total_services,
        "unique_providers": unique_providers,
        "active_count": len(active_services),
        "cancelled_count": len(cancelled_services),
        "removed_count": len(removed_services),
        "wrongly_attributed_count": len(wrongly_attributed_services),
        "active_monthly_spend_chf": active_monthly_spend,
        "monthly_drain_prevented_chf": drain_prevented,
        "active_monthly_spend": chf(active_monthly_spend),
        "monthly_drain_prevented": chf(drain_prevented),
        "critical_recovery_count": len(critical_recoveries),
        "critical_services_summary": f"{len(critical_recoveries)} ({', '.join(a.service for a in critical_recoveries)})"
        if critical_recoveries
        else "0",
    }
