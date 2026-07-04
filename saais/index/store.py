# -*- coding: utf-8 -*-
"""In-memory index over the student records, rebuilt lazily from file mtimes.

Since the v2 data layer the source of truth is students/<status>/…/record.json
(not the Markdown files — those are now an export format). The index is
disposable, always recomputed from files, and picks up hand edits made while
the server runs — with zero extra dependencies.
"""
import os

from ..domain import rules
from ..repo import curriculum, paths, records


class Student:
    def __init__(self, status_dir, folder, folder_path):
        self.status_dir = status_dir               # "active" | "inactive" | "graduated"
        self.folder = folder                       # "Laraga, Keana Samantha"
        self.folder_path = folder_path
        self.record = None                         # validated record dict
        self.rec_hash = None
        self.an = None                             # rules.analyze() output
        self.error = None

    # -------------------------------------------------------------- profile
    @property
    def sid(self):
        return self.record["student"]["student_number"] if self.record else None

    @property
    def name(self):
        return self.record["student"]["name"].rstrip(" .") if self.record else self.folder

    @property
    def status(self):
        """Status light (🔴/🟡/🟢) — computed, never stored."""
        return self.an["status"] if self.an else "⚪ No data"

    @property
    def status_key(self):
        """Lifecycle status: active / inactive / graduated."""
        return self.record["student"]["status"] if self.record else self.status_dir

    @property
    def notes(self):
        return records.notes_newest_first(self.record) if self.record else []

    @property
    def fields(self):
        """Ordered display fields for the profile box — derived, not stored."""
        if not self.record:
            return {}
        s = self.record["student"]
        out = {
            "Student No.": s["student_number"],
            "Program": s["program"],
            "Curriculum": curriculum.labels().get(
                self.an["curkey"] if self.an else s.get("curriculum"),
                s.get("curriculum") or "—"),
            "Entered": f"AY {s['entered']}" if s.get("entered") else "—",
            "Email": s.get("email") or "—",
            "Contact": s.get("contact") or "—",
            "Status": s["status"] + (f" ({s['inactive_reason']})" if s.get("inactive_reason") else "")
                      + (f" ({s['graduated_year']})" if s.get("graduated_year") else ""),
        }
        if self.an:
            an = self.an
            out["Units earned"] = f"{an['units']:g} / {an['grad_units']:g}"
            out["Year level (by units)"] = an["year_level"]
            out["GWA (all final numeric grades)"] = f"{an['gwa']:.2f}" if an["gwa"] else "—"
            out["Last term with records"] = rules.short_term(*an["last_term"])
        return out


class Store:
    def __init__(self, config):
        self.config = config
        self._cache = {}   # folder_path -> (cache_key, Student)

    # ---------------------------------------------------------------- build
    def _build(self, status_dir, folder, folder_path):
        st = Student(status_dir, folder, folder_path)
        try:
            st.record = records.load(folder_path)
        except records.RecordError as e:
            st.error = str(e)
            return st
        if st.record is None:
            st.error = ("no record.json — legacy folder; run "
                        "`python -m saais.migrate` to migrate it")
            return st
        st.rec_hash = records.content_hash(st.record)
        if st.record["grades"]:
            try:
                st.an = rules.analyze(st.record, curriculum.load_all(), self.config,
                                      st.record["student"].get("curriculum"))
            except Exception as e:  # keep the roster usable if one record is odd
                st.error = f"analysis failed: {e}"
        return st

    def _cache_key(self, folder_path):
        rp = paths.record_path(folder_path)
        return (os.path.getmtime(rp) if os.path.exists(rp) else None,
                curriculum.cache_token())

    def invalidate(self, st=None):
        if st is None:
            self._cache.clear()
        else:
            self._cache.pop(st.folder_path, None)

    # ---------------------------------------------------------------- API
    def all_students(self):
        """Every advisee across active/inactive/graduated, name-sorted;
        lazily rebuilt where files changed."""
        out = []
        seen = set()
        for status_dir, folder, fp in paths.student_dirs():
            key = self._cache_key(fp)
            cached = self._cache.get(fp)
            if cached is None or cached[0] != key:
                self._cache[fp] = (key, self._build(status_dir, folder, fp))
            out.append(self._cache[fp][1])
            seen.add(fp)
        for fp in list(self._cache):
            if fp not in seen:
                del self._cache[fp]  # folder moved/removed
        return sorted(out, key=lambda s: rules.strip_accents(s.name).upper())

    def students(self, status="active"):
        """Advisees with the given lifecycle status (default: active)."""
        return [st for st in self.all_students()
                if status is None or st.status_key == status]

    def get(self, sid):
        for st in self.all_students():
            if st.sid == sid:
                return st
        return None

    def by_folder(self, folder_path):
        for st in self.all_students():
            if st.folder_path == folder_path:
                return st
        return None

    def unmatched_raw(self):
        """raw/*.json scrape files with no matching student record."""
        have = {st.sid for st in self.all_students() if st.sid}
        out = []
        if os.path.isdir(paths.RAW_DIR):
            for f in sorted(os.listdir(paths.RAW_DIR)):
                if f.endswith(".json") and f[:-5] not in have:
                    out.append(f[:-5])
        return out
