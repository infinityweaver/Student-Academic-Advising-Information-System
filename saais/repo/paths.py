# -*- coding: utf-8 -*-
"""Canonical locations of the repo files SAAIS reads and writes."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACTIVE_DIR = os.path.join(ROOT, "students", "active")
GRADUATED_DIR = os.path.join(ROOT, "students", "graduated")
INACTIVE_DIR = os.path.join(ROOT, "students", "inactive")
RAW_DIR = os.path.join(ROOT, "raw")
CURRICULUM_DIR = os.path.join(ROOT, "reference", "curriculum")
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
