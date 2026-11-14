# SiPh Lab research workspace: independent usability audit (2026-10-15)

An independent reviewer audited the web workspace at `16a1560` (branch `causal-warrant-gate-v1`)
from the point of view of a **new graduate researcher** who has only the browser. It was read-only
on the code. It ran its own instance on a disposable database and inspected it in a browser,
desktop and 375 px mobile, in English and zh-TW. It did not touch the deployment.
Below is its report, condensed as delivered. The last column, and the list in §3, say what this
branch (`ux-research-workspace-clarity`) changed.

Evidence types: **VB** verified in the browser (screenshot in `screenshots/` where kept);
**VB-text** verified from page text or DOM; **CODE** code reading only.

## 1. Environment the reviewer used

| Item | Value |
|---|---|
| Code | detached worktree at `16a1560`, `git status` clean before and after |
| Database | disposable `lab_brain_ux_audit` (63 migrations), dropped at the end |
| Server | `lab-brain web` on 127.0.0.1:8877 as `act:newgrad`, once as `act:colleague` |
| AI | none configured: every run used the local rules reasoner (`rules:sp.rs_anomaly_mechanisms@1.0.0`); no paid call |
| Browser | built-in browser; 44 screenshots (18 kept here) |
| Data | six files imported through the page (READY, DUPLICATE, BLOCKED with a fake key block, FAILED with a fake PDF); device files generated from the benchmark fixture as the e2e helper does |
| Episodes | (a) no verification input, a Lab-confidential question: COMPLETED, NOT_REACHED; (b) report + literature + PS-504: SUSPENDED, PROVISIONAL, then continued; (c) report + PS-501: COMPLETED, CONFIRMED; one CLI episode in another project |
| Caveat | file selection was injected into the page's own inputs (the browser tool cannot drive a native file dialog); every submission went through the page's own buttons |

## 2. Findings

| ID | Sev | Screen / route | What a new researcher experiences | Evidence | This branch |
|---|---|---|---|---|---|
| F01 | HIGH | `/runs/new` → episode | "Verification input" is optional; without it the run shows green "Finished", NOT_REACHED, "No further check is planned", and cannot be continued, with no reason. | VB s15, s17 | **Fixed**: the page says no check could be planned without a verification input and that new research is needed |
| F02 | HIGH | episode (CONFIRMED) | The confirmed mechanism is also listed under "Still competing". | VB s31–s33 | **Fixed**: Supported / Still open / Ruled out |
| F03 | HIGH | episode run from the CLI | "No hypothesis was admitted" and "No further check is planned" although 5 hypotheses and a CONFIRMED outcome exist (no web report stored). | VB c02 | **Fixed**: says no report was recorded in the workspace; a test that asserted the false sentence now asserts its absence |
| F04 | HIGH | whole UI | Pending causal-warrant reviews are invisible (CLI only); warrants appear as raw ids in layer 3. | CODE | Proposal R1 |
| F05 | HIGH | episode L1/L2 | Readings of the uploaded design file are labelled "observed" / "Observed facts"; one such reading confirmed a root cause. | VB s21, s31 | **Wording fixed** ("result", "Results of executed checks"); the scientific question is G1 |
| F06 | HIGH | episode L2 | A RETRACTED paper's passage shows as "(external literature, PEER_REVIEWED)"; RETRACTED appears only in layer 3. | VB s23 | **Fixed**: the source's status is shown beside the excerpt |
| F07 | MED | episode | "Model interpretations" although no model ran; "The author's own explanation" is ambiguous; raw role ids. | VB s20 | **Wording fixed** for the two labels |
| F08 | MED | next action | "A person can act now: fourpoint probe", with nowhere to record the result. | VB s22 | Proposal R3 (governance) |
| F09 | MED | Continue | Offered while the blocker is unchanged; creates an empty run 2. | VB s25 | Proposal R8 |
| F10 | MED | `/data` vs `/runs/new` | A file with 0 passages reads "Ready for research, pick it in New research" and is silently not offered there. | VB s06, s11 | **Fixed**: says it holds no citable passage and is not offered |
| F11 | MED | `/runs/review` | "Go back and change" clears the whole form. | VB s36 | Not changed (form semantics; proposal) |
| F12 | MED | `/runs/new` | The question's classification offers levels above the researcher's clearance; a Lab-confidential question was accepted. | VB s14, s15 | **Fixed**: disabled in the form and refused on both POSTs (test) |
| F13 | MED | `/data` | Materials cannot be viewed, downloaded, searched, archived or reclassified. | VB s06–s09 | Proposal R5 |
| F14 | MED | Home | No project page: members, clearance, privacy mode, review policy hidden. | VB s02 | Proposal R6 |
| F15 | MED | `/episodes` | A confirmed and an untested episode both read only "Finished". | VB s26 | **Fixed**: a Result column, the status only (checked in a browser: the stored value carries the cause's id, which the first version showed) |
| F16 | MED | episode, egress | Jargon in layer 1 ("TST-001, risk R-1", "governed transition (ALLOW)", "§14.2"); a CLI command offered as the web next step. | VB s21, s22 | Partly (F07 labels); proposal R12 |
| F17 | MED | zh-TW episode | Stored English mixed into Chinese layer 1; state badges stay English enums. | VB s34 | Proposal R10 |
| F18 | MED | mobile 375 px | Tables crush to one character per line; the "Use it as" select shows only an arrow. | VB m02, m05 | Proposal R11 |
| F19 | LOW | `/data` | "3 file(s) imported" when one failed and one was quarantined. | VB s09 | **Fixed**: "received" |
| F20 | LOW | file inputs | No `accept` filter. | DOM | Not changed |
| F21 | LOW | status legend | Literal "…" placeholders. | VB s07 | Not changed |
| F22 | LOW | header | "signed in as act:newgrad" implies a login that does not exist. | VB s01 | **Fixed**: "Working as" |
| F23–F27 | LOW | settings, confirm page, L3 time zone, foreign `?project=`, egress back link | small wording and navigation issues | VB | Not changed |
| F28 | LOW | Home | A CLI-ingested file shows its full `file:///C:/Users/…` path. | VB c03 (not kept: it shows the local path the finding is about) | **Fixed**: base name only |
| F29 | LOW | onboarding | README's `PS-504.device.json` is not in the repository; no template in the UI. | CODE | Proposal R4 |
| F30–F33 | LOW | literature confirmation, nav for non-admins, step-4 files imported at confirm, step bar | small consistency issues | VB/CODE | Not changed |

What works well (reviewer): every import status explains itself and gives a next step; refusals
for a colleague's and a nonexistent episode are identical (nothing leaks); a missing simulator is
explained as a known limit; the confirm page lists every input before anything runs; empty states
say what to do first; no horizontal page scroll on mobile.

## 3. Changes on this branch

Each is display or wording, except F12, which tightens a server rule to match the existing one
for imports. F03, F12 and F15 were also checked in a browser after the change (on a
disposable database, with an episode the command line confirmed): `screenshots/after_*.jpg`. None changes stored data, transition policy, a stored report or a warrant.
- F01, F02, F03, F05, F06, F07: `interfaces/web/pages.py`, `i18n.py`; tests in
  `tests/unit/test_episode_view_page.py`.
- F10, F15, F19, F22: `workspace_pages.py`, `i18n.py`.
- F12: `app.py` (`_review`, `_create_run`), `workspace_pages.py`; test
  `test_a_question_is_classified_only_at_a_level_the_researcher_holds`.
- F28: `research/data.py`.
- From the data-organization audit:
  - F-07, an exported report now carries the flags and reliance recorded since its run. The
    stored report is unchanged, and so is the export when there is nothing to add (`render.py`,
    `app.py`; tests).
  - S5/S6, research bytes kept out of the repository (`.gitignore`, README examples under
    `var\artifacts`, a test that wrote a store into the repository root).

## 4. Larger proposals (reviewer's priority order; not implemented)

- **R1** Decisions inbox: open review items with the question in plain words, the observation,
  the rivals and what each answer would change. Signing can stay in the CLI at first; the page
  shows the exact command.
- **R2** Evidence ladder per belief change: source type, result, prediction, warrant in words,
  transition.
- **R3** Recording the result of a planned person-action (a governance decision).
- **R4** Verification-input onboarding: a device-project template and preview; "run again with a
  verification input" on NOT_REACHED episodes.
- **R5** Materials library: item page, passages, which episodes used it, classification history,
  search.
- **R6** Project overview: members, my clearance and scopes, privacy mode, egress, review policy.
- **R7** One status vocabulary: lifecycle separate from outcome.
- **R8** Honest Continue: disabled or explained when nothing changed since the blocking run.
- **R9** CLI/web parity: store CLI reports, or render from rows with a banner.
- **R10** Layer 1 from structured data, translated; the English report only in layer 3.
- **R11** Mobile layout: cards, a compact header, an in-page contents list.
- **R12** Inline glossary: hypothesis, prediction, falsifier, warrant, belief state, provisional.

## 5. Possible correctness or governance issues (reported, not fixed here)

- **G1** A single design-file reading CONFIRMED the root cause of a measured anomaly while other
  mechanisms were untested. The gate's rule allows it (no rival predicts that observable). Whether
  a design-file reading may confirm the root cause of a measured anomaly is the science review's
  question; see the V1.1 audit report §10, item 4.
- **G2** The question's classification above clearance: fixed here (F12).
- **G3** The literature egress policy is built as RESEARCH mode even for PRIVATE projects
  (`research/literature.py:101-109`). Only a local corpus exists today, so nothing leaves the
  machine, but a future network provider would contradict the egress page.
- **G4** Retracted literature is admitted as REPORTED evidence by design (EVI-008). It is now
  shown (F06). Whether a retracted passage may feed the critic or a relation needs confirming.
- **G5** The view's false statement for unrecorded runs: fixed (F03).
- **G6** A wrong classification can only be loosened by the operator; there is no recorded
  escalation path.
- **G7** Every Continue adds an audit-trail run, even when nothing can change (F09).
