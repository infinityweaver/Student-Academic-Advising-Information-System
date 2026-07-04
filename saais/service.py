# -*- coding: utf-8 -*-
"""Write-back operations over the JSON records. Every mutation: check the
stale-write hash → backup → write record.json → resync ROSTER.md.

Markdown is no longer written on mutation — it is generated on demand by
export_md() (Students list → Export MD)."""
import io
import os
import shutil
import zipfile

from .domain import rules
from .index.store import Store
from .render import roster_md, student_md
from .repo import backups, curriculum, paths, records, scrape


class Conflict(Exception):
    """The record changed on disk after the page was loaded — reload and retry."""


def _check_hash(st, expected_hash):
    if expected_hash and st.rec_hash and expected_hash != st.rec_hash:
        raise Conflict("record.json changed on disk since the page was loaded. "
                       "Reload the page and re-apply your change.")


def _write(store: Store, st):
    records.save(st.folder_path, st.record)
    store.invalidate(st)
    sync_roster(store)


# ------------------------------------------------------------------ mutations
def add_note(store: Store, st, note, expected_hash=None, when=None):
    _check_hash(st, expected_hash)
    records.add_note(st.record, note, when)
    _write(store, st)


def edit_profile(store: Store, st, email, contact, curkey, expected_hash=None):
    _check_hash(st, expected_hash)
    s = st.record["student"]
    s["email"] = email.strip()
    s["contact"] = contact.strip()
    s["curriculum"] = curkey or None
    _write(store, st)


def encode_grades(store: Store, st, updates, expected_hash=None):
    """updates: [{'academic_year','semester','course_code','course_title','units',
    'midterm','grade','completion'}] — existing (term, code) entries are updated,
    new ones appended."""
    _check_hash(st, expected_hash)
    changed = 0
    for u in updates:
        rec = records.find_grade(st.record, u["academic_year"], u["semester"], u["course_code"])
        vals = {k: (u.get(k) or "").strip() or None for k in ("midterm", "grade", "completion")}
        if rec is None:
            if not u.get("course_title") or not u.get("units"):
                raise ValueError(f"New record {u['course_code']} needs a title and units.")
            rec = {"academic_year": u["academic_year"], "semester": u["semester"],
                   "course_code": u["course_code"], "course_title": u["course_title"],
                   "units": float(u["units"]), **vals}
            st.record["grades"].append(rec)
            changed += 1
        else:
            before = {k: rec.get(k) for k in vals}
            rec.update({k: v for k, v in vals.items() if v is not None or before[k] is not None})
            if any(rec.get(k) != before[k] for k in vals):
                changed += 1
    if changed:
        _write(store, st)
    return changed


def merge_scrape(rec, data):
    """Merge a registrar scrape into a record: update matching (term, code)
    grade entries, append new ones; refresh name/program. Returns #changed."""
    changed = 0
    rec["student"]["name"] = data["student"]["name"]
    rec["student"]["program"] = data["student"]["program"]
    for g in data["grades"]:
        mine = records.find_grade(rec, g["academic_year"], g["semester"], g["course_code"])
        if mine is None:
            rec["grades"].append(dict(g))
            changed += 1
        elif any(mine.get(k) != g.get(k) for k in ("units", "midterm", "grade", "completion", "course_title")):
            mine.update(g)
            changed += 1
    return changed


def import_scrape(store: Store, text):
    """Paste/upload a fresh scrape → keep an audit copy in raw/ → merge the
    grade entries into the student's record. Returns (sid, student_or_None)."""
    data = scrape.parse_text(text)
    sid = data["student"]["student_number"]
    backups.backup(paths.raw_path(sid))
    scrape.save(data)                       # audit copy of what the registrar said
    st = store.get(sid)
    if st and st.record:
        merge_scrape(st.record, data)
        _write(store, st)
        return sid, st
    return sid, None


def intake(store: Store, text, folder_name):
    """New advisee: students/active/<Folder>/record.json seeded from a scrape
    (plus an audit copy of the scrape in raw/)."""
    data = scrape.parse_text(text)
    sid = data["student"]["student_number"]
    folder_name = folder_name.strip().rstrip(".")
    if not folder_name:
        raise ValueError("Folder name is required (e.g. \"Surname, Firstname\").")
    if os.sep in folder_name or "/" in folder_name or ".." in folder_name:
        raise ValueError("Folder name must be a plain name, not a path.")
    fpath = os.path.join(paths.ACTIVE_DIR, folder_name)
    if os.path.exists(paths.record_path(fpath)):
        raise ValueError(f"{folder_name} already has a record.json.")
    if store.get(sid):
        raise ValueError(f"A record for {sid} already exists.")
    scrape.save(data)
    s = data["student"]
    rec = records.new_record(sid, s["name"], s["program"],
                             entered=f"20{sid[:2]}-20{int(sid[:2]) + 1}" if sid[:2].isdigit() else "")
    rec["grades"] = data["grades"]
    records.save(fpath, rec)
    store.invalidate()
    sync_roster(store)
    return sid, folder_name


def graduate(store: Store, st, year):
    """Mark graduated and move the folder to students/graduated/<year>/."""
    year = str(year).strip()
    if not year.isdigit():
        raise ValueError("Graduation year must be a number.")
    dest_dir = os.path.join(paths.GRADUATED_DIR, year)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, st.folder)
    if os.path.exists(dest):
        raise ValueError(f"{dest} already exists.")
    st.record["student"]["status"] = "graduated"
    st.record["student"]["graduated_year"] = int(year)
    records.save(st.folder_path, st.record)
    backups.backup(paths.record_path(st.folder_path))
    shutil.move(st.folder_path, dest)
    store.invalidate()
    sync_roster(store)
    return dest


# ------------------------------------------------------------------ exports
def render_md(store: Store, st):
    """The student's advising Markdown, generated from the record on demand."""
    if not st.record:
        raise ValueError(f"{st.folder} has no record.")
    an = st.an
    if an is None and st.record["grades"]:
        an = rules.analyze(st.record, curriculum.load_all(), store.config,
                           st.record["student"].get("curriculum"))
    return student_md.render(st.record, an)


def export_md(store: Store, sids, out_dir=None):
    """Generate MD files for the selected students. Returns (zip_bytes, names);
    if out_dir is given the files are also written there."""
    chosen = [st for st in store.all_students() if st.sid in set(sids)]
    if not chosen:
        raise ValueError("No students selected.")
    if out_dir:
        out_dir = out_dir.strip()
        if not os.path.isdir(out_dir):
            raise ValueError(f"Output directory does not exist: {out_dir}")
    buf = io.BytesIO()
    names = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for st in chosen:
            name = st.folder.upper() + ".md"
            text = render_md(store, st)
            zf.writestr(name, text)
            names.append(name)
            if out_dir:
                with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
                    fh.write(text)
    return buf.getvalue(), names


def sync_roster(store: Store):
    return roster_md.sync(store.students())
