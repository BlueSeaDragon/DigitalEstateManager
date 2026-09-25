# Subscription Finder — Design

Status: validated design (brainstorming complete), 2026-09-24
Scope: `subscription_finder/` folder only. No changes to `app.py` or other existing files, except `.gitignore` entries.

---

## 1. Understanding Summary

- **What:** A Python tool that scans **one person's** email (Gmail API) and transaction history and writes `subscriptions.json` listing their **paid recurring subscriptions**, structured as *Raw sources → Evidence records → Subscription inference → Explanation*.
- **Why:** (1) Account owners inventory subscriptions when planning their will. (2) After a death, heirs/executors find all subscriptions — replacing the company's current manual search.
- **Who:** Owners, heirs/executors, company staff (CLI), and the team's Streamlit app (library function, integrated later by a teammate).
- **How:** Deterministic rules detect recurring patterns; **Apertus** (Swisscom-hosted, `swiss-ai/Apertus-v1.5-70B`) extracts fields from emails, filters false positives, names/categorizes services and writes explanations.
- **One person per run:** the app has one account per person; they connect their email and upload their own transaction file.
- **v1 scope:** paid recurring subscriptions only, with a pluggable detector/`category` design for later extension (online accounts, financial assets, …).
- **Non-goals:** modifying `app.py`, the ML challenge submission (`sample_submission.csv`), PDF/bank-specific parsers, a UI, cancelling subscriptions.

## 2. Assumptions

1. Self-contained folder `subscription_finder/` with its own `pyproject.toml`, README, tests.
2. `.gitignore` (repo root) gains: `data/`, `.env`, `credentials.json`, `token.json`, `output/`, `.cache/`.
3. Swisscom API key lives in `subscription_finder/.env` as `SWISSCOM_API_KEY` (gitignored); code reads it only via environment (`python-dotenv`). `.env.example` is committed with an empty value.
4. Transaction input for now: the sample dataset in `data/*.jsonl` (synthetic, 2000+ people, fields `client_id, timestamp, amount, currency, direction, type, description, mcc, fee`). A `--sample-client` filter selects one person; real uploads are one person per file and need no filter.
5. Sample descriptions are generic ("media streaming", "cover plan") → transaction-only findings get a **category** but `name/url/cancel_url = null`. Names/URLs require email evidence.
6. Gmail and the sample transactions belong to different people in testing; cross-source merging is implemented but not exercised by the sample data.
7. Gmail: read-only scope (`gmail.readonly`), filtered query, last 24 months; only headers + trimmed body (~1500 chars) are sent to the LLM; evidence stores snippets ≤ 200 chars.
8. Data leaves the machine only to Google (fetch) and Swisscom (LLM, Swiss-hosted). Logs contain only IDs/counts.
9. Swisscom limits: 5 req/s, 10M input / 2.5M output token budget, 262k context. Design: one interpretation call per person + one extraction call per billing email; disk cache; `--no-llm` mode.
10. Hackathon-grade reliability: retries, graceful degradation to rules-only.
11. Stack: Python ≥ 3.10, `openai`, `google-api-python-client`, `google-auth-oauthlib`, `python-dotenv`, `pytest`.

## 3. Decision Log

| # | Decision | Alternatives considered | Why |
|---|----------|------------------------|-----|
| D1 | Email via **Gmail API** | mbox/eml export, IMAP | User requirement; matches "connect your email" UI flow |
| D2 | LLM = **Swisscom-hosted Apertus 1.5 70B** via OpenAI-compatible client | Public AI, HF, local Ollama, configurable backend | User has free hackathon access |
| D3 | v1 detects **only paid recurring subscriptions**, extensible via detectors + `category` | Accounts too; full estate assets | User scope; extensibility requested |
| D4 | **JSON** output with separate `evidence[]` and `subscriptions[]`, `observed` vs `inferred`, `explanation`, `confidence`, `confidence_reasons`, `recurrence_pattern` | Flat CSV; both | Explainability & auditability requirement; maps to app state |
| D5 | **Library + CLI** | CLI only; library only | CLI for staff/dev, library for Streamlit integration |
| D6 | Sample dataset is **test data only**; labels used for evaluation | Also produce challenge submission | User decision |
| D7 | API key in gitignored `.env`, referenced via env var | Hardcoded; config file | Must never be pushed |
| D8 | **Approach A: hybrid** — rules detect recurrence, Apertus interprets candidates | LLM-first; rules-only | Auditable, token-efficient, works offline; uses LLM where it adds value |
| D9 | **Auth decoupled from fetching**: `EmailSource` protocol, credentials injected, auth helpers for both local (CLI) and web (Streamlit button) OAuth flows | Source owns its login flow | Teammate will add a "connect email" button; must plug in without refactor; allows Outlook/IMAP later |
| D10 | **One person per run**; `client_id` only as sample-data filter; loader accepts path or file-like object | Multi-person batch API | App is one account per person; matches `st.file_uploader` |
| D11 | Keep `scripts/evaluate.py` (dev only, `--no-llm` default, sample of 100) | Unit tests only | Needed to tune thresholds and demonstrate accuracy |
| D12 | LLM must not invent name/URL without supporting sender/domain evidence (guardrail nulls it) | Trust LLM output | Heirs act on this data; hallucinated URLs are harmful |
| D13 | Confidence computed by **rules**; LLM only contributes reasons/disagreement | LLM-assigned confidence | Deterministic, explainable |

## 4. Architecture

```
subscription_finder/
├── pyproject.toml
├── .env.example                 # SWISSCOM_API_KEY=
├── README.md                    # setup, Gmail OAuth walkthrough, usage, UI integration, eval
├── docs/design.md
├── src/subscription_finder/
│   ├── __init__.py              # exports detect_subscriptions, GmailSource
│   ├── cli.py
│   ├── config.py                # env loading, endpoint, model, thresholds
│   ├── models.py                # Evidence, Subscription, RunInfo dataclasses
│   ├── auth/gmail_auth.py       # local_login, build_authorization_url, exchange_code, credentials_(to|from)_dict
│   ├── sources/
│   │   ├── email_base.py        # EmailSource protocol
│   │   ├── gmail.py             # GmailSource(credentials)
│   │   └── transactions_jsonl.py
│   ├── extract/email_extractor.py
│   ├── detect/
│   │   ├── base.py              # Detector protocol (extension point)
│   │   ├── recurrence.py
│   │   └── paid_subscription.py
│   ├── llm/client.py            # Swisscom client, retry, rate limit, disk cache
│   ├── llm/prompts.py
│   ├── confidence.py
│   └── output.py
├── scripts/evaluate.py
└── tests/
```

### Public API

```python
detect_subscriptions(
    email_sources: list[EmailSource] = (),
    transactions: str | Path | IO | None = None,
    sample_client_id: str | None = None,   # sample data only
    use_llm: bool = True,
    reference_date: date | None = None,     # default: today
    progress: Callable[[str, float], None] | None = None,
) -> dict
```

### CLI

```
subscription-finder --gmail --transactions ../data/valid_transactions.jsonl \
    --sample-client C000001 --out output/subscriptions.json [--no-llm]
```

### UI integration (teammate, later)

1. Button → `build_authorization_url(redirect_uri)` → user consents at Google.
2. Redirect back → `exchange_code(code, state, redirect_uri)` → `credentials_to_dict` into `st.session_state`.
3. "Run AI Discovery" → `detect_subscriptions(email_sources=[GmailSource(credentials_from_dict(...))], transactions=uploaded_file, progress=...)`.
4. Revoked/expired token raises `ReconnectRequired`.

## 5. Output Schema (`subscriptions.json`)

```json
{
  "run": {
    "generated_at": "...", "tool_version": "0.1.0", "model": "swiss-ai/Apertus-v1.5-70B",
    "reference_date": "2026-01-01",
    "sources_scanned": {
      "email": [{"provider": "gmail", "account": "...", "query": "...", "date_range": ["...", "..."], "messages_scanned": 0, "skipped": 0}],
      "transactions": [{"source": "...", "rows": 0, "skipped": 0}]
    },
    "warnings": []
  },
  "evidence": [
    {"evidence_id": "ev-0001", "type": "transaction", "source": "...", "source_ref": "line:42",
     "observed": {"date": "...", "amount": 17.9, "currency": "CHF", "merchant": "...", "mcc": "5812", "description": "..."}},
    {"evidence_id": "ev-0002", "type": "email", "source": "gmail:...", "source_ref": "msg:...",
     "observed": {"date": "...", "sender": "...", "subject": "...", "snippet": "≤200 chars", "amount": 17.9, "currency": "CHF"}}
  ],
  "subscriptions": [
    {
      "subscription_id": "sub-0001",
      "evidence_ids": ["ev-0001", "ev-0002"],
      "observed": {"charge_dates": [], "amounts": [], "currency": "CHF", "email_senders": [], "refunds": []},
      "inferred": {
        "category": "paid_subscription", "service_type": "streaming",
        "name": null, "url": null, "cancel_url": null,
        "amount": 17.9, "currency": "CHF", "billing_cycle": "monthly", "recurrence_pattern": "30 ± 2 days",
        "first_seen_date": "...", "last_charge_date": "...", "next_expected_date": "...",
        "status": "active", "account_email": null, "payment_method": null
      },
      "explanation": "...",
      "confidence": "high",
      "confidence_reasons": ["..."]
    }
  ]
}
```

`observed` = deterministic aggregation of evidence. `inferred` = rules/LLM conclusions. Full emails and statements are never copied.

## 6. Data Flow & Detection

1. **Load evidence**
   - Transactions → one `Evidence` per row. Only `direction=out` and `type ∈ {card_payment, transfer}` proceed to detection (refund rows kept for refund matching).
   - Email → Gmail query `newer_than:24m (receipt OR invoice OR subscription OR renewal OR "your plan" OR Abo OR Rechnung OR Quittung OR facture) -in:spam` → headers + trimmed body → Apertus extracts `{is_billing_email, merchant, amount, currency, billing_cycle_hint, date}` → non-billing emails dropped.
2. **Candidate grouping (rules, `recurrence.py`)**
   - Group transactions by `(normalized description, mcc, currency)`; emails by `(sender domain, currency)`.
   - Cluster amounts within ±10%.
   - Candidate if ≥ 3 charges (≥ 2 for yearly), median interval matches a cycle (weekly 7±2, monthly 30±4, quarterly 91±7, yearly 365±15), interval CV < 0.25; tolerate one missed period; dedupe same-day charges.
   - Produces `observed`, `recurrence_pattern`, `billing_cycle`, `last_charge_date`, `next_expected_date`; `status = active` if next expected ≥ reference date (with tolerance), else `possibly_cancelled`.
3. **Interpretation (Apertus, one call per person)** — compact candidate list in; strict JSON out per candidate: `is_subscription, service_type (streaming|music|software|cloud|mobile|gym|insurance|other), name, url, cancel_url, explanation, llm_reasons`. Validate; one repair retry; else rules-only fallback.
4. **Cross-source merge** — transaction + email candidates with amount ±5%, same cycle, dates within 3 days → one subscription (corroboration).
5. **Confidence (rules)** — high: ≥ 4 charges & CV < 0.1 & subscription-typical MCC, or cross-source corroboration; medium: meets candidate threshold; low: LLM disagreed, or only 2 charges. Each firing rule adds a `confidence_reason`.

Detectors are the extension point: each receives all evidence and returns subscriptions with its own `category`.

## 7. Error Handling & Edge Cases

- Missing `SWISSCOM_API_KEY` with LLM on → clear error; `--no-llm` works without it.
- Missing `credentials.json` → error pointing to README; failed token refresh → `ReconnectRequired`.
- Gmail errors → backoff; on persistent failure continue with transactions, note in `run.warnings`.
- LLM: 3 retries with backoff, client-side limit 4 req/s; invalid JSON → one repair retry → rules-only fallback (confidence −1 level, reason "LLM interpretation unavailable").
- Guardrail: LLM name/url/cancel_url set to null without supporting sender domain.
- Cache: `.cache/llm/` keyed by hash(model + prompt).
- Price changes, mixed currencies (never converted), missed charges, duplicates, < 2 charges (never a subscription), refunds (noted; full refund → `possibly_cancelled`), empty input (valid empty output + warning), malformed rows/emails (skipped + counted).
- Privacy: no content in logs; snippets ≤ 200 chars; `output/`, `.cache/`, `token.json`, `credentials.json`, `.env` gitignored.

## 8. Testing & Evaluation

- **Unit tests (offline):** recurrence series (exact, jitter, yearly, weekly, price change, missed month, duplicates, noise); loader (path, file-like, sample filter, skip rules, malformed); Gmail source with fake service; extractor/interpreter with fake LLM (invalid JSON, hallucinated URL); confidence rules; output schema + referential integrity; auth dict round-trip and auth URL scope/state.
- **Live smoke test** (`@pytest.mark.live`, skipped by default): one real Apertus call.
- **Evaluation script:** N=100 sampled people from `valid_labels.csv`, `--no-llm` default; reports detection recall (labelled category ∈ detected service types), approximate false-alarm rate on `none` people, per-category breakdown, avg subscriptions/person, tokens used → `output/eval_report.json`.
- **Manual acceptance:** 3 hand-picked sample clients + own Gmail.

## 9. Risks

- Sample data has generic merchants → transaction-only results cannot be named; demo relies on Gmail for names/URLs.
- Labels describe only the *next* recurring merchant → evaluation metrics are approximate.
- Token budget is shared/finite → cache + `--no-llm` defaults for evaluation.
- Gmail OAuth for a web app requires a verified redirect URI and, for external users, Google app verification — out of scope for the hackathon (test users only).
- Swisscom token expiry (60 min) may require key refresh during long runs.

## 10. Implementation Notes (2026-09-24)

Deviations from the sections above, driven by the sample data:

| # | Change | Why |
|---|--------|-----|
| D14 | Transactions are grouped by **currency only**; series are found by a longest-chain search per cycle (consecutive gaps match the cycle, at most one missed period; consecutive amounts within ±10 %), repeated on the leftover charges. | Sample descriptions and MCCs vary within one subscription ("saas billing", "productivity suite", "premium plan"; MCC 5734/5732/5812), so grouping by `(description, mcc)` split every subscription. The chain search also skips noise charges at a similar price. |
| D15 | Added a **biweekly** cycle (14 ± 5) and widened monthly to 30 ± 5. | Many sample subscriptions charge every ~2 weeks, with ±5 days of jitter. |
| D16 | Overlapping series with the same cycle and price are joined (jitter fragments). A series starting one period after another ends, with a price up to 1.5× different, is joined as a **price change**. | Keeps one subscription per service. |
| D17 | Series with only the minimum number of charges (3, or 2 yearly) are kept only with an exact repeated price, or with a subscription signal (subscription MCC or wording on ≥ half of the charges) and amount CV ≤ 5 %. | Removes regular-looking grocery, pharmacy or restaurant noise. |
| D18 | Cross-source merge runs **before** the single LLM interpretation call. | Merging is rule-based; the LLM then sees transaction and email evidence together. |
| D19 | `evidence[]` in the output contains only records a subscription refers to; totals are in `run.sources_scanned`. | Output stays small and holds no unrelated personal transactions. |
| D20 | The endpoint is configured by `SWISSCOM_BASE_URL` in `.env` (next to `SWISSCOM_API_KEY`). | The URL depends on the hackathon access. |
| D21 | `build_authorization_url` returns `url`, `state` and a PKCE `code_verifier`; `exchange_code(..., code_verifier=...)`. | google-auth-oauthlib ≥ 1.2 uses PKCE, and the verifier must survive the redirect. |
| D22 | Advertising is never a billing email (extraction prompt + rules fallback), even when it names a price. | First Gmail test: three Coursera ads ("… for $239/year") became a "weekly subscription". |
| D23 | Billing emails are grouped by sender only, may vary in amount, and may skip up to 2 periods per gap (max 6 missed in total). A gap counts as missed only if one period does not fit. | Phone bills vary (CHF 0–20) and not every bill reaches the mailbox; TalkTalk was missed. A mismatch between an email's cycle wording and the observed timing is not a reason to reject. |
| D24 | `cancel_url` must be a link found verbatim in the emails (query strings stripped); the domain check alone is not enough. | Apertus proposed a plausible but invented `…/cancel-service` path. |
| D25 | Single-receipt subscriptions stay out of scope (≥ 2 charges required). | User decision. |

Baseline (`scripts/evaluate.py`, 100 people, `--no-llm`): recall 0.61 (per category 0.11 music to 0.73 software/streaming), 2.4 subscriptions per person, 0.77 of `none` people have an active detection. The low music recall and the "false alarms" mostly reflect the labels: sample music charges are usually worded like streaming ("media streaming"), and many `none` people (e.g. C000000, C000003) have regular subscription-like charges.
