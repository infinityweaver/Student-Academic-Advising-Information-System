# -*- coding: utf-8 -*-
"""Enrollment advising: prerequisite evaluation over the curriculum checklist."""
import re

from . import rules

CODE_RE = re.compile(r"^[A-Za-z]{2,5}\s?\d{2,3}(\.\d+)?[a-z]?$")


def parse_prereq(prereq):
    """-> (course_codes, other_requirements). 'CSci 14, CSci 102' -> codes;
    non-course text ('3rd year standing', 'COI') -> other (manual check)."""
    prereq = (prereq or "").strip()
    if not prereq or prereq.lower() in ("none", "n/a", "-", "—"):
        return [], []
    codes, other = [], []
    for tok in re.split(r"[,;/]| and ", prereq):
        tok = tok.strip()
        if not tok:
            continue
        if CODE_RE.match(tok):
            codes.append(tok)
        else:
            other.append(tok)
    return codes, other


def can_enroll(an):
    """Per unpassed checklist course: eligibility from passed prereqs.

    -> list of {"row", "eligible", "missing", "manual", "in_progress", "attempted"}
    """
    passed = an["passed"]
    in_progress_codes = {rules.base_code(g["course_code"]) for g in an["in_progress"]}
    out = []
    for item in an["checklist"]:
        row = item["row"]
        bc = rules.base_code(row["code"])
        if bc in passed:
            continue
        codes, other = parse_prereq(row["prereq"])
        missing = [c for c in codes if rules.base_code(c) not in passed]
        entry = {
            "row": row,
            "eligible": not missing,
            "missing": missing,
            "manual": other,
            "in_progress": bc in in_progress_codes,
            "attempted": bool(item["recs"]),
        }
        out.append(entry)
    return out
