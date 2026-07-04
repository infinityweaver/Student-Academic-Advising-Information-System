# -*- coding: utf-8 -*-
"""In-memory index over the repo files, rebuilt lazily from file mtimes.

The plan sketched a SQLite cache + watchdog; at this scale (~30 students) a
per-request mtime check gives the same guarantees — the index is disposable,
always recomputed from files, and picks up hand edits made while the server
runs — with zero extra dependencies. Deleting nothing is ever needed.
"""
import os

from ..domain import rules
from ..repo import curriculum, md_doc, paths, scrape


class Student:
    def __init__(self, folder):
        self.folder = folder                       # "Laraga, Keana Samantha"
        self.folder_path = os.path.join(paths.ACTIVE_DIR, folder)
        self.md_path = None
        self.md_text = None
        self.md_hash = None
        self.fields = {}                           # header table key -> value
        self.notes = []
        self.sid = None
        self.name = folder
        self.raw = None                            # validated scrape dict
        self.raw_path = None
        self.an = None                             # rules.analyze() output
        self.error = None

    @property
    def status(self):
        return self.an["status"] if self.an else "⚪ No data"

    @property
    def curriculum_label(self):
        return self.fields.get("Curriculum", "")


class Store:
    def __init__(self, config):
        self.config = config
        self._cache = {}   # folder -> (cache_key, Student)

    # ---------------------------------------------------------------- build
    def _find_md(self, folder_path, folder):
        conventional = os.path.join(folder_path, folder.upper() + ".md")
        if os.path.exists(conventional):
            return conventional
        mds = [f for f in os.listdir(folder_path) if f.lower().endswith(".md")]
        return os.path.join(folder_path, mds[0]) if mds else None

    def _build(self, folder):
        st = Student(folder)
        st.md_path = self._find_md(st.folder_path, folder)
        if st.md_path:
            with open(st.md_path, encoding="utf-8") as fh:
                st.md_text = fh.read()
            st.md_hash = md_doc.content_hash(st.md_text)
            doc = md_doc.parse(st.md_text)
            st.fields = md_doc.header_fields(doc["preamble"])
            st.notes = md_doc.parse_notes(st.md_text)
            st.sid = st.fields.get("Student No.")
            first = st.md_text.splitlines()[0] if st.md_text else ""
            if first.startswith("# "):
                st.name = first[2:].strip()
        if st.sid:
            try:
                st.raw = scrape.load(st.sid)
            except scrape.ScrapeError as e:
                st.error = str(e)
            if st.raw:
                st.raw_path = paths.raw_path(st.sid)
                st.name = st.raw["student"]["name"].rstrip(" .")
                curkey = curriculum.key_from_label(st.curriculum_label)
                try:
                    st.an = rules.analyze(st.raw, curriculum.load_all(), self.config, curkey)
                except Exception as e:  # keep the roster usable if one file is odd
                    st.error = f"analysis failed: {e}"
        return st

    def _cache_key(self, folder):
        fp = os.path.join(paths.ACTIVE_DIR, folder)
        parts = []
        md = self._find_md(fp, folder)
        parts.append(os.path.getmtime(md) if md and os.path.exists(md) else None)
        sid = None
        if md:
            # cheap sid sniff without full parse: filename-independent, so read header
            try:
                with open(md, encoding="utf-8") as fh:
                    head = fh.read(2000)
                for line in head.splitlines():
                    if line.startswith("| Student No."):
                        sid = line.split("|")[2].strip()
                        break
            except OSError:
                pass
        rp = paths.raw_path(sid) if sid else None
        parts.append(os.path.getmtime(rp) if rp and os.path.exists(rp) else None)
        for cp in paths.CURRICULA.values():
            parts.append(os.path.getmtime(cp))
        return tuple(parts)

    # ---------------------------------------------------------------- API
    def students(self):
        """All active advisees, name-sorted; lazily rebuilt where files changed."""
        out = []
        seen = set()
        if os.path.isdir(paths.ACTIVE_DIR):
            for folder in sorted(os.listdir(paths.ACTIVE_DIR)):
                fp = os.path.join(paths.ACTIVE_DIR, folder)
                if not os.path.isdir(fp):
                    continue
                key = self._cache_key(folder)
                cached = self._cache.get(folder)
                if cached is None or cached[0] != key:
                    self._cache[folder] = (key, self._build(folder))
                st = self._cache[folder][1]
                out.append(st)
                seen.add(folder)
        for folder in list(self._cache):
            if folder not in seen:
                del self._cache[folder]  # folder moved/removed
        return sorted(out, key=lambda s: rules.strip_accents(s.name).upper())

    def get(self, sid):
        for st in self.students():
            if st.sid == sid:
                return st
        return None

    def by_folder(self, folder):
        for st in self.students():
            if st.folder == folder:
                return st
        return None

    def unmatched_raw(self):
        """raw/*.json files with no active student folder (e.g. graduated)."""
        have = {st.sid for st in self.students() if st.sid}
        out = []
        if os.path.isdir(paths.RAW_DIR):
            for f in sorted(os.listdir(paths.RAW_DIR)):
                if f.endswith(".json") and f[:-5] not in have:
                    out.append(f[:-5])
        return out
