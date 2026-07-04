# -*- coding: utf-8 -*-
"""Raw registrar scrapes (raw/<student-no>.json): load, validate, save, merge."""
import json
import os

from . import paths

REQUIRED_STUDENT = ("student_number", "name", "program")
REQUIRED_GRADE = ("academic_year", "semester", "course_code", "course_title", "units")
GRADE_DEFAULTS = {"midterm": None, "grade": None, "completion": None}


class ScrapeError(ValueError):
    """Raised when a scrape does not match the expected schema — fail loudly."""


def validate(data):
    if not isinstance(data, dict) or "student" not in data or "grades" not in data:
        raise ScrapeError("Scrape must be an object with 'student' and 'grades' keys.")
    s = data["student"]
    for k in REQUIRED_STUDENT:
        if not s.get(k):
            raise ScrapeError(f"student.{k} is missing or empty.")
    if not isinstance(data["grades"], list) or not data["grades"]:
        raise ScrapeError("'grades' must be a non-empty list.")
    for i, g in enumerate(data["grades"]):
        for k in REQUIRED_GRADE:
            if g.get(k) in (None, ""):
                raise ScrapeError(f"grades[{i}].{k} is missing or empty ({g.get('course_code', '?')}).")
        try:
            g["units"] = float(g["units"])
        except (TypeError, ValueError):
            raise ScrapeError(f"grades[{i}].units is not a number.")
        for k, v in GRADE_DEFAULTS.items():
            g.setdefault(k, v)
    return data


def load(sid):
    path = paths.raw_path(sid)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return validate(json.load(fh))


def parse_text(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ScrapeError(f"Not valid JSON: {e}")
    return validate(data)


def save(data):
    validate(data)
    sid = data["student"]["student_number"]
    path = paths.raw_path(sid)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def find_record(data, ay, sem, course_code):
    for g in data["grades"]:
        if (g["academic_year"], g["semester"], g["course_code"]) == (ay, sem, course_code):
            return g
    return None
