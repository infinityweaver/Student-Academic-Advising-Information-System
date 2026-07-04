# SAAIS — Student Academic Advising Information System

A **local, file-based advising workspace** for university academic advisers, with a
small web system on top. Built for BSCS advising at Visayas State University (VSU,
College of Engineering and Technology), but reusable by any adviser who tracks
advisees as one Markdown file per student.

> **Privacy by design:** all student records (grades, contact info, rosters) are
> **gitignored** and never leave this machine. This public repo contains only the
> system, the curriculum references, and empty folder scaffolding — clone it and add
> your own advisees.

## How it works

**The files are the database.** Each advisee has a hand-maintainable Markdown file;
registrar grade scrapes live as JSON; the curriculum checklists are read-only Excel
workbooks. The web system (SAAIS) is a *view and editor* over those files — every
action in the browser writes back to them, so they stay readable and editable by hand
even if the system is never opened again.

```
academic advising/
├── README.md                  ← this file (public)
├── ROSTER.md                  ← generated roster table (gitignored — PII)
├── SAAIS.bat                  ← double-click launcher (Windows)
├── requirements.txt
├── saais/                     ← the web system
│   ├── __main__.py            ← `python -m saais` entry point
│   ├── app.py                 ← Flask routes
│   ├── service.py             ← write-back operations (backup → write → regenerate)
│   ├── config.py / saais.toml ← rules & term configuration
│   ├── repo/                  ← file I/O: MD round-trip parser, curriculum (xlsx),
│   │                             scrapes (JSON), timestamped backups
│   ├── domain/                ← rules.py (grades/GWA/flags), advising.py (prereqs)
│   ├── index/                 ← in-memory index, rebuilt from file mtimes
│   ├── render/                ← student MD + ROSTER.md generators
│   └── templates/, static/    ← Jinja pages, one CSS file, vendored htmx
├── students/
│   ├── active/                ← one folder per advisee (gitignored): advising .md
│   │                             + checklist .xlsx with contact info
│   ├── graduated/<year>/      ← archived advisees (gitignored)
│   └── inactive/              ← shifters / AWOL / LOA (gitignored)
├── raw/                       ← registrar grade scrapes, <student-no>.json (gitignored)
├── reference/
│   ├── curriculum/            ← BSCS checklists & prospectus (2018–2024, 2025–present)
│   ├── calendars/             ← academic calendars
│   ├── policies/              ← CET academic residency policy form
│   ├── rosters/               ← official advisee lists per semester (gitignored)
│   └── misc/                  ← (gitignored)
├── tools/                     ← generate_student_md.py — legacy one-shot generator,
│                                 superseded by SAAIS (re-running it OVERWRITES notes!)
└── docs/                      ← SAAIS plan and implementation notes
```

## Quick start

Requirements: **Python 3.10+**, `pip install -r requirements.txt` (Flask + openpyxl).

```bat
python -m saais
```

or double-click **`SAAIS.bat`**. The app opens at `http://127.0.0.1:8000/` — it binds
to localhost only and has no authentication because it is a single-user local tool.
**Do not expose it to a network**, and keep the folder out of cloud-sync services
unless encrypted: the data is PII.

## What SAAIS does

| Area | Features |
|---|---|
| **Dashboard** | Status counts, ⏳ INC deadline countdown (1-year lapse rule), 🚪 stop-out list |
| **Roster** | Sortable/filterable advisee table (status, curriculum, year level, GWA, flags) |
| **Flags board** | All 🔴/🟡 items across advisees, grouped: INCs, retakes, delinquency, stop-outs |
| **Student page** | Profile, flags, curriculum checklist, grade history by term, advising notes |
| **Advising notes** | Add dated notes from the browser — appended to the student's MD table |
| **Scrape import** | Drop/paste a fresh registrar JSON → grades merged, checklist/flags/header regenerated |
| **Grade encoding** | Enter final grades / INC completions through a form when no scrape is available |
| **Enrollment advising** | *Can Enroll* computed from prerequisites; tick *Will Enroll*; unit-load check; printable advising slip |
| **Lifecycle** | New-advisee intake (scaffolds folder + MD), mark graduated (archives the folder) |

Every write is **reversible**: the previous version of any mutated file is copied to
`.backups/<timestamp>/` first, and writes are rejected with a *"file changed, reload"*
prompt if the file was hand-edited while the page was open.

### Round-trip safety

A student MD file is an ordered list of `##` sections. SAAIS regenerates the
**computed** sections (header table, Flags, Currently enrolled, Curriculum checklist,
Grade history) wholesale from the raw grade data, and preserves the **Advising notes**
section and any sections you add by hand **byte-for-byte**. Derived numbers (units
earned, GWA, year level, flags) are always recomputed, never stored as truth.

## Each student file contains

1. **Header** — student no., curriculum, contact, units earned, year level (by unit thresholds), GWA, status.
2. **Flags** — retakes needed, outstanding INCs, delinquency-rule hits, enrollment gaps.
3. **Curriculum checklist** — every required course with status (✅ passed / ⏳ INC / ❌ failed-or-dropped / ✳️ in progress / ⬜ not taken), latest grade, prior attempts.
4. **Grade history by term** — with per-term GWA.
5. **Advising notes** — hand-maintained log, newest entries at the top.

## Grading rules (VSU)

Configurable in [saais/saais.toml](saais/saais.toml):

- 1.00 (excellent) … 3.00 (lowest pass); **5.00 = fail**; `S` = satisfactory (pass, no GWA weight); `DR` = dropped; `NA` = no attendance.
- `INC` must be completed within **1 year**, otherwise it lapses to 5.00.
- Delinquency flag: failed ≥ 25% of enrolled units in a term.
- Year level by units earned — thresholds come from each curriculum workbook.
- Status: 🟢 on track (no flags) · 🟡 watch (INCs / a retake pending) · 🔴 needs attention (recent delinquency, ≥3 retakes, or no current enrollment).

## Semester workflow

At each enrollment/advising period, per student — entirely in the browser:

1. **Import** the fresh registrar scrape (or **encode grades** manually) — checklist, flags, header, and `ROSTER.md` update automatically.
2. Check the **Flags board** and **INC deadlines** on the dashboard.
3. Run **Enrollment advising** — review computed eligibility, tick the courses, print the advising slip for signing; the conversation is recorded as an advising note.
4. On graduation, **Mark graduated** — the folder moves to `students/graduated/<year>/`.

## Reusing this for your own advisees

Because all student data is gitignored, a fresh clone is an **empty but fully working
system**:

1. Clone the repo and `pip install -r requirements.txt`.
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
| Curriculum checklists, prospectus, calendars, policy forms | `raw/*.json` — registrar grade scrapes |
| This README | `ROSTER.md`, `tools/roster.json` — generated rosters |
| | `reference/rosters/`, `reference/misc/` — official lists, grade monitoring |
| | `.backups/` — pre-write file snapshots |

Git is used for versioning the *system*; student-file history is kept in `.backups/`
instead, precisely so PII can never end up in a public git history. See
[docs/SAAIS-IMPLEMENTATION.md](docs/SAAIS-IMPLEMENTATION.md) for this and other
design decisions, and [docs/SAAIS-PLAN.md](docs/SAAIS-PLAN.md) for the original plan.
