# -*- coding: utf-8 -*-
"""Write-back operations over the JSON records. Every mutation: check the
stale-write hash → backup → write record.json → resync ROSTER.md.

Markdown is no longer written on mutation — it is generated on demand by
export_md() (Students list → Export MD)."""
import io
import os
import shutil
import zipfile

from .domain import ai_chat, rules
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


def edit_note(store: Store, st, note_id, text, expected_hash=None, when=None):
    _check_hash(st, expected_hash)
    records.edit_note(st.record, note_id, text, when)
    _write(store, st)


def delete_note(store: Store, st, note_id, expected_hash=None):
    _check_hash(st, expected_hash)
    records.delete_note(st.record, note_id)
    _write(store, st)


def ask_ai(store: Store, st, message, cfg, expected_hash=None):
    """Append the user's message, ask the local AI model for a reply (context
    strictly limited to this student's own record), append the reply, and
    persist — the transcript never leaves this student's record.json. The
    user's message is kept even if the model call fails, so nothing is lost."""
    _check_hash(st, expected_hash)
    message = " ".join(message.split())
    if not message:
        raise ValueError("Empty message.")
    # Last N turns only — keeps requests small and avoids context-limit
    # failures as a transcript grows; read defensively in case a record was
    # ever hand-edited/partially corrupted.
    recent = st.record["chat"][-20:]
    history = [{"role": t.get("role", "user"), "text": t.get("text", "")} for t in recent]
    records.add_chat_message(st.record, "user", message)
    try:
        reply = ai_chat.ask(cfg, st, history, message)
        records.add_chat_message(st.record, "assistant", reply)
    finally:
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
    for k in ("name", "program"):
        if rec["student"].get(k) != data["student"][k]:
            rec["student"][k] = data["student"][k]
            changed += 1
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


def _validate_folder_name(folder_name):
    folder_name = folder_name.strip().rstrip(".")
    if not folder_name:
        raise ValueError("Folder name is required (e.g. \"Surname, Firstname\").")
    if os.sep in folder_name or "/" in folder_name or ".." in folder_name:
        raise ValueError("Folder name must be a plain name, not a path.")
    fpath = os.path.join(paths.ACTIVE_DIR, folder_name)
    if os.path.exists(fpath):
        raise ValueError(
            f"{folder_name} already exists. If it is a legacy folder, run "
            "`python -m saais.migrate` to migrate it; otherwise choose a different name.")
    return folder_name, fpath


def intake(store: Store, text, folder_name):
    """New advisee: students/active/<Folder>/record.json seeded from a scrape
    (plus an audit copy of the scrape in raw/)."""
    data = scrape.parse_text(text)
    sid = data["student"]["student_number"]
    folder_name, fpath = _validate_folder_name(folder_name)
    if store.get(sid):
        raise ValueError(f"A record for {sid} already exists.")
    backups.backup(paths.raw_path(sid))     # back up any prior scrape before overwriting
    scrape.save(data)
    s = data["student"]
    rec = records.new_record(sid, s["name"], s["program"],
                             entered=f"20{sid[:2]}-20{int(sid[:2]) + 1}" if sid[:2].isdigit() else "")
    rec["grades"] = data["grades"]
    records.save(fpath, rec)
    store.invalidate()
    sync_roster(store)
    return sid, folder_name


def create_advisee(store: Store, folder_name, sid, name, program, curkey, entered, email, contact):
    """Manual "Add advisee" (3.1) — no scrape needed. Defaults: 1st year,
    0 units earned, GWA —, no last term (all derived once grades exist)."""
    sid = (sid or "").strip()
    name = (name or "").strip()
    program = (program or "").strip().upper()
    if not sid:
        raise ValueError("Student ID is required.")
    if not name:
        raise ValueError("Name is required.")
    if not program:
        raise ValueError("Program is required (e.g. BSCS).")
    folder_name, fpath = _validate_folder_name(folder_name)
    if store.get(sid):
        raise ValueError(f"A record for {sid} already exists.")
    rec = records.new_record(sid, name, program, curriculum=curkey or None,
                             entered=(entered or "").strip(),
                             email=(email or "").strip(), contact=(contact or "").strip())
    records.save(fpath, rec)
    store.invalidate()
    sync_roster(store)
    return sid, folder_name


def edit_advisee(store: Store, st, sid, email, contact, curkey, expected_hash=None):
    """3.2 edit: student ID / email / contact / curriculum. Curriculum is
    locked once the student has graduated."""
    _check_hash(st, expected_hash)
    s = st.record["student"]
    sid = (sid or "").strip()
    if not sid:
        raise ValueError("Student ID is required.")
    if sid != s["student_number"]:
        other = store.get(sid)
        if other and other.folder_path != st.folder_path:
            raise ValueError(f"Student ID {sid} is already used by {other.name}.")
        s["student_number"] = sid
    if s["status"] == "graduated" and (curkey or None) != s.get("curriculum"):
        raise ValueError("Curriculum is locked after graduation.")
    s["email"] = email.strip()
    s["contact"] = contact.strip()
    s["curriculum"] = curkey or None
    _write(store, st)


def set_active(store: Store, st, active, reason=None, expected_hash=None):
    """Toggle active/inactive (3.2); moves the folder between
    students/active/ and students/inactive/. A reason is required to
    deactivate. No-op (besides the reason update) if already in that state
    and the folder is already in the right place."""
    _check_hash(st, expected_hash)
    if st.record["student"]["status"] == "graduated":
        raise ValueError("Cannot toggle active/inactive on a graduated student.")
    if not active and reason not in records.INACTIVE_REASONS:
        raise ValueError(f"A reason is required to deactivate — one of {records.INACTIVE_REASONS}.")
    dest_dir = paths.ACTIVE_DIR if active else paths.INACTIVE_DIR
    dest = os.path.join(dest_dir, st.folder)
    records.set_lifecycle(st.record, "active" if active else "inactive",
                          reason=None if active else reason)
    records.save(st.folder_path, st.record)   # backs up the pre-toggle record
    if os.path.abspath(dest) != os.path.abspath(st.folder_path):
        if os.path.exists(dest):
            raise ValueError(f"{dest} already exists.")
        shutil.move(st.folder_path, dest)
    store.invalidate()
    sync_roster(store)


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
    records.set_lifecycle(st.record, "graduated", graduated_year=year)
    records.save(st.folder_path, st.record)   # backs up the pre-graduation record
    shutil.move(st.folder_path, dest)
    store.invalidate()
    sync_roster(store)
    return dest


def ungraduate(store: Store, st, expected_hash=None):
    """Reverse graduate(): moves the folder back to students/active/ and
    clears graduated_year."""
    _check_hash(st, expected_hash)
    if st.record["student"]["status"] != "graduated":
        raise ValueError(f"{st.name} is not graduated.")
    dest = os.path.join(paths.ACTIVE_DIR, st.folder)
    if os.path.exists(dest):
        raise ValueError(f"{dest} already exists.")
    records.set_lifecycle(st.record, "active")
    records.save(st.folder_path, st.record)
    shutil.move(st.folder_path, dest)
    store.invalidate()
    sync_roster(store)
    return dest


def delete_advisee(store: Store, st):
    """Hard delete: the folder is backed up whole (backups.backup_tree) —
    SAAIS's only undo mechanism, matching how curriculum delete/graduate
    already rely on backups instead of a soft-delete/trash state."""
    backups.backup_tree(st.folder_path)
    shutil.rmtree(st.folder_path)
    store.invalidate()
    sync_roster(store)


# ------------------------------------------------------------------ checklist
def save_checklist(store: Store, st, statuses, expected_hash=None):
    """statuses: {course_code: status}. Bulk-applies and writes once. A blank
    status clears a previously-saved override back to "computed" (remarks,
    if any, are untouched) rather than being skipped."""
    _check_hash(st, expected_hash)
    changed = 0
    for code, status in statuses.items():
        status = status or None
        before = st.record["checklist"].get(code, {}).get("status")
        if status == before:
            continue
        records.set_checklist_status(st.record, code, status)
        changed += 1
    if changed:
        _write(store, st)
    return changed


def add_checklist_remark(store: Store, st, code, text, expected_hash=None):
    _check_hash(st, expected_hash)
    records.add_checklist_remark(st.record, code, text)
    _write(store, st)


def delete_checklist_remark(store: Store, st, code, idx, expected_hash=None):
    _check_hash(st, expected_hash)
    records.delete_checklist_remark(st.record, code, idx)
    _write(store, st)


def delete_grade_entry(store: Store, st, ay, sem, code, expected_hash=None):
    _check_hash(st, expected_hash)
    records.delete_grade(st.record, ay, sem, code)
    _write(store, st)


# ------------------------------------------------------------------ attachments
def add_attachment(store: Store, st, filename, mimetype, stream, expected_hash=None):
    from werkzeug.utils import secure_filename
    _check_hash(st, expected_hash)
    name = secure_filename(filename)
    if not name:
        raise ValueError("Choose a file to attach.")
    dest = os.path.join(st.folder_path, name)
    if os.path.exists(dest):
        raise ValueError(f"{name} is already attached — rename the file and try again.")
    stream.save(dest)
    records.add_attachment(st.record, name, mimetype)
    _write(store, st)


# ------------------------------------------------------------------ curricula
def curriculum_refs(store: Store, cid):
    """Students whose record explicitly references curriculum `cid`."""
    return [st for st in store.all_students()
            if st.record and st.record["student"].get("curriculum") == cid]


def curriculum_ref_counts(store: Store):
    """{cid: number of students explicitly referencing it} in one roster pass —
    avoids re-scanning all students once per curriculum."""
    counts = {}
    for st in store.all_students():
        cid = st.record and st.record["student"].get("curriculum")
        if cid:
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def create_curriculum(program, start, end, sections, thresholds=None, cid=None):
    from datetime import date
    program = (program or "").strip().upper()
    if not program:
        raise ValueError("Program is required (e.g. BSCS).")
    cid = (cid or f"{program.lower()}-{start}").strip()
    if curriculum.get(cid):
        raise ValueError(f"A curriculum '{cid}' already exists.")
    today = date.today().isoformat()
    cur = {"schema": curriculum.SCHEMA, "id": cid, "program": program,
           "effective_start": start, "effective_end": end or None,
           "sections": sections, "thresholds": thresholds or [],
           "meta": {"created": today, "updated": today, "source": "manual"}}
    curriculum.save(cur)
    return cid


def edit_curriculum_years(cid, start, end):
    """Only the effective year range is editable after creation — program,
    sections and courses are locked (students' checklists depend on them)."""
    from datetime import date
    cur = curriculum.get(cid)
    if not cur:
        raise ValueError(f"No curriculum '{cid}'.")
    cur["effective_start"] = start
    cur["effective_end"] = end or None
    cur.setdefault("meta", {})["updated"] = date.today().isoformat()
    curriculum.save(cur)


def delete_curriculum(store: Store, cid):
    refs = curriculum_refs(store, cid)
    if refs:
        names = ", ".join(st.name for st in refs[:5])
        more = f" (+{len(refs) - 5} more)" if len(refs) > 5 else ""
        raise ValueError(f"Cannot delete: {len(refs)} student record(s) use this "
                         f"curriculum — {names}{more}.")
    if len(curriculum.load_all()) <= 1:
        raise ValueError("Cannot delete the only curriculum.")
    curriculum.delete(cid)
    store.invalidate()


def import_curriculum_xlsx(stream, program, start, end, cid=None):
    program = (program or "").strip().upper()
    if not program:
        raise ValueError("Program is required (e.g. BSCS).")
    cid = (cid or f"{program.lower()}-{start}").strip()
    if curriculum.get(cid):
        raise ValueError(f"A curriculum '{cid}' already exists.")
    cur = curriculum.from_xlsx(stream, cid, program, start, end or None)
    curriculum.save(cur)
    return cid


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
    wanted = set(sids)
    chosen = [st for st in store.all_students() if st.sid in wanted]
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
