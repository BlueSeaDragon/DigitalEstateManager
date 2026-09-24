# Digital Estate Manager (DEM)

AI-powered digital asset discovery and post-mortem executor platform.

---

## 🚀 Setup & Installation

1. **Create and activate the conda environment**:
   ```bash
   conda create -n DEM python=3.12
   conda activate DEM
   ```

2. **Install dependencies and register the local packages in editable mode** (the subscription finder is installed from its local folder):
   ```bash
   pip install -e ./subscription_finder
   pip install -e .
   ```
   > **Already set up before the subscription finder was added?** After pulling, run
   > `pip install -e ./subscription_finder` once. Otherwise discovery shows
   > "The subscription finder is not installed."

3. **Configure Gmail and the AI model** (optional; without them, upload a JSONL transaction file and run rules-only):
   - Put the Google OAuth **Web application** client JSON at `config/credentials_web.json` (gitignored), with
     `http://localhost:8501` as an authorized redirect URI. The CLI keeps using its own desktop client.
     - The file is **not in the repository**. Ask the project owner for it, or create your own in
       [Google Cloud Console](https://console.cloud.google.com/apis/credentials): enable the Gmail API, then
       *Create credentials → OAuth client ID → Web application*, add the redirect URI above and download the JSON.
     - While the OAuth app is in **Testing** mode, only Google accounts listed as **test users** on the
       OAuth consent screen can connect; everyone else gets an "access blocked" error from Google.
       Ask the project owner to add your account.
   - Copy `.env.example` to `.env` and set `SWISSCOM_API_KEY` / `SWISSCOM_BASE_URL`.

4. **Run the Streamlit application** (from the repository root):
   ```bash
   streamlit run app.py
   ```

---

## 📁 Project Architecture & Team Division

The codebase is organized as a decoupled, modular Python package under `src/digital_estate_manager/`:

```text
DigitalEstateManager/
├── src/
│   └── digital_estate_manager/
│       ├── models/                 # Shared Pydantic data schemas
│       │   └── schemas.py          # Asset, PolicyGuidance, DiscoveryResult
│       ├── config.py               # Repo-rooted paths & env (Google web client, redirect URI)
│       ├── discovery/              # Teammate 2: AI extraction & statement ingestion
│       │   ├── email_connector.py  # Gmail OAuth: connect_email_provider / complete_email_connection
│       │   ├── extractor.py        # parse_and_extract(): runs the subscription finder
│       │   └── subscription_adapter.py  # finder subscriptions.json -> DiscoveryResult / Asset
│       ├── policies/               # Teammate 3: Company policies & legal generation
│       │   ├── rules.py            # Platform rules (Spotify, Google, Coinbase, etc.)
│       │   └── generator.py        # Legal notification & email draft generator
│       └── vault/                  # Storage & metrics utilities
│           └── storage.py          # calculate_metrics() & fallback asset loader
├── subscription_finder/            # Standalone package: detects paid subscriptions (Gmail + transactions)
├── config/                         # Local OAuth client secrets (gitignored)
├── app.py                          # Teammate 1: Streamlit UI
├── pyproject.toml
└── README.md
```

### Team Member Workflows

- **Teammate 1 (Frontend / Streamlit)**:
  - Works on [app.py](file:///c:/Users/oarevian/OneDrive%20-%20Arev%20Finances/Documents/DEM/DigitalEstateManager/app.py).
  - Imports domain models and services directly from `digital_estate_manager`.

- **Teammate 2 (Document Ingestion & AI Discovery)**:
  - Works in [src/digital_estate_manager/discovery/extractor.py](file:///c:/Users/oarevian/OneDrive%20-%20Arev%20Finances/Documents/DEM/DigitalEstateManager/src/digital_estate_manager/discovery/extractor.py).
  - Replaces prototype logic with OCR / PDF parsing (e.g. `pypdf`, `pdfplumber`) and LLM extraction.
  - Contract: Returns a `DiscoveryResult` with a list of `Asset` models.

- **Teammate 3 (Policies & Legal Guidance)**:
  - Works in [src/digital_estate_manager/policies/rules.py](file:///c:/Users/oarevian/OneDrive%20-%20Arev%20Finances/Documents/DEM/DigitalEstateManager/src/digital_estate_manager/policies/rules.py) and [generator.py](file:///c:/Users/oarevian/OneDrive%20-%20Arev%20Finances/Documents/DEM/DigitalEstateManager/src/digital_estate_manager/policies/generator.py).
  - Adds platform-specific requirements, document checklists, and email generation templates.

---

## 🔎 Legacy Policy Crawler (`src/legacy_policy_crawler/`)

For a company website it finds the page that states what happens to an account or subscription after the holder's death, and saves the link, a short summary and a few tick boxes in `data/legacy_policies.json`. It only reads public web pages: it never logs in to accounts and does not cancel anything (that is a separate crawler). The agent runs on Apertus 1.5 70B (Swisscom AI Platform).

**Setup** (after pulling, run `pip install -e .` again: new dependencies `httpx`, `beautifulsoup4`, `python-dotenv`, `ddgs`)

1. Copy `.env.example` to `.env` (git-ignored) and paste your Swisscom token: `APERTUS_API_KEY=<token>`. Never commit or share it. The default endpoint is the Swiss AI Weeks one (`.../products/swiss-ai-weeks/apertus-1.5-70b/v1`); a key only works on the product URL it belongs to, so set `APERTUS_BASE_URL` in `.env` if yours differs.
2. Check token, URL and model: `python -m legacy_policy_crawler.llm --ping`

> Windows on ARM: the x64 Miniconda runs fine under emulation. To avoid Anaconda's channel licence prompt, create the environment with `conda create -n DEM -c conda-forge --override-channels python=3.12 pip`.

**Use**

```bash
python -m legacy_policy_crawler google.com spotify.com   # JSON on stdout, saved in data/legacy_policies.json
python -m legacy_policy_crawler netflix.com --trace      # also show the agent's steps (stderr)
python -m legacy_policy_crawler netflix.com --refresh    # crawl again although the website is saved
pytest -q                                                # offline tests, no token needed
```

```python
from legacy_policy_crawler import lookup_legacy_policy

record = lookup_legacy_policy("https://spotify.com")  # 10-40 s the first time, instant afterwards
```

**Output** (`data/legacy_policies.json`, one record per website):

```json
{
  "website": "acme.com",
  "legacy_policy_url": "https://help.acme.com/deceased-users",
  "summary": "Two to three sentences, only what the page states.",
  "tick_boxes": {
    "owner_can_appoint_successor": false,
    "heirs_can_request_access": true,
    "subscription_or_balance_addressed": null,
    "proof_required": true
  },
  "checked": "2026-09-24"
}
```

`true` / `false` means the page says so, `null` means it does not say. A provider without a clear legacy policy is a valid result: `legacy_policy_url` is `"not found"` and `summary` is `"none"`.

Quota: Apertus allows 5 requests/s and 10M input / 2.5M output tokens. The client stays at 4 requests/s and prints the tokens it used (a lookup costs roughly 3-10k input tokens); saved records are reused, so a website costs tokens only once.

Good to know:
- Summaries are machine-written from the linked page: check the source before relying on them. Only company pages count; community, forum and Q&A pages are never used.
- A tick box is `true`/`false` only if the model quoted the page for it and the quote is really on the page; otherwise it is `null`.
- Some sites block bots or disallow the page in `robots.txt` (the crawler respects both). If a promising page cannot be read, the record links to it and the summary comes from the public search result; it says so, and the tick boxes stay `null`.
- Only HTML pages are read (no PDF or Word files). The web search is keyless and can be throttled; then the agent navigates from the homepage instead.