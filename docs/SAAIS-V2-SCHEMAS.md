# SAAIS v2 — data store schemas

Since the v2 data layer (issue #1, phase 0) the source of truth is structured
JSON. Markdown is an **export format** generated on demand; the legacy MD
files are never parsed back after migration (`python -m saais.migrate`).

Design rules carried over from v1:

- **Privacy-by-design** — student records live inside the gitignored
  `students/` tree; nothing containing PII is ever committed.
- **Pre-write backups** — every mutation first copies the previous version to
  `.backups/<timestamp>/<repo-relative-path>`.
- **Stale-write rejection** — pages embed a short content hash of the record
  as loaded; a write whose hash no longer matches the file on disk is refused.
- **Derived values are never stored** — units earned, GWA, year level, flags
  and status are recomputed from the grade entries on every read
  (`saais/domain/rules.py`). Year level is autocomputed from units earned;
  thresholds are configurable in `saais.toml` (`[year_level] thresholds`),
  falling back to the curriculum's own thresholds.

## Student record — `students/<status>/<Folder>/record.json`

One file per student, inside the student's own folder (which also holds their
attachments). `<status>` is `active/`, `inactive/` or `graduated/<year>/`.

```jsonc
{
  "schema": 1,
  "student": {
    "student_number": "25-1-03407",
    "name": "SURNAME, FIRSTNAME MI",
    "program": "BSCS",
    "curriculum": "2018",          // curriculum key; null = autodetect from grades
    "entered": "2025-2026",        // first AY enrolled
    "email": "student@example.com",
    "contact": "09xxxxxxxxx",
    "status": "active",            // active | inactive | graduated
    "inactive_reason": null,       // required when inactive: leave of absence |
                                   // absence without leave | transferred | shifted | other
    "graduated_year": null         // int when graduated
  },

  // Grade entries — same shape as the registrar scrapes, so scrapes merge in
  // directly and rules.analyze() consumes the record as-is.
  "grades": [
    {
      "academic_year": "2025-2026",
      "semester": "First Semester", // First Semester | Second Semester | Summer/Mid Year
      "course_code": "CSIT 101",
      "course_title": "INTRODUCTION TO COMPUTING",
      "units": 3.0,
      "midterm": "2.1",             // number-string | "INC"/"S"/"NA"/"Def" | null
      "grade": "1.9",               // number-string | "INC" | "DR" | "S" | "NA" | null (in progress)
      "completion": null            // grade that resolved an INC, else null
    }
  ],

  // Manual per-course checklist state (phase 3.3 UI): keyed by curriculum row.
  // Only overrides are stored; anything not listed is derived from grades.
  "checklist": {
    "CSIT 101": { "status": "passed",   // passed | pending | enrolled
                  "remarks": ["credited from XYZ"] }
  },

  "notes": [                        // advising notes — full CRUD (phase 3.4)
    { "id": 1, "date": "2026-07-04", "text": "Advised CSIT 201, CSIT 202 (6 units)." }
  ],

  "attachments": [                  // metadata only; the files themselves live
    {                               // in the student's folder next to record.json
      "name": "shifting-form.pdf",
      "type": "application/pdf",
      "added": "2026-07-04"
    }
  ],

  "meta": { "created": "2026-07-04", "updated": "2026-07-05", "note_seq": 1 }
}
```

## Curriculum — `data/curricula/<id>.json` (phase 2)

Curricula are not PII and are committed. After creation only the effective
year range is editable — students' checklists depend on the sections/courses.

```jsonc
{
  "schema": 1,
  "id": "bscs-2018",                // slug: <program>-<start year>; the two
                                    // migrated legacy curricula keep their v1
                                    // keys "2018"/"2025" (student records use them)
  "program": "BSCS",
  "effective_start": 2018,
  "effective_end": 2024,            // null = "present"
  "sections": [                     // identified by year level + semester
    {
      "year": 1,
      "term": "1st",                // 1st | 2nd | Midyear
      "courses": [
        { "code": "CSci 100", "title": "Introduction to Computing",
          "units": 3.0, "prereq": "None" }
      ]
    }
  ],
  // Year-level thresholds; the last pair is (total units, "Graduating").
  // Omitted on creation -> quartiles of total units.
  "thresholds": [[0, "1st year"], [52, "2nd year"], [98, "3rd year"],
                 [140, "4th year"], [168, "Graduating"]],
  "meta": { "created": "2026-07-05", "updated": "2026-07-05", "source": "xlsx import" }
}
```

The two legacy workbooks (`reference/curriculum/Course-Checklist-*.xlsx`) are
importable through the curriculum UI so nothing needs re-encoding by hand.

## Registrar scrapes — `raw/<student-no>.json` (unchanged, audit copies)

Scrapes keep their v1 shape (`{"student": {...}, "grades": [...]}`). They are
no longer read at page time — importing a scrape merges its grade entries into
the student's record (matching on academic year + semester + course code) and
keeps the file as an audit copy of what the registrar reported.
