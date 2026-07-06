# SAAIS — Implementation notes

Implemented 2026-07-04 against [SAAIS-PLAN.md](SAAIS-PLAN.md). This documents what
was built, where the implementation deliberately deviates from the plan, and what
remains open.

## Status by phase

| Plan item | Status |
|---|---|
| M0: rules module extracted, MD round-trip parser, repo under git | ✅ `saais/domain/rules.py`, `saais/repo/md_doc.py` — verified: identical units/GWA/flags/status for all 27 real students vs `tools/roster.json`; merge preserves hand sections byte-for-byte and is idempotent |
| Phase 1: roster page, student page, flags board | ✅ |
| Phase 2: advising notes, scrape import, manual grade encoding, profile edits | ✅ (profile = email/contact/curriculum; status stays computed) |
| Phase 3: enrollment advising assistant + printable slip | ✅ prereq eligibility, unit-load warning, print view; non-course prereqs (e.g. "3rd year standing") are surfaced as *verify manually* |
| Phase 3: INC deadline tracker | ✅ dashboard countdown; deadlines approximated from term ends (Dec / Jun / Aug) — confirm against the registrar |
| Phase 3: graduation lifecycle + new advisee intake | ✅ |
| Phase 3: semester rollover (one-click term close + roster snapshot) | ❌ not built — closing a term is currently: import fresh scrapes (or encode grades), then update `[term]` in `saais.toml` and restart |
| Phase 4: search, charts, PDF/CSV export, config UI | ❌ not built (config is the hand-edited `saais.toml`) |

## Deviations from the plan (and why)

1. **Backups instead of git commits for student files.** The plan proposed a git
   commit per write as the audit trail. This repo is now *public* with all student
   files gitignored — committing them into the same history would leak PII, and git
   refuses ignored paths anyway. SAAIS therefore uses the plan's stated fallback:
   a copy of every file it is about to mutate goes to `.backups/<timestamp>/`
   (gitignored). If you want git-based history for student files, init a *separate,
   private* repo elsewhere; do not commit them here.

2. **In-memory index instead of SQLite + watchdog.** At ~30 students a full
   re-scan is milliseconds, so the index is a per-request mtime check with cached
   parses (`saais/index/store.py`). Same guarantees as the plan's disposable SQLite
   cache — hand edits made while the server runs are picked up on the next request —
   with two fewer dependencies. Conflict detection uses a content hash captured when
   the page was rendered; a stale write is rejected with a "reload" message.

3. **Roster moved from README.md to ROSTER.md.** The plan had SAAIS regenerate the
   roster table inside the root README. The README is public now, so the generated
   roster (names, IDs, GWAs) lives in the gitignored `ROSTER.md`, rewritten between
   `<!-- saais:begin/end roster -->` markers after every write.

4. **Heading-based section boundaries, no extra markers.** The plan suggested
   `<!-- saais:begin ... -->` markers inside student files. The existing 27 files
   already follow a fixed `##` section layout, so the round-trip writer keys on
   headings instead: computed sections (header, Flags, Currently enrolled, Curriculum
   checklist, Other courses, Grade history) are replaced wholesale; everything else —
   Advising notes and any hand-added section — is preserved byte-for-byte. This keeps
   the files clean and works with the files as they are.

5. **`saais.toml` is parsed by a minimal built-in reader** (Python 3.10 has no
   `tomllib`): `[section]`, `key = value`, `#` comments — which is all the config uses.

## Answers to the plan's open questions

- **Checklist `.xlsx` files** in student folders are frozen as legacy; SAAIS reads
  them for nothing (contact info now lives in the MD header, which SAAIS edits).
  The curriculum workbooks in `reference/curriculum/` remain the read-only source
  of courses, prerequisites, and unit thresholds.
- **Two curricula / shifters:** curriculum is an explicit per-student field (the
  header's `Curriculum` row), editable on the student page; autodetected from course
  codes only when the field is missing.
- **Scrape format drift:** the importer validates the schema and fails loudly
  (`saais/repo/scrape.py`) rather than guessing.

## Testing done

- Rules fidelity: recomputed all 27 advisees, exact match on units, GWA, year level,
  status, flag counts, and curriculum vs the generator's `tools/roster.json`.
- Round-trip: for all 27 files, regenerate+merge changes only the `last updated`
  status line, preserves hand sections byte-for-byte, and is idempotent.
- Live: all pages served; note add (with backup + conflict rejection on stale hash),
  intake → grade encoding (final grade + INC completion) → advising slip →
  mark-graduated exercised end-to-end on a synthetic student, then removed.

## 2026-07-06 — UI/UX refactor (Issue #1 follow-up)

All v2 features (Dashboard, Curriculum, Students, Reports, advising notes CRUD,
AI chat) had shipped, but the top nav was still one flat list of 8 links and the
student page — the busiest page, with flags, checklist, grade history, notes,
attachments, and chat all on one URL — had no way to jump between sections. This
pass changes only templates/CSS and documentation (`saais/templates/base.html`,
`saais/templates/home.html`, `saais/templates/student.html`,
`saais/static/style.css`, this file, and `README.md`); no routes, schemas, or
domain logic changed.

- **Grouped nav**: `Dashboard · Students ▾ (Roster, Flags board, Add advisee, New
  advisee from scrape, Import scrape) · Curricula · Reports` — matches the four
  features from Issue #1 instead of a flat link list. Active page is highlighted;
  narrow viewports collapse the nav behind a ☰ toggle.
- **Dashboard quick actions**: one-click buttons to the most common next steps
  (open roster, add advisee, import scrape, flags board, curricula, reports).
- **Student page sub-nav**: a sticky quick-jump bar (Flags · Checklist · Grades ·
  Notes · Attachments) plus a back-to-roster link, since the page is long.
- No files removed by this pass — a repo-wide check found no unused tracked files
  (`git ls-files` was reviewed; `saais/repo/md_doc.py` still backs the one-time v1
  migration in `saais/migrate.py` and is kept).

Tracked in Issue #1, shipped in PR #7. Copilot's automated review on PR #7 flagged
two issues, both fixed in the same PR before merge:
1. `saais/templates/base.html` — the `navlink` macro and the Students dropdown
   `<summary>` used `{{ 'active' if <cond> }}`, an inline Jinja conditional
   expression with no `else`, which raises `TemplateSyntaxError` in strict Jinja
   configurations. Fixed to `{{ 'active' if <cond> else '' }}` in both spots.
2. This file — the note said the pass "only touches templates/CSS", which was
   inaccurate since it also updated this file and `README.md`; reworded to say
   templates/CSS *and documentation*.
