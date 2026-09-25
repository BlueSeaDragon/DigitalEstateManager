# Guided onboarding for the pitch demo

Status: design approved, 2026-09-25. Branch: `feat/vz-redesign`. Builds on `docs/design/vz-redesign.md`.

## 1. Understanding summary

- **What:** a guided first-run flow in the existing Streamlit app: Landing → Onboarding → Magic moment
  → Dashboard. It runs only when a config flag is on; with the flag off the app is unchanged.
- **Why:** a polished one-minute screen recording for the VZ pitch. Slow parts are sped up in editing.
- **Who:** the VZ judges watching the recording; real first-time users benefit as a side effect.
- **Everything is real:** the Gmail OAuth popup, the statement upload and the finder run. No staged
  connectors or scripted animations of fake results.
- **Non-goals:** extra (fake) provider tiles, rework of Assets/Evidence/Policies/Executor, new persistence
  or auth, hype copy.

## 2. Assumptions

1. With onboarding on, the vault starts empty, so the magic moment only counts what the scan found.
2. The recording uses a Gmail test inbox and `samples/demo_transactions.jsonl` as the "bank statement".
3. Google sign-in opens in a new tab and returns in a new Streamlit session, so Gmail comes first and the
   statement is uploaded in the returning tab.
4. The count-up is pure CSS (a registered `@property` integer); the auto-advance is a Streamlit fragment
   with `run_every`. No JavaScript, no new dependency.
5. Recorded at 1920×1080 in desktop Chrome. Reloading the page starts the onboarding again (retakes).

## 3. Decision log

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| 1 | Guided first-run flow inside the app, behind a flag | Replace navigation; separate HTML prototype | Reuses the real scan; one codebase |
| 2 | Fully real sources and analysis | Staged connectors; scripted analysis | It is a recording: slow parts are sped up |
| 3 | Magic moment: summary with count-up and provider grid, then auto-advance (~7 s) with a "Continue" fallback | Progressive list; straight to dashboard | One memorable hero frame without an extra click |
| 4 | Dashboard in the video: spend and categories | Review/evidence, legacy policies, executor | Keeps the minute focused; the rest stays reachable |
| 5 | Landing copy: "Know what you leave behind." + "Find your digital accounts and subscriptions so your heirs don't have to." | Two other lines | Owner's choice; matches the existing hero |
| 6 | One screen with two source cards (Gmail, bank statement), one "Analyse" button | Two-step stepper; upload only | Fewest clicks; both sources feed one run; shows the Google popup |
| 7 | Enabled by `DLV_ONBOARDING=1` (env / `.env`) | `?onboarding=1`; sidebar toggle | Server-side, so it survives the OAuth redirect |
| 8 | Gmail connects with one link button (no dialog) | Reuse the "Connect Gmail" dialog | Two fewer clicks on camera |
| 9 | Magic-moment grid: provider + monthly cost, largest first | Names grouped by category | The finder files nearly everything under Subscriptions; one long column read poorly |
| 10 | Onboarding screens centred; the dashboard stays left-aligned with the sidebar | Left-aligned everywhere | Matches VZ's centred marketing pages at 1920px |

## 4. Design

### 4.1 Visual language (VZ website, marketing context)

Extracted from vermoegenszentrum.ch `critical.css`, added to the tokens of the main redesign:

- **Hero heading** 42px / 1.19 / 700 (the app's page titles stay 28px).
- **Lead text** 21px / 1.46, Muted.
- **Orange button** (`.button-orange`): `#C95321` with a faint white top gradient, bold 14–15px, 4px radius.
  It is the single orange element on the landing.
- **CTA link** (`.cta`): bold ink text with a 2px orange underline. Used for "Continue" and quiet actions.
- No photography, gradients or shadows beyond these.

The anchor that ties the four screens together is the **three-step rule** (Connect · Analyse · Review):
a thin rule per step that turns orange for the current step and navy when done. The landing previews it,
onboarding uses it as the stepper, and on the magic moment an orange line fills across it while the
screen counts down to the dashboard.

### 4.2 Screens

All onboarding screens hide the sidebar and show a slim top bar: wordmark left, a 1px rule below.

1. **Landing:** eyebrow "Digital estate planning"; the 42px headline; the lead sentence; the orange
   "Get started" button; one Muted line "Takes about a minute. Read-only access, nothing is stored.";
   the three-step rule as a preview, nothing current.
2. **Connect:** step rule with Connect current; title "Connect your sources"; two equal cards.
   - *Gmail* (step 1): "Read-only access to billing emails." One "Connect Gmail" link button to Google.
     Connected: green "Connected" label and a "Disconnect" link.
   - *Bank statement* (step 2): "A transaction export from your bank (JSON or JSONL). Read in memory only."
     A file uploader.
   - Below: the navy primary "Analyse" (disabled until a source is ready) and a Muted line naming the
     ready sources.
3. **Analyse:** step rule with Analyse current; title "Analysing your footprint"; the finder's real
   progress as the existing step list. On an error: inline message and "Back to sources". Without an LLM:
   the existing "rules only" offer.
4. **Magic moment:** step rule with Review current. Eyebrow "Your digital footprint"; 42px headline
   "We found **N** accounts and subscriptions." with N counting up; lead "Together they cost about
   **CHF X** a month. **K** need your review." Below, a four-column grid of the providers with their
   monthly cost, largest first, fading in one after another. (Grouping by category was dropped: the
   finder files nearly everything under Subscriptions.) An orange line fills over ~7 s,
   then the app opens the dashboard; "Open my dashboard" (CTA link) skips the wait.
5. **Dashboard:** the existing Overview after a scan, plus a spend bar per category (share of the
   monthly total) so the "spend and categories" beat reads at a glance.

### 4.3 State and flow

- `st.session_state.onboarding` ∈ `landing`, `connect`, `analyse`, `reveal`, `done`; starts at `landing`
  when the flag is on, otherwise `done`.
- The OAuth redirect lands on `connect` (not Discover) while onboarding is running.
- `analyse` runs `run_scan()` with the uploaded statement (plus Gmail when connected); on success it moves
  to `reveal`, on failure it stays with a way back.
- `reveal` → `done` sets the page to Overview.

### 4.4 Code structure and testing

- `config.onboarding_enabled()` reads `DLV_ONBOARDING`.
- `ui/components.py`: `topbar`, `step_rule`, `reveal`; `ui/styles.py`: onboarding CSS, injected only
  during onboarding.
- `app.py`: one onboarding section before the pages, ending in `st.stop()`; `run_scan()` gains an
  `upload` argument and an `on_success` callback.
- Tests: the flag parser; AppTest smoke tests of landing → connect, the magic moment and the dashboard
  with the flag on, including the no-emoji check. With the flag off, the existing tests still pass.

### 4.5 Risks

- **Sidebar CSS selectors** can change with Streamlit upgrades; the hiding is limited to onboarding.
- **New tab after OAuth:** the old tab is left behind; cut it in editing.
- **`@property` count-up** needs a Chromium browser; elsewhere the final numbers show without animation.

## 5. Executor scene (added 2026-09-25)

The jury works on the post-death side, so the one-minute video is now: owner scan (about 20 s) →
"Three years later" title card → executor. The owner onboarding is unchanged apart from a yearly-reminder
line on the magic moment and a matching toggle on the owner overview (a stored preference; nothing sends
reminders yet).

- **Worklist** (executor start page): title "Estate of Anna Muster" (or "Estate overview"), then the
  deceased's name and the list, with no KPI strip. Sorted by monthly cost,
  largest first; rows keep their place when marked done, so nothing jumps on camera.
- **No automatic cancellation.** Providers need a death certificate and proof of authority through their own
  process; DEM prepares the policy, documents and letter.

## 6. Frame and page structure (added 2026-09-25, later)

- **No Overview page.** The asset list is the start page for both roles; its header carries the key
  figures (headline number, KPI strip) and the one primary action. The reveal's CTA is "Open my inventory".
- **View switch in a band above every page**, not in the sidebar: switching role changes the whole app.
- **Executor looks different on purpose:** navy sidebar and navy role band, navy eyebrows, and its own
  navigation labels (Worklist / Find accounts instead of Inventory / Find accounts), so the cut from owner
  to executor reads at a glance in the video.
- **Page headers:** small eyebrow with a rule (orange for owner, navy for executor), a plain 34px title
  ("Accounts and subscriptions", "Estate overview", "Find accounts"), no line underneath.
  No taglines: titles name the page, and not every account is closed.
