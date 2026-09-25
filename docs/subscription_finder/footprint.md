# Digital footprint (`--footprint`)

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
- Services are identified by sender domain against a catalog (`src/subscription_finder/footprint/catalog.py`), else typed by
  keyword rules. Only unknown services with strong or medium evidence go to Apertus, in one batched call
  with sender domain, sender names and subjects (no bodies). Newsletters from unknown senders are dropped.
- One-time codes in security and sign-up emails are redacted from the evidence.
- New sources (e.g. uploaded documents) plug in as a function returning `Signal`s (`src/subscription_finder/footprint/signals.py`).
