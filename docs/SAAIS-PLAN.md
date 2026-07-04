# Student Academic Advising Information System (SAAIS)

Development plan — drafted 2026-07-04.

## 1. Vision

A **local web system** for one adviser, running entirely on this machine, that uses the
files in this repository as its database. No external server, no cloud, no separate DBMS
to administer. Every interaction in the browser (adding an advising note, encoding a
grade, importing a fresh registrar scrape) **writes back to the repo files**, so the
Markdown files remain the single source of truth and stay readable/editable by hand even
if the system is never opened again.

## 2. Guiding principles

1. **Files are the database.** `students/active/*/*.md` + `raw/*.json` +
   `reference/curriculum/*.xlsx` are canonical. The web system is a *view and editor*
   over them, never a replacement.
2. **Round-trip safety.** The system must be able to parse a student MD file, modify one
   section, and rewrite it without disturbing hand-made edits elsewhere. Hand edits and
   system edits must coexist.
3. **Derived data is always recomputed, never stored as truth.** Units earned, GWA, year
   level, flags, and the README roster table are recalculated from grades on every write.
4. **Every write is reversible.** Automatic timestamped backup (or git commit) before any
   file mutation.

## 3. Recommended stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.10 (already installed) | `openpyxl`, `pandas` already present; reuses `tools/generate_student_md.py` logic |
| Web framework | **Flask** + Jinja2 templates | Minimal, serves on `localhost`, no build step |
| Interactivity | **htmx** (single static JS file, vendored) | Inline edits/partial updates without a JS framework or npm |
| Index / cache | **SQLite** (stdlib `sqlite3`), rebuilt from files at startup | Fast queries/search; disposable — deleting the .db is harmless |
| MD parsing | `python-frontmatter` + section-based parser (regex on `##` headings) | Student files already follow a fixed section layout |
| File watching | `watchdog` | Detect hand edits while the server is running; re-index changed files |
| Versioning | `git` (init a repo at the root) | Free undo history for every interaction; commit per write with a message like `note: LARAGA 2026-07-04` |

Run as: `python -m saais` → opens `http://localhost:8000`. Optionally a `SAAIS.bat`
double-click launcher on the Desktop.

## 4. Data model (files ↔ entities)

| Entity | Backing file(s) | System writes? |
|---|---|---|
| Student profile | MD header table in `students/active/<Name>/<NAME>.md` | Yes (contact, status) |
| Grades / attempts | `raw/<student-no>.json` (imported) + "Grade history by term" MD section | Yes (grade encoding, scrape import) |
| Curriculum + prereqs | `reference/curriculum/Course-Checklist-*.xlsx` (parsed read-only) | No |
| Checklist status | Computed from grades × curriculum; rendered into the MD checklist section | Yes (regenerated section) |
| Flags | Computed (retakes, INC deadlines, delinquency, stop-out) | Yes (regenerated section) |
| Advising notes | "Advising notes" MD section | Yes (append-only via UI; hand edits preserved) |
| Roster overview | Root `README.md` table | Yes (regenerated table between markers) |
| Graduated/removed | Folder moves under `students/` | Yes (lifecycle actions) |

**Write strategy:** each MD file is treated as an ordered list of sections keyed by
heading. Computed sections (header table, Flags, Checklist, Grade history) are replaced
wholesale on update; free-text sections (Advising notes and anything the adviser adds)
are preserved byte-for-byte, with UI note-adds inserted as new table rows. HTML comment
markers (e.g. `<!-- saais:begin flags -->`) make the boundaries explicit and hand-edit-proof.

## 5. Features by phase

### Phase 1 — Read-only dashboard (MVP)
- Parse all repo files into SQLite at startup; file-watcher re-indexes on change.
- **Roster page**: sortable/filterable table (status, year level, curriculum, GWA, flags), same data as README.
- **Student page**: rendered MD (profile, flags, checklist, grade history, notes).
- **Flags board**: all 🔴/🟡 items across advisees grouped by type (INC deadlines, retakes, delinquency, stop-outs).
- *Exit criterion: everything visible in the browser matches the MD files exactly.*

### Phase 2 — Write-back interactions
- **Advising notes**: add a dated note from the student page → appended to the MD notes table (+ git commit).
- **Scrape import**: drop a new `raw/*.json` (or paste registrar output) → grades merged, checklist/flags/header recomputed, MD sections regenerated, README roster synced.
- **Manual grade encoding**: enter final grades / INC completions for the current term through a form (for when a full scrape isn't available).
- **Profile edits**: contact number, email, status override.
- *Exit criterion: a full semester update for one student can be done entirely in the browser, and the resulting MD diff is clean.*

### Phase 3 — Advising workflows
- **Enrollment advising assistant**: per student, compute *Can Enroll* from prereqs + passed courses; adviser ticks *Will Enroll*; unit-load validation; printable advising slip (HTML → print) for signing.
- **INC deadline tracker**: countdown per outstanding INC (1-year lapse rule) with a home-page warning list.
- **Semester rollover**: one action that closes a term — finalizes in-progress courses, recomputes everything, archives a roster snapshot per term.
- **Graduation audit + lifecycle**: remaining-requirements report; "Mark graduated" moves the folder to `students/graduated/<year>/` and updates the README.
- **New advisee intake**: form or JSON import that scaffolds the folder + MD file (what `tools/generate_student_md.py` did, per student).

### Phase 4 — Quality of life (optional)
- Search across notes/courses; batch views (per-course failure rates, batch GWA trends — e.g. the 2025 freshman delinquency wave).
- Charts (GWA over terms, units progress vs. expected).
- Export: per-student PDF summary; CSV of the roster.
- Config page for rules (pass threshold, delinquency %, year-level unit cutoffs) stored in `saais.toml`.

## 6. Proposed project layout

```
academic advising/
├── saais/                     ← the web system (new)
│   ├── __main__.py            ← `python -m saais` entry point
│   ├── app.py                 ← Flask routes
│   ├── repo/                  ← file I/O: md_parser.py, md_writer.py,
│   │                             curriculum.py (xlsx), scrape.py (raw JSON), gitops.py
│   ├── domain/                ← rules.py (grades/flags/GWA — extracted from
│   │                             tools/generate_student_md.py), advising.py (prereqs)
│   ├── index/                 ← sqlite.py (rebuildable cache), watcher.py
│   ├── templates/  static/    ← Jinja pages, htmx, one CSS file
│   └── saais.toml             ← rules config
├── students/  raw/  reference/  docs/  tools/   ← unchanged (the "database")
└── .git/                      ← version history = audit trail
```

## 7. Consistency & safety

- **Startup**: full re-index of all files → SQLite (seconds for ~30 students).
- **Hand edits while running**: watcher re-indexes; if a file changed on disk after the
  page was loaded, writes are rejected with a "file changed, reload" prompt (compare
  content hash captured at read time).
- **Backups**: git commit before/after every mutation; `git log` per student file is the
  audit trail. If git is unwanted: `\.backups/<timestamp>/` copies instead.
- **Privacy**: binds to `127.0.0.1` only; no auth needed for single-user local use, but
  the data is PII — keep the folder out of cloud-sync services unless encrypted.

## 8. Milestones

| Milestone | Scope | Estimate |
|---|---|---|
| M0 | `git init`, extract shared rules module from `tools/generate_student_md.py`, MD round-trip parser + tests | 1–2 days |
| M1 | Phase 1 dashboard | 2–3 days |
| M2 | Phase 2 write-back (notes → scrape import → grade encoding) | 3–4 days |
| M3 | Phase 3 workflows (advising assistant first — highest advising value) | 4–5 days |
| M4 | Phase 4 polish | as needed |

Sequenced so the system is useful after every milestone; M2 is the point where the
"regularly updates upon interaction" requirement is fully met.

## 9. Risks / open questions

- **MD round-trip fidelity** is the core technical risk → mitigate with section markers
  (M0) and golden-file tests against the 27 real student files.
- **Registrar scrape format drift**: keep the JSON importer schema-tolerant and fail loudly.
- **Two curricula + shifters** (e.g. Nable, 2023 admit on the 2025 curriculum): curriculum
  should be an explicit per-student field (editable in the UI), not inferred forever.
- Open: should the checklist `.xlsx` files also be written back, or frozen as legacy?
  (Plan assumes frozen; the MD supersedes them.)
