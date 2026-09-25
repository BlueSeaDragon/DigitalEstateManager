# VZ-inspired redesign of Digital Legacy Vault

Status: design approved, 2026-09-24. Branch: `feat/vz-redesign`.

## 1. Understanding summary

- **What:** a two-phase redesign of the Streamlit app *Digital Legacy Vault*. Phase 1 is a visual
  overhaul of the existing UI; Phase 2 adds a pitch flow: Problem → Scan → Discovery → Evidence → Action.
- **Why:** to pitch the product to VZ VermögensZentrum as something that already looks at home in their
  ecosystem. We borrow VZ's design language; we do not clone their brand.
- **For whom:** first the VZ judges, who see a narrated screen recording; then account owners and
  heirs/executors.
- **Constraints:** keep Streamlit, a single `app.py` entry point, and the existing state and flows.
  Backend changes are additive only.
- **Non-goals:** a pixel clone, VZ's logo or name in the UI, new auth or persistence,
  "Powered by AI" messaging.

### Audit: why the current UI reads as AI-generated

1. Emojis on every header, tab, button, expander and status.
2. A dark slate theme with Tailwind blue `#3B82F6`, the default "AI startup" look.
3. Stacked `st.info`/`st.warning`/`st.success` boxes with bold emoji prefixes, 2–4 per page.
4. No action hierarchy: 3–4 equal-weight full-width buttons per asset.
5. Every category shown twice: a dataframe, then expanders repeating the same fields as `**Label:** value`.
6. Inflated copy ("Subscription Actions & Cancellation Center", "Legal Notice / Execution Dispatcher"),
   plus a filler caption under every header.
7. Tab sprawl: 7 owner tabs and 8 executor tabs, each with an emoji and a count.
8. Six copies of a "➕ Add Asset" button floating in `[3,1]` columns.
9. A default sidebar title with an emoji, two stacked radio groups, and no product wordmark.
10. Inconsistent heading levels, `$` instead of CHF, a hardcoded "John Doe", and a redundant
    "Back to Catalogue" button.

## 2. Assumptions

1. Radius is 4px, a compromise between VZ's 0–5px and softer SaaS radii.
2. Icons use Streamlit's built-in Material icons; no new dependency.
3. Demo data is the fictional Zurich resident in `samples/demo_transactions.jsonl`.
4. "Share" in the journey strip can be a basic export (download); real sharing is out of scope.
5. Single user and session-only state, as today. The Gmail privacy wording stays. The recording uses
   the sample data or a test inbox.
6. Recording target is 1920×1080 in desktop Chrome; mobile polish is not a priority.
7. The owner/executor role switch stays as it is, restyled.
8. Foreign-currency totals use a fixed demo FX table and are labelled "approx.".

## 3. Decision log

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| 1 | Inspired by VZ, own branding | Co-branded mock-up; neutral Swiss fintech; keep dark | Plausible ecosystem fit without imitating VZ's brand |
| 2 | Name: Digital Legacy Vault | Digital Estate Manager; Estate Manager | Owner's choice |
| 3 | Two phases: visual overhaul, then pitch flow | One pass; visual only | Reviewable diffs; Phase 1 is useful on its own |
| 4 | Demo uses both sample data and live Gmail; the pitch is a recorded video | Live Gmail only; scripted animation | Honest (real computation) with no on-stage risk |
| 5 | Sample persona in `samples/` with a generator; seed 11 (2 false positives) | Clean seed 303 | Gives something real to reject in "Needs review" |
| 6 | New Overview page first in navigation | Merge into Find Assets; keep Catalogue first | Tells the story up front |
| 7 | Approach A: theme-first with thin CSS and helpers, plus custom HTML for 3 read-only hero components | B: CSS-heavy HTML reskin; C: component library | Robust across Streamlit upgrades, maintainable; buttons stay native |
| 8 | Confidence labels: Confirmed = user-checked, Likely = high, Needs review = medium/low or possibly cancelled | Show raw confidence percentages | Honest about uncertainty; user confirmation stays the source of truth |
| 9 | Additive `confidence`, `confidence_reasons`, `evidence` fields on `Asset` | Parse `notes` text | Structured data for the evidence panel; `notes` kept for compatibility |
| 10 | CHF display with a fixed FX table for totals | Keep `$`; per-currency totals | Swiss audience; fixes a mixed-currency sum bug in `calculate_metrics` |

## 4. Design

### 4.1 Tokens and theme

| Role | Value | Use |
|---|---|---|
| Ink | `#191919` | Body text, headings |
| Muted | `#666666` | Captions, labels, secondary text |
| Rule | `#E5E5E5` | Borders, dividers, table grid |
| Surface | `#FFFFFF` / `#F5F5F7` | Page / sidebar, table header, hero panels |
| Navy | `#004388` | Primary buttons, links, active states |
| Orange | `#D6521C` | At most one use per screen: active-nav marker, Overview CTA |

- **Status colours** (text plus a thin left rule, never filled boxes): green `#4E924A` for
  Confirmed/Active, amber `#B7791F` for Likely/Pending, red `#B42318` for Needs review/errors.
- **Type:** Inter only (400/600/700), base size 15px.
  - Page title 28/700, section 18/600, sub-section 15/600.
  - Tabular figures for numbers.
  - Section labels 12px uppercase, tracking 0.06em, Muted.
- **Spacing:** 8px grid (8/16/24/40). 40px between sections. Content capped at about 1200px and
  left-aligned.
- **Shape:** 4px base and button radius, no shadows, 1px Rule borders only where a boundary means
  something.
- **Buttons:**
  - Primary: filled navy, one per context.
  - Secondary: white with a Rule border.
  - Tertiary: navy text link.
- **Hero components (custom HTML, read-only):** the Overview KPI strip, the evidence panel, and the
  Inventory → Instructions → Share journey strip.

### 4.2 Information architecture and navigation

- **Sidebar:**
  - Wordmark "Digital Legacy Vault" with the caption "Digital estate overview".
  - Navigation: **Overview**, **Assets** (was Catalogue), **Discover** (was Find Assets). The active
    item has a 2px orange marker.
  - At the bottom, a segmented "VIEW AS" control (*Owner | Executor*) with a one-line caption.
- **Page frame:** title (28/700), at most one Muted line under it, and the page's single primary action
  right-aligned in the title row. No back button.
- **Assets (owner):**
  - One segmented filter (*All · Subscriptions · Finance · Cloud · Social · Other*) replaces the tabs.
    "Show removed (n)" is a quiet toggle.
  - One compact row per asset: service, identifier, category, monthly cost, status label, and Details.
  - Details holds a definition list plus actions: a contextual primary action; "Open provider site" and
    "Remove" as secondary or tertiary actions.
  - The editable master table stays, behind a "Table view" toggle.
- **Assets (executor):** the same filter plus *Flagged* and *Removed by owner*. The audit policy is one
  line with a "Why?" popover.

### 4.3 Pitch flow (Phase 2)

- **Overview before a scan:**
  - Title "Know what you leave behind." with one explanatory sentence.
  - Primary CTA "Scan my digital footprint" (sample data); secondary "Connect Gmail".
  - The journey strip with Step 1 current.
- **Discover:**
  - Bordered source panels: *Demo dataset*, *Gmail*, and a quiet "Upload a transaction file".
  - The scan shows the finder's real progress messages as a vertical step list.
- **Overview after a scan:**
  - KPI strip with four figures: assets found · subscriptions · CHF/month recurring (approx.) · needs
    review.
  - A grouped category list, and the journey strip with Step 2 current.
- **Confidence:** each detected item gets *Confirm* (primary) and *Not mine* (tertiary; moves it to
  Removed).
- **Evidence panel:** "Why we think so".
  - Pattern (e.g. "Monthly · CHF 20.90"), sources, date range, last charge, and the finder's reasons.
  - A "View evidence" expander listing the matching transactions.

### 4.4 Copy, currency, states, dialogs

- **Copy:**
  - No emojis. Material icons at 16px only where they carry meaning.
  - Sentence case and verb-first buttons.
  - One short line per explanation.
  - "Legal Notice / Execution Dispatcher" becomes "Notification letter".
  - The deceased's name is a field in the executor view (replaces "John Doe").
- **Currency:** `CHF 1'234.50`. Default assets use CHF. Rows keep their original currency; totals are
  converted with a fixed FX table and marked "approx.".
- **Empty states:** one Muted line plus the relevant action.
- **Loading:** the step list for scans; spinners with specific verbs elsewhere.
- **Errors:** an inline message saying what happened and what to do, with raw exception text under
  "Technical details". Theme-muted alert colours.
- **Success:** `st.toast` for small actions; a persistent message only for scan results.
- **Dialogs:**
  - Title only, then a facts definition list, then content.
  - Footer with secondary on the left and primary on the right.
  - Cross-dialog switches become tertiary links.
  - The Remove dialog keeps a single amber billing warning.

### 4.5 Code structure, testing, risks

- **Code structure:**
  - `.streamlit/config.toml` holds all tokens.
  - A new `src/digital_estate_manager/ui/` package (presentation only):
    - `styles.py` for the CSS
    - `components.py` for the helpers and hero renderers
    - `format.py` for `chf()` and the FX table
  - `app.py` keeps its session keys, dialogs and flows. The seven tab blocks collapse into one
    filtered renderer.
  - Backend changes are additive: `Asset` confidence and evidence fields, filled by the adapter;
    currency-aware metrics; CHF demo assets.
- **Phase 1 PR:** theme, CSS, `ui/`, the navigation rename, the Assets list, copy, emojis, states,
  dialogs, CHF.
- **Phase 2 PR:** Overview, Discover panels and the step-list scan, confidence labels, the evidence
  panel, the journey strip.
- **Testing:**
  - Unit tests for `chf()`/FX, the adapter's new fields and mixed-currency metrics.
  - Streamlit `AppTest` smoke tests per page and role, including a regex check that no emoji is rendered.
  - A 1920×1080 screenshot audit after each phase, followed by a fix pass.
- **Risks and mitigations:**
  - `data-testid` CSS fragility: keep CSS minimal, prefer theme keys, pin `streamlit>=1.57`.
  - Hero HTML can't hold buttons: native actions sit directly below each component.
  - Sample dates drift: regenerate before recording.
  - Finder false positives on real data: shown as "Needs review". Separately, the finder groups card
    charges by amount and timing only, not by merchant; grouping by merchant would be the fix.

## 5. Visual reference (VZ, extracted from their stylesheets)

- Font: `"VZInter","Inter",sans-serif`, weights 400/600/700.
- Colours: `#191919`, `#666`, `#e5e5e5`, `#f5f5f7`, `#004388`, `#005ba6`, `#d6521c`.
- Radius mostly 0, or 3–5px. No gradients, and almost no shadows.
- Heading h1 is 30px/1.19 in the app context and 42px on marketing pages.
