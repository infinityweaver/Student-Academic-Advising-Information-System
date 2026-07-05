# -*- coding: utf-8 -*-
"""Canonical locations of the repo files SAAIS reads and writes."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STUDENTS_DIR = os.path.join(ROOT, "students")
ACTIVE_DIR = os.path.join(STUDENTS_DIR, "active")
GRADUATED_DIR = os.path.join(STUDENTS_DIR, "graduated")
INACTIVE_DIR = os.path.join(STUDENTS_DIR, "inactive")
RAW_DIR = os.path.join(ROOT, "raw")
CURRICULUM_DIR = os.path.join(ROOT, "reference", "curriculum")
CURRICULA_DIR = os.path.join(ROOT, "data", "curricula")
ROSTER_MD = os.path.join(ROOT, "ROSTER.md")
BACKUPS_DIR = os.path.join(ROOT, ".backups")

CURRICULA = {
    "2018": os.path.join(CURRICULUM_DIR, "Course-Checklist-2018-2024.xlsx"),
    "2025": os.path.join(CURRICULUM_DIR, "Course-Checklist-2025-present.xlsx"),
}


def raw_path(sid):
    return os.path.join(RAW_DIR, f"{sid}.json")


def md_path(folder):
    """students/active/<Folder>/<FOLDER>.md — the convention used by the generator."""
    return os.path.join(ACTIVE_DIR, folder, folder.upper() + ".md")


def record_path(folder_path):
    """The student's JSON record — the source of truth since the v2 data layer."""
    return os.path.join(folder_path, "record.json")


def student_dirs():
    """Yield (status, folder_name, folder_path) for every student folder across
    active/, inactive/ and graduated/<year>/."""
    for status, base in (("active", ACTIVE_DIR), ("inactive", INACTIVE_DIR)):
        if os.path.isdir(base):
            for folder in sorted(os.listdir(base)):
                fp = os.path.join(base, folder)
                if os.path.isdir(fp):
                    yield status, folder, fp
    if os.path.isdir(GRADUATED_DIR):
        for year in sorted(os.listdir(GRADUATED_DIR)):
            ydir = os.path.join(GRADUATED_DIR, year)
            if not os.path.isdir(ydir):
                continue
            for folder in sorted(os.listdir(ydir)):
                fp = os.path.join(ydir, folder)
                if os.path.isdir(fp):
                    yield "graduated", folder, fp
