# Demo persona: Martina Keller

One fictional person runs through every screen of the demo. All names, numbers, addresses and
account identifiers are invented.

## Who she is

| | |
|---|---|
| Name | Martina Keller, born 14 March 1968 |
| Home | Rotbuchstrasse 42, 8037 Zürich |
| Work | Architect, founder of Keller Architektur GmbH (salary CHF 7'850 per month) |
| Family | Husband Thomas Keller; children Lea Keller (29) and Jonas Keller (26) |
| Email | `martina.keller@gmail.com` (main), `m.keller@bluewin.ch` (old), `martina.keller@icloud.com` (Apple ID) |
| Bank | PostFinance private account `CH93 0900 0000 **** 4821` with a Visa card |
| Other cards | Mastercard ending 3309, American Express ending 1006, PayPal |

Thomas gets everything the couple shares and the password manager. Lea is the trusted contact for
Google and Facebook. Lea and Jonas share the custody account; Jonas gets the crypto.

## Where the data lives

| Data | File | Used by |
|---|---|---|
| Starter inventory (16 accounts) | `get_default_assets()` in `src/digital_estate_manager/vault/storage.py` | Owner and executor views when onboarding is off |
| 18-month bank and Visa statement | `samples/demo_transactions.jsonl`, made by `samples/make_demo_transactions.py` | *Scan my digital footprint* and onboarding |
| Legacy policies | `data/legacy_policy_demo.json` | Policy summaries of known providers |

The inventory holds the accounts Martina entered herself. Those are paid by Mastercard, PayPal, Amex
or invoice. The statement is her PostFinance account and Visa card, and holds the subscriptions she
forgot. A scan therefore adds new rows (to review) instead of duplicating the inventory.

## What each account demonstrates

| Account | Type | Wish | Shows |
|---|---|---|---|
| Google Drive (2 TB) | Cloud + subscription | Pass to heir: Lea Keller | AI-crawled policy, sensitive data types |
| iCloud (200 GB) | Cloud + subscription | Other: photos to Thomas, then delete | Free-text wish |
| Spotify Premium Duo | Subscription | Other: move plan to Thomas | Crawled policy "not found" |
| Coinbase | Crypto | Pass to heir: Jonas Keller | Probate, critical recovery |
| PostFinance e-finance | Bank | Pass to heir: Thomas Keller | No crawled policy: *Look up* button |
| UBS key4 custody account | Brokerage | Pass to heir: Lea and Jonas Keller | Largest balance |
| Facebook | Social | Memorialize | Legacy contact already set |
| Instagram | Social | Cancel/Deactivate | Close-profile action |
| LinkedIn Premium | Social + subscription (USD) | Memorialize | Hand-written policy, USD converted to CHF |
| 1Password Families | Password manager + subscription (USD) | Pass to heir: Thomas Keller | Generic asset with custom properties |
| Hostpoint (keller-architektur.ch) | Domain + subscription | Other: keep site 12 months | Annual billing |
| SBB GA Travelcard | Subscription (annual) + SwissPass | Cancel/Deactivate | Refund of unused months, email template |
| PureGym | Gym subscription (monthly) | Cancel/Deactivate | Direct debit that runs on until cancelled |
| Swiss Post customer account | Postal services (free) | Other: redirect mail to Thomas | Manual steps, SwissID login |
| Dropbox | Cloud | none | Status *Cancelled* |
| Galaxus | Online shop | none | Wish still to set |

The statement adds, when scanned: Netflix, Swisscom mobile, ChatGPT (USD), NZZ,
Disney+ (new, few charges), Microsoft 365 (yearly), Helsana (standing order) and
Adobe (stopped about 6 months ago, so *possibly cancelled*). Salary, groceries, restaurants, train
class upgrades (she has a GA) and a refunded Zalando order are noise the finder must ignore.

## Before a demo

- `python samples/make_demo_transactions.py` so the history ends today. Seed 52 finds all subscriptions
  with no false series for at least 90 days after 2026-11-05; recheck if you change the data.
- Delete `data/wishes.json` to reset wishes changed during a rehearsal to the persona's defaults.
