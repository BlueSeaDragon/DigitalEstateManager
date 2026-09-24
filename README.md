# Digital Estate Manager (DEM)

AI-powered digital asset discovery and post-mortem executor platform.

---

## 🚀 Setup & Installation

1. **Create and activate the conda environment**:
   ```bash
   conda create -n DEM python=3.12
   conda activate DEM
   ```

2. **Install dependencies and register the local package in editable mode**:
   ```bash
   pip install -e .
   ```

3. **Run the Streamlit application**:
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
│       ├── discovery/              # Teammate 2: AI extraction & statement ingestion
│       │   └── extractor.py        # parse_and_extract(file) hook
│       ├── policies/               # Teammate 3: Company policies & legal generation
│       │   ├── rules.py            # Platform rules (Spotify, Google, Coinbase, etc.)
│       │   └── generator.py        # Legal notification & email draft generator
│       └── vault/                  # Storage & metrics utilities
│           └── storage.py          # calculate_metrics() & fallback asset loader
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