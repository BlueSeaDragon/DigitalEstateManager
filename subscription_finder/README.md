# Subscription Finder

Finds **one person's paid recurring subscriptions** in their Gmail and bank transactions and writes
`subscriptions.json`: raw sources → evidence → subscription inference → explanation.
Deterministic rules detect recurring charges; the Swisscom-hosted **Apertus** model reads billing
emails and reviews, names and explains the findings. See [`docs/design.md`](docs/design.md).

## Setup

```bash
cd subscription_finder
pip install -e ".[dev]"
cp .env.example .env        # then fill in SWISSCOM_API_KEY and SWISSCOM_BASE_URL
```

`.env`, `credentials.json`, `token.json`, `output/` and `.cache/` are gitignored. Never commit them.
Without an API key, use `--no-llm` (rules only; nothing is sent to the LLM).

### Gmail setup (once)

1. In [Google Cloud Console](https://console.cloud.google.com/) create a project and enable the **Gmail API**.
2. *APIs & Services → OAuth consent screen*: type **External**, add your Google account as a **test user**.
3. *Credentials → Create credentials → OAuth client ID*:
   - for the CLI: type **Desktop app**;
   - for the Streamlit app: type **Web application** with redirect URI e.g. `http://localhost:8501`.
4. Download the JSON as `subscription_finder/credentials.json`.

The first `--gmail` run opens a browser for consent (read-only scope `gmail.readonly`) and caches
`token.json`. Delete `token.json` to log out.

## Usage

```bash
# sample dataset, rules only (the sample's cutoff date is 2026-01-01)
subscription-finder --transactions ../data/valid_transactions.jsonl --sample-client C000002 \
    --reference-date 2026-01-01 --no-llm --out output/subscriptions.json

# own Gmail + a transaction file, with Apertus
subscription-finder --gmail --transactions my_transactions.jsonl --out output/subscriptions.json
```

Options: `--gmail-max N` (emails to read, default 500), `--reference-date` (default today),
`--credentials`, `--token`, `-v`.

Transactions are JSONL with `timestamp, amount, currency, direction, type, description, mcc`
(one person per file; `--sample-client` only selects a person in the multi-person sample data).

## Output

```jsonc
{
  "run": { "reference_date": "...", "sources_scanned": {...}, "llm_usage": {...}, "warnings": [] },
  "evidence": [ { "evidence_id": "ev-0001", "type": "transaction", "source_ref": "line:42", "observed": {...} } ],
  "subscriptions": [ {
    "subscription_id": "sub-0001",
    "evidence_ids": ["ev-0001", "..."],
    "observed": { "charge_dates": [], "amounts": [], "currency": "CHF", "email_senders": [], "refunds": [] },
    "inferred": { "service_type": "streaming", "name": null, "amount": 17.9, "billing_cycle": "monthly",
                  "next_expected_date": "...", "status": "active", ... },
    "explanation": "...", "confidence": "high", "confidence_reasons": ["..."]
  } ]
}
```

- `observed` is aggregated from evidence; `inferred` are rule/LLM conclusions.
- `evidence` holds only the records a subscription refers to; snippets are ≤ 200 characters.
- Transaction-only findings get a `service_type` but `name/url/cancel_url = null`: names and URLs
  require billing emails, and the LLM may only set them on the email sender's domain.
- `confidence` is computed by rules: **high** = ≥ 4 very regular charges with a subscription-typical
  MCC, or confirmed by both bank and email; **low** = only 2 charges, or the AI review disagreed.

## Digital footprint (`--footprint`)

Besides subscriptions, the finder can list every service a person has a relationship with —
social media, email, banks, brokers, crypto, payment, cloud storage, developer/cloud services,
password managers, utilities/telecom, insurance, memberships, shopping, travel, entertainment.
A finding means *there is evidence that an account or contract exists*; nothing is accessed.

```bash
subscription-finder --gmail --transactions my_transactions.jsonl --footprint --out output/footprint.json
```

```python
from subscription_finder import FOOTPRINT_TERMS, GmailSource, discover_footprint
result = discover_footprint(email_sources=[GmailSource(creds, terms=FOOTPRINT_TERMS, max_messages=1500)],
                            transactions=uploaded_file)
```

`discover_footprint` returns the `detect_subscriptions` document (subscriptions unchanged) plus:

```jsonc
"accounts": [ {
  "account_id": "acc-0001",
  "service": { "key": "coinbase", "name": "Coinbase", "domain": "coinbase.com" },
  "account_type": "crypto", "account_type_label": "crypto account", "estate_relevance": ["money"],
  "classified_by": "catalog",            // catalog | keywords | subscription | llm
  "evidence_ids": ["ev-0012", "..."],    // strongest first, max 10; each evidence has a "signal" {kind, strength, rule}
  "subscription_ids": [],
  "observed": { "first_seen": "...", "last_seen": "...", "evidence_count": 3,
                "evidence_kinds": { "security": 1, "account_created": 1, "marketing": 1 }, "evidence_omitted": 0 },
  "evidence_strength": "strong", "confidence": "high", "confidence_reasons": ["..."], "explanation": "..."
} ]
```

- **Strong** evidence (→ high confidence): security/login, account creation, statements, invoices,
  contracts/policies, detected subscriptions, the connected mailbox itself. **Medium**: orders/bookings,
  account notices, bank transactions naming the service. **Weak** (→ low): newsletters and marketing.
- Services are identified by sender domain against a catalog (`footprint/catalog.py`), else typed by
  keyword rules. Only unknown services with strong or medium evidence go to Apertus, in one batched call
  with sender domain, sender names and subjects (no bodies). Newsletters from unknown senders are dropped.
- One-time codes in security and sign-up emails are redacted from the evidence.
- New sources (e.g. uploaded documents) plug in as a function returning `Signal`s (`footprint/signals.py`).

## Streamlit integration

```python
from subscription_finder import GmailSource, ReconnectRequired, detect_subscriptions
from subscription_finder.auth import build_authorization_url, exchange_code, credentials_to_dict, credentials_from_dict

REDIRECT = "http://localhost:8501"

@st.cache_resource  # server-side: st.session_state does not survive the round trip to Google
def pending_logins() -> dict:
    return {}

# 1. "Connect Gmail" button
if st.button("Connect Gmail"):
    req = build_authorization_url(REDIRECT)            # uses credentials.json (Web application client)
    pending_logins()[req.state] = req.code_verifier
    st.link_button("Continue to Google", req.url)

# 2. Google redirects back with ?code=...&state=...
params = st.query_params
if "code" in params and params.get("state") in pending_logins():
    verifier = pending_logins().pop(params["state"])   # unknown state -> ignore (CSRF protection)
    creds = exchange_code(params["code"], params["state"], REDIRECT, code_verifier=verifier)
    st.session_state.gmail = credentials_to_dict(creds)
    st.query_params.clear()

# 3. "Run AI Discovery"
if st.button("Run AI Discovery"):
    bar = st.progress(0.0)
    try:
        sources = [GmailSource(credentials_from_dict(st.session_state.gmail))] if "gmail" in st.session_state else []
        result = detect_subscriptions(email_sources=sources, transactions=uploaded_file,
                                      progress=lambda msg, f: bar.progress(f, text=msg))
    except ReconnectRequired:
        st.warning("Gmail access expired; please connect again.")
```

`detect_subscriptions(...)` returns the same dict as `subscriptions.json`. It raises
`LLMConfigError` when the LLM is enabled but not configured (pass `use_llm=False` to skip it).
Persist `credentials_to_dict(...)` wherever the app keeps the user's account data if the
connection should outlive the browser session.

## Tests and evaluation

```bash
pytest                      # offline unit tests
pytest -m live              # one real Apertus call (needs .env)
python scripts/evaluate.py  # 100 sample people, rules only -> output/eval_report.json
python scripts/evaluate.py --n 30 --llm   # spends Apertus tokens (answers are cached in .cache/llm)
```

The sample labels only name the category of each person's *next* recurring merchant, and many
`none` people still have subscriptions, so recall and false-alarm figures are approximate.

## Privacy

- Data leaves the machine only to Google (fetching) and Swisscom (LLM, Swiss-hosted); `--no-llm` sends nothing.
- Only headers and the first 1500 characters of each candidate billing email go to the LLM.
- Logs contain counts and IDs only. Full emails and statements are never copied into the output.
