# -*- coding: utf-8 -*-
"""Read-only loader for the BSCS curriculum workbooks (cached by mtime)."""
import os
import re

import openpyxl

from . import paths

_cache = {}  # key -> (mtime, parsed)


def _load(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Student"]
    courses, thresholds = [], []
    year, cur_term = 1, None
    mode = "courses"
    for row in ws.iter_rows(min_row=9, values_only=True):
        a, b, c = row[0], row[1], row[2]
        units = row[5]
        if mode == "courses":
            if c is None or str(c).strip() == "":
                if row[4] and "Current Total Units" in str(row[4]):
                    mode = "between"
                continue
            t = str(a).strip() if a else ""
            if t and t != cur_term:
                if t == "1st" and cur_term in ("2nd", "Midyear"):
                    year += 1
                cur_term = t
            courses.append({
                "code": str(b).strip(), "title": re.sub(r"\s+", " ", str(c)).strip(),
                "units": float(units) if units not in (None, "") else 0.0,
                "prereq": re.sub(r"\s+", " ", str(row[6])).strip() if row[6] else "None",
                "year": year, "term": cur_term,
            })
        else:
            if a is not None and str(a).strip().replace(".", "").isdigit() and b:
                thresholds.append((float(a), str(b).strip()))
    return {"courses": courses, "thresholds": sorted(thresholds)}


def load_all():
    """{'2018': {...}, '2025': {...}} — reparsed only when a workbook changes."""
    out = {}
    for key, path in paths.CURRICULA.items():
        mtime = os.path.getmtime(path)
        cached = _cache.get(key)
        if cached is None or cached[0] != mtime:
            _cache[key] = (mtime, _load(path))
        out[key] = _cache[key][1]
    return out


CURRICULUM_LABEL = {"2018": "2018–2024 (old)", "2025": "2025–present (new)"}


def key_from_label(label):
    """Header-table label -> curriculum key ('2018'/'2025'); None if unrecognized."""
    label = (label or "").strip()
    for key, lab in CURRICULUM_LABEL.items():
        if label == lab or label.startswith(key):
            return key
    return None
