# -*- coding: utf-8 -*-
"""Write-back operations. Every mutation: backup → write file(s) → regenerate
computed MD sections (hand-written sections preserved) → resync ROSTER.md."""
import os
import shutil
from datetime import date

from .domain import rules
from .index.store import Store
from .render import roster_md, student_md
from .repo import backups, curriculum, md_doc, paths, scrape


class Conflict(Exception):
    """The file changed on disk after the page was loaded — reload and retry."""


def _check_hash(st, expected_hash):
    if expected_hash and st.md_hash and expected_hash != st.md_hash:
        raise Conflict(f"{os.path.basename(st.md_path)} changed on disk since the page was loaded. "
                       "Reload the page and re-apply your change.")


def _info_from_fields(fields, email=None, contact=None):
    return {
        "email": email if email is not None else fields.get("Email", ""),
        "contact": contact if contact is not None else fields.get("Contact", ""),
    }


def regenerate_md(store: Store, st, source="registrar scrape", email=None, contact=None, curkey=None):
    """Re-render computed sections from raw data; keep notes/hand sections."""
    if not st.raw or not st.an:
        raise ValueError(f"No raw grade data for {st.name} — import a scrape first.")
    an = st.an
    if curkey and curkey != an["curkey"]:
        an = rules.analyze(st.raw, curriculum.load_all(), store.config, curkey)
    info = _info_from_fields(st.fields, email, contact)
    fresh = student_md.render(st.raw, info, an, source)
    if st.md_text is not None:
        new_text = md_doc.merge(fresh, st.md_text)
        backups.backup(st.md_path)
    else:
        new_text = fresh
        st.md_path = paths.md_path(st.folder)
    with open(st.md_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    sync_roster(store)
    return st.md_path


def add_note(store: Store, st, note, expected_hash=None, when=None):
    _check_hash(st, expected_hash)
    if not note.strip():
        raise ValueError("Empty note.")
    backups.backup(st.md_path)
    new_text = md_doc.add_note(st.md_text, when or date.today().isoformat(), note)
    with open(st.md_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)


def edit_profile(store: Store, st, email, contact, curkey, expected_hash=None):
    _check_hash(st, expected_hash)
    regenerate_md(store, st, source="profile edit; registrar scrape",
                  email=email.strip(), contact=contact.strip(), curkey=curkey or None)


def encode_grades(store: Store, st, updates, expected_hash=None):
    """updates: [{'academic_year','semester','course_code','course_title','units',
    'midterm','grade','completion'}] — existing (term, code) records are updated,
    new ones appended. Then the MD is regenerated."""
    _check_hash(st, expected_hash)
    if not st.raw:
        raise ValueError("No raw grade data for this student.")
    backups.backup(st.raw_path, st.md_path)
    changed = 0
    for u in updates:
        rec = scrape.find_record(st.raw, u["academic_year"], u["semester"], u["course_code"])
        vals = {k: (u.get(k) or "").strip() or None for k in ("midterm", "grade", "completion")}
        if rec is None:
            if not u.get("course_title") or not u.get("units"):
                raise ValueError(f"New record {u['course_code']} needs a title and units.")
            rec = {"academic_year": u["academic_year"], "semester": u["semester"],
                   "course_code": u["course_code"], "course_title": u["course_title"],
                   "units": float(u["units"]), **vals}
            st.raw["grades"].append(rec)
            changed += 1
        else:
            before = {k: rec.get(k) for k in vals}
            rec.update({k: v for k, v in vals.items() if v is not None or before[k] is not None})
            if any(rec.get(k) != before[k] for k in vals):
                changed += 1
    if changed:
        scrape.save(st.raw)
        store._cache.pop(st.folder, None)
        st2 = store.by_folder(st.folder)
        regenerate_md(store, st2, source="grade encoding; registrar scrape")
    return changed


def import_scrape(store: Store, text):
    """Paste/upload a fresh scrape → save raw JSON → regenerate the student MD.
    Returns (sid, folder_or_None)."""
    data = scrape.parse_text(text)
    sid = data["student"]["student_number"]
    backups.backup(paths.raw_path(sid))
    scrape.save(data)
    store._cache.clear()
    st = store.get(sid)
    if st:
        regenerate_md(store, st, source="scrape import")
        return sid, st.folder
    return sid, None


def intake(store: Store, text, folder_name):
    """New advisee: save raw JSON + scaffold students/active/<Folder>/<FOLDER>.md."""
    data = scrape.parse_text(text)
    sid = data["student"]["student_number"]
    folder_name = folder_name.strip().rstrip(".")
    if not folder_name:
        raise ValueError("Folder name is required (e.g. \"Surname, Firstname\").")
    if os.sep in folder_name or "/" in folder_name or ".." in folder_name:
        raise ValueError("Folder name must be a plain name, not a path.")
    fpath = os.path.join(paths.ACTIVE_DIR, folder_name)
    if os.path.exists(paths.md_path(folder_name)):
        raise ValueError(f"{folder_name} already has an advising MD file.")
    scrape.save(data)
    os.makedirs(fpath, exist_ok=True)
    an = rules.analyze(data, curriculum.load_all(), store.config)
    fresh = student_md.render(data, {}, an, source="intake")
    with open(paths.md_path(folder_name), "w", encoding="utf-8") as fh:
        fh.write(fresh)
    store._cache.clear()
    sync_roster(store)
    return sid, folder_name


def graduate(store: Store, st, year):
    """Move the student folder to students/graduated/<year>/ and resync."""
    year = str(year).strip()
    if not year.isdigit():
        raise ValueError("Graduation year must be a number.")
    dest_dir = os.path.join(paths.GRADUATED_DIR, year)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, st.folder)
    if os.path.exists(dest):
        raise ValueError(f"{dest} already exists.")
    backups.backup(st.md_path)
    shutil.move(st.folder_path, dest)
    store._cache.pop(st.folder, None)
    sync_roster(store)
    return dest


def sync_roster(store: Store):
    return roster_md.sync(store.students())
