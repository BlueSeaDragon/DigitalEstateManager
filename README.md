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

3. **Configure Gmail and the AI model** (optional; without them, upload a JSONL transaction file and run rules-only):
   - Put the Google OAuth **Web application** client JSON at `config/credentials_web.json` (gitignored), with
     `http://localhost:8501` as an authorized redirect URI. The CLI keeps using its own desktop client.
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