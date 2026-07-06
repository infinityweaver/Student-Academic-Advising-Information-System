# SAAIS — Student Academic Advising Information System

A **local, file-based advising workspace** for university academic advisers, with a
small web system on top. Built for BSCS advising at Visayas State University (VSU,
Faculty of Computing), but reusable by any adviser who tracks advisees as one
Markdown file per student.

> **Privacy by design:** all student records (grades, contact info, rosters) are
> **gitignored** and never leave this machine. This public repo contains only the
> system, the curriculum references, and empty folder scaffolding — clone it and add
> your own advisees.

## Table of contents

- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Installation](#installation)
- [How to use the system](#how-to-use-the-system)
- [Each student file contains](#each-student-file-contains)
- [Grading rules (VSU)](#grading-rules-vsu)
- [Reusing this for your own advisees](#reusing-this-for-your-own-advisees)
- [What is and isn't committed](#what-is-and-isnt-committed)
- [Changelog](#changelog)

## How it works

**Local JSON records are the database** (since v2). Each advisee has a
`record.json` in their own folder holding the profile, grade entries, advising
notes and attachment metadata; registrar grade scrapes are kept in `raw/` as
audit copies and merge into the record on import. The schemas are documented in
[docs/SAAIS-V2-SCHEMAS.md](docs/SAAIS-V2-SCHEMAS.md). Coming from v1
(MD-as-database)? Run the one-time migration: `python -m saais.migrate`.

Every write is **reversible**: the previous version of any mutated file is copied to
`.backups/<timestamp>/` first, and writes are rejected with a *"file changed, reload"*
prompt if the file was hand-edited while the page was open.

**Markdown is now an export format.** The per-student advising MD files are
generated on demand from the records (Roster → select students → *Export MD*,
as a ZIP download or into a folder of your choice) — they are never parsed
back. Derived numbers (units earned, GWA, year level, flags) are always
recomputed, never stored as truth; year level is autocomputed from units
earned with thresholds configurable in `saais.toml` (`[year_level]`).

## Repository layout

```
academic advising/
├── README.md                  ← this file (public)
├── ROSTER.md                  ← generated roster table (gitignored — PII)
├── SAAIS.bat                  ← double-click launcher (Windows)
├── requirements.txt
├── saais/                     ← the web system
│   ├── __main__.py            ← `python -m saais` entry point
│   ├── app.py                 ← Flask routes
│   ├── service.py             ← write-back operations (backup → write record.json)
│   ├── migrate.py             ← one-time v1 (MD) → v2 (JSON records) migration
│   ├── config.py / saais.toml ← rules, term & year-level configuration
│   ├── repo/                  ← file I/O: records (JSON), curriculum (xlsx),
│   │                             scrapes (JSON), timestamped backups
│   ├── domain/                ← rules.py (grades/GWA/flags), advising.py (prereqs)
│   ├── index/                 ← in-memory index, rebuilt from file mtimes
│   ├── render/                ← student MD export + ROSTER.md generators
│   └── templates/, static/    ← Jinja pages, one CSS file, vendored htmx
├── students/
│   ├── active/                ← one folder per advisee (gitignored): record.json
│   │                             + legacy checklist .xlsx + attachments
│   ├── graduated/<year>/      ← archived advisees (gitignored)
│   └── inactive/              ← shifters / AWOL / LOA (gitignored)
├── raw/                       ← registrar grade scrapes, <student-no>.json (gitignored)
├── data/
│   └── curricula/             ← curriculum records, <id>.json (no PII — committed)
├── reference/
│   ├── curriculum/            ← BSCS checklists & prospectus (2018–2024, 2025–present)
│   ├── calendars/             ← current academic calendars
│   └── rosters/               ← official advisee lists, recent semesters (gitignored)
├── archive/                   ← obsolete records kept for reference: expired calendars,
│                                 old rosters, superseded monitoring sheets (gitignored)
└── docs/                      ← SAAIS plan, implementation notes, v2 data schemas
```

## Installation

Requirements: **Python 3.10+** and **git**. Works on Windows, macOS, and Linux
(the `.bat` launcher is Windows-only; use the command line elsewhere).

```bash
# 1. Clone the repository
git clone https://github.com/infinityweaver/Student-Academic-Advising-Information-System.git
cd Student-Academic-Advising-Information-System

# 2. Install dependencies (Flask + openpyxl)
pip install -r requirements.txt

# 3. Start the system
python -m saais
```

The app opens at `http://127.0.0.1:8000/`. On Windows you can also double-click
**`SAAIS.bat`**.

> ⚠️ SAAIS binds to localhost only and has no authentication because it is a
> single-user local tool. **Do not expose it to a network**, and keep the folder out
> of cloud-sync services unless encrypted: the data is PII.

A fresh clone starts **empty** — the student folders exist but contain no records.
See [Reusing this for your own advisees](#reusing-this-for-your-own-advisees) to load
your own.

## How to use the system

### Navigation

The top nav is grouped into four areas so every feature stays a click or two away:

- **🏠 Dashboard** — the home page (status counts, INC countdown, stop-outs, statistics).
- **👥 Students ▾** — a dropdown with Roster, Flags board, ＋ Add advisee, New advisee
  (from scrape), and Import scrape.
- **📚 Curricula** — first-class curriculum records.
- **📊 Reports** — the flexible report generator.

The current page is highlighted in the nav; on narrow screens the nav collapses
behind a ☰ button. The student page additionally has a sticky quick-jump bar
(Flags · Checklist · Grades · Notes · Attachments) since it is the longest page.

### The pages

| Page | What it's for |
|---|---|
| **Dashboard** (Home) | Status counts, ⏳ INC deadline countdown (1-year lapse rule), 🚪 stop-out list, per-program statistics, recent graduates |
| **Roster** (Students ▾) | All advisees — sortable/filterable by status, curriculum, year level, GWA, flags |
| **Flags board** (Students ▾) | Every 🔴/🟡 item across advisees, grouped: INCs, retakes, delinquency, stop-outs |
| **Curricula** | First-class curriculum records — add, import from xlsx, edit effective years, delete |
| **Reports** | Filter by status/curriculum/year level/GWA/flags/date range; on-screen table or CSV export |
| **Student page** | Profile, flags, curriculum checklist, grade history by term, advising notes CRUD, attachments, AI chat |
| **Import scrape** (Students ▾) | Drop/paste a fresh registrar JSON for an existing advisee |
| **New advisee** (Students ▾) | Scaffold the folder + `record.json` for a new advisee, by hand or from their grade JSON |

### During an advising session

1. Open the student's page — review **Flags** (retakes, INC deadlines, delinquency)
   and the **curriculum checklist**.
2. Click **📝 Enrollment advising** — SAAIS computes *Can Enroll* for every remaining
   course from passed prerequisites. Tick the courses to take (the unit total warns
   above the regular load), then **Generate advising slip** and print it for signing.
   The advised courses are recorded as a dated advising note automatically.
3. Add any extra **advising notes** (commitments, concerns) from the notes form —
   they are stored in the student's record, newest on top.

### At the end of a term (grades released)

1. **Import scrape** for each advisee with a fresh registrar JSON — grade entries
   merge into the record; checklist, flags and `ROSTER.md` recompute automatically.
2. No scrape available? Use **🖊 Encode grades** on the student page to type final
   grades and INC completions for the in-progress courses.
3. When moving to a new term, update `[term]` in
   [saais/saais.toml](saais/saais.toml) and restart — this drives the
   *currently enrolled* section, stop-out detection, and the grade-encoding form.

### Lifecycle

- **New advisee** → intake page (paste their grade JSON, name the folder).
- **Graduation** → *🎓 Mark graduated* on the student page moves the folder to
  `students/graduated/<year>/`.
- **Shifted out / AWOL** → move the folder to `students/inactive/` by hand.

### Editing files by hand

Still supported — `record.json` is plain, indented JSON. SAAIS picks up hand
edits on the next page load, refuses stale browser writes over them, and backs
up the previous version before every write of its own.

## Each student record (and its MD export) contains

1. **Header** — student no., curriculum, contact, units earned, year level (by unit thresholds), GWA, status.
2. **Flags** — retakes needed, outstanding INCs, delinquency-rule hits, enrollment gaps.
3. **Curriculum checklist** — every required course with status (✅ passed / ⏳ INC / ❌ failed-or-dropped / ✳️ in progress / ⬜ not taken), latest grade, prior attempts.
4. **Grade history by term** — with per-term GWA.
5. **Advising notes** — hand-maintained log, newest entries at the top.

## Grading rules (VSU)

Configurable in [saais/saais.toml](saais/saais.toml):

- 1.00 (excellent) … 3.00 (lowest pass); **5.00 = fail**; `S` = satisfactory (pass, no GWA weight); `DR` = dropped; `NA` = no attendance.
- `INC` must be completed within **1 year**, otherwise it lapses to 5.00.
- Delinquency **flag**: failed ≥ 25% of enrolled units in a term. This is an advising
  heads-up only — there is currently **no active student-retention policy** attached
  to it.
- Year level by units earned — thresholds come from each curriculum workbook, or
  set your own in `saais.toml` (`[year_level] thresholds`).
- Status: 🟢 on track (no flags) · 🟡 watch (INCs / a retake pending) · 🔴 needs attention (recent delinquency, ≥3 retakes, or no current enrollment).

## Reusing this for your own advisees

Because all student data is gitignored, a fresh clone is an **empty but fully working
system**:

1. [Install](#installation) as above.
2. If your program differs, replace the curriculum workbooks in
   [reference/curriculum/](reference/curriculum/) (see the expected sheet layout in
   [saais/repo/curriculum.py](saais/repo/curriculum.py)) and adjust
   [saais/saais.toml](saais/saais.toml) (current term, grading thresholds).
3. Start SAAIS and use **New advisee** to add each student — paste their grade JSON
   (schema below) and a folder name. Everything else is generated.

Scrape JSON schema (one file per student, `raw/<student-no>.json`):

```json
{
  "student": {"student_number": "25-1-00001", "name": "SURNAME, FIRSTNAME MI", "program": "BSCS"},
  "grades": [
    {"academic_year": "2025-2026", "semester": "First Semester",
     "course_code": "CSIT 101", "course_title": "INTRODUCTION TO COMPUTING",
     "units": 3.0, "midterm": "2.00", "grade": "1.75", "completion": null}
  ]
}
```

`grade` may be a number, `"INC"`, `"DR"`, `"S"`, `"NA"`, or `null` (still in progress);
`completion` holds the grade that resolved an INC.

## What is and isn't committed

| Public (committed) | Private (gitignored, `.gitkeep` placeholders keep the folders) |
|---|---|
| The SAAIS system (`saais/`, `tools/`, `docs/`) | `students/**` — advising MDs, checklist workbooks, contact info |
| Curriculum checklists, prospectus, calendars | `raw/*.json` — registrar grade scrapes |
| This README | `ROSTER.md`, `tools/roster.json` — generated rosters |
| | `reference/rosters/` — official advisee lists |
| | `archive/` — obsolete records kept for reference |
| | `.backups/` — pre-write file snapshots |

Git is used for versioning the *system*; student-file history is kept in `.backups/`
instead, precisely so PII can never end up in a public git history. See
[docs/SAAIS-IMPLEMENTATION.md](docs/SAAIS-IMPLEMENTATION.md) for this and other
design decisions, and [docs/SAAIS-PLAN.md](docs/SAAIS-PLAN.md) for the original plan.

## Changelog

### 2.0.0 — 2026-07-06

- **v2 rewrite** (Issue [#1](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/issues/1),
  PRs [#2](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/pull/2),
  [#4](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/pull/4),
  [#5](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/pull/5),
  [#6](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/pull/6)):
  JSON records (`students/<status>/<Folder>/record.json`)
  replace per-student Markdown as the source of truth, with a one-time migration from
  the legacy `.md`/`.xlsx`/`raw/*.json` files; Markdown becomes an export-only format
  (Roster → select students → *Export MD*). Curricula are now first-class editable
  records (`data/curricula/<id>.json`) with an xlsx import path. Full Students CRUD
  (add/edit/delete, checklist overrides + remarks, grade-entry deletion, file
  attachments). Dashboard rebuilt with per-program statistics and a recent-graduates
  list, alongside the existing INC countdown and stop-out list. New flexible Reports
  page (filter by status/curriculum/year level/GWA/flags/date range, CSV export).
  Advising notes are full CRUD (was append-only), plus an optional local AI advising
  chat scoped to a single student's own records (disabled by default; enable `[ai]`
  in `saais.toml`).
- **UI/UX refactor** (Issue [#1](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/issues/1),
  PR [#7](https://github.com/infinityweaver/Student-Academic-Advising-Information-System/pull/7))
  for intuitive, efficient access to every v2 feature: the top nav
  is now grouped into *Dashboard · Students (Roster, Flags board, Add advisee, New
  advisee from scrape, Import scrape) · Curricula · Reports*, with active-page
  highlighting and a collapsible mobile menu; the Dashboard gained a quick-actions bar
  to the most common tasks; the (long) student page gained a sticky quick-jump sub-nav
  (Flags · Checklist · Grades · Notes · Attachments) and a back-to-roster link.
  Addressed Copilot review feedback on PR #7: two nav template expressions were
  missing an explicit `else` branch (risked a `TemplateSyntaxError`), and an
  implementation-notes sentence understated the docs-only files it touched.

### 1.0.0 — 2026-07-04

- Initial release, implementing [docs/SAAIS-PLAN.md](docs/SAAIS-PLAN.md) phases 1–3:
  dashboard with INC deadline tracker, roster, flags board, student pages; advising
  notes, scrape import, manual grade encoding, profile edits; prerequisite-based
  enrollment advising with printable slips; new-advisee intake and graduation
  lifecycle. Timestamped backups before every write; PII kept out of the public repo
  by design.
