# -*- coding: utf-8 -*-
"""Per-student JSON records — the source of truth since the v2 data layer.

Each student folder holds a single `record.json` with the profile, the grade
entries, manual checklist state, advising notes and attachment metadata.
Markdown files are no longer the database; they are generated on demand as an
export format (see render/student_md.py and the Export MD action).

Guarantees carried over from v1:
- every write is preceded by a timestamped copy under .backups/ (backups.py)
- records stay inside the gitignored students/ tree (privacy-by-design)
- stale writes are rejected via a content hash of the record as loaded
- derived values (units earned, GWA, year level, flags) are never stored here;
  they are recomputed from the grade entries on every read (domain/rules.py)
"""
import hashlib
import json
import os
from datetime import date

from . import backups, paths

SCHEMA = 1

STATUSES = ("active", "inactive", "graduated")
INACTIVE_REASONS = ("leave of absence", "absence without leave",
                    "transferred", "shifted", "other")
CHECKLIST_STATUSES = ("passed", "pending", "enrolled")

REQUIRED_STUDENT = ("student_number", "name", "program")
REQUIRED_GRADE = ("academic_year", "semester", "course_code", "course_title", "units")
GRADE_DEFAULTS = {"midterm": None, "grade": None, "completion": None}


class RecordError(ValueError):
    """Raised when a record does not match the expected schema — fail loudly."""


def new_record(student_number, name, program, curriculum=None, entered="",
               email="", contact="", status="active"):
    today = date.today().isoformat()
    return {
        "schema": SCHEMA,
        "student": {
            "student_number": student_number,
            "name": name,
            "program": program,
            "curriculum": curriculum,        # curriculum key; None = autodetect
            "entered": entered,              # first AY enrolled, e.g. "2025-2026"
            "email": email,
            "contact": contact,
            "status": status,
            "inactive_reason": None,
            "graduated_year": None,
        },
        "grades": [],       # same entry shape as the registrar scrapes
        "checklist": {},    # manual per-course state: {key: {status, remarks: []}}
        "notes": [],        # advising notes: {id, date, text}
        "attachments": [],  # metadata only: {name, type, added}
        "meta": {"created": today, "updated": today, "note_seq": 0},
    }


def validate_grade(g, i):
    for k in REQUIRED_GRADE:
        if g.get(k) in (None, ""):
            raise RecordError(f"grades[{i}].{k} is missing or empty ({g.get('course_code', '?')}).")
    try:
        g["units"] = float(g["units"])
    except (TypeError, ValueError):
        raise RecordError(f"grades[{i}].units is not a number.")
    for k, v in GRADE_DEFAULTS.items():
        g.setdefault(k, v)
    return g


def validate(rec):
    if not isinstance(rec, dict) or "student" not in rec:
        raise RecordError("Record must be an object with a 'student' key.")
    s = rec["student"]
    for k in REQUIRED_STUDENT:
        if not s.get(k):
            raise RecordError(f"student.{k} is missing or empty.")
    if s.get("status") not in STATUSES:
        raise RecordError(f"student.status must be one of {STATUSES}.")
    if s["status"] == "inactive" and not s.get("inactive_reason"):
        raise RecordError("An inactive student needs an inactive_reason.")
    if not isinstance(rec.get("grades"), list):
        raise RecordError("'grades' must be a list.")
    for i, g in enumerate(rec["grades"]):
        validate_grade(g, i)
    for key in ("checklist", "meta"):
        if not isinstance(rec.setdefault(key, {}), dict):
            raise RecordError(f"'{key}' must be an object.")
    for key in ("notes", "attachments"):
        if not isinstance(rec.setdefault(key, []), list):
            raise RecordError(f"'{key}' must be a list.")
    for i, item in enumerate(rec["checklist"].values()):
        if item.get("status") not in CHECKLIST_STATUSES:
            raise RecordError(f"checklist entries need a status in {CHECKLIST_STATUSES}.")
    return rec


def load(folder_path):
    """Validated record dict, or None if the folder has no record.json."""
    path = paths.record_path(folder_path)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        try:
            rec = json.load(fh)
        except json.JSONDecodeError as e:
            raise RecordError(f"{path} is not valid JSON: {e}")
    return validate(rec)


def dumps(rec):
    return json.dumps(rec, indent=2, ensure_ascii=False)


def content_hash(rec):
    """Short hash of the record content — embedded in pages so stale writes
    (record changed on disk after the page loaded) can be rejected."""
    return hashlib.sha256(dumps(rec).encode("utf-8")).hexdigest()[:16]


def save(folder_path, rec):
    """Validate → backup the previous version → write. Returns the path."""
    validate(rec)
    rec["meta"]["updated"] = date.today().isoformat()
    path = paths.record_path(folder_path)
    backups.backup(path)
    os.makedirs(folder_path, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(rec))
    return path


def add_note(rec, text, when=None):
    """Append an advising note; returns the new note dict."""
    text = " ".join(text.split())
    if not text:
        raise RecordError("Empty note.")
    rec["meta"]["note_seq"] = int(rec["meta"].get("note_seq", 0)) + 1
    note = {"id": rec["meta"]["note_seq"],
            "date": when or date.today().isoformat(),
            "text": text}
    rec["notes"].append(note)
    return note


def notes_newest_first(rec):
    return sorted(rec["notes"], key=lambda n: (n.get("date", ""), n.get("id", 0)), reverse=True)


def find_grade(rec, ay, sem, course_code):
    for g in rec["grades"]:
        if (g["academic_year"], g["semester"], g["course_code"]) == (ay, sem, course_code):
            return g
    return None


def delete_grade(rec, ay, sem, course_code):
    """Remove a matching grade entry in place. Raises if none matches."""
    g = find_grade(rec, ay, sem, course_code)
    if g is None:
        raise RecordError(f"No grade entry for {course_code} in {ay} {sem}.")
    rec["grades"].remove(g)


def set_lifecycle(rec, status, reason=None, graduated_year=None):
    """Set student.status (+ inactive_reason / graduated_year); re-validated
    by the caller's records.save()."""
    if status not in STATUSES:
        raise RecordError(f"status must be one of {STATUSES}.")
    s = rec["student"]
    s["status"] = status
    s["inactive_reason"] = reason if status == "inactive" else None
    s["graduated_year"] = int(graduated_year) if status == "graduated" and graduated_year else None


def set_checklist_status(rec, code, status):
    """Manual override of a checklist row's status; anything not listed here
    is derived from grades. Preserves any existing remarks."""
    if status not in CHECKLIST_STATUSES:
        raise RecordError(f"checklist status must be one of {CHECKLIST_STATUSES}.")
    item = rec["checklist"].setdefault(code, {"status": status, "remarks": []})
    item["status"] = status
    item.setdefault("remarks", [])


def add_checklist_remark(rec, code, text):
    text = " ".join(text.split())
    if not text:
        raise RecordError("Empty remark.")
    item = rec["checklist"].setdefault(code, {"status": "pending", "remarks": []})
    item.setdefault("remarks", []).append(text)


def delete_checklist_remark(rec, code, idx):
    item = rec["checklist"].get(code)
    if item is None or not (0 <= idx < len(item.get("remarks", []))):
        raise RecordError(f"No remark #{idx} for {code}.")
    del item["remarks"][idx]


def add_attachment(rec, name, mimetype):
    from datetime import date as _date
    rec["attachments"].append({"name": name, "type": mimetype or "application/octet-stream",
                               "added": _date.today().isoformat()})
