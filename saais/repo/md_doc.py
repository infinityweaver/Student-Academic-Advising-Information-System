# -*- coding: utf-8 -*-
"""Round-trip parser/writer for student Markdown files.

A student file is an ordered list of sections keyed by `## ` heading, plus a
preamble (title, status line, header table). Computed sections are replaced
wholesale on update; every other section — Advising notes and anything the
adviser adds by hand — is preserved byte-for-byte.
"""
import hashlib
import re

# Sections SAAIS owns (regenerated from raw data). Matched by heading prefix
# because some titles are dynamic ("Currently enrolled — no final grade yet (...)").
COMPUTED_PREFIXES = (
    "Flags",
    "Currently enrolled",
    "Curriculum checklist",
    "Other courses taken",
    "Grade history by term",
)

NOTES_TITLE = "Advising notes"


def parse(text):
    """-> {"preamble": str, "sections": [{"title": str, "text": str}]}
    Section text includes its `## ` heading line. Concatenating preamble +
    all section texts reproduces the input exactly."""
    lines = text.splitlines(keepends=True)
    sections = []
    preamble = []
    current = None
    for line in lines:
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "text": line}
            sections.append(current)
        elif current is not None:
            current["text"] += line
        else:
            preamble.append(line)
    return {"preamble": "".join(preamble), "sections": sections}


def is_computed(title):
    return any(title.startswith(p) for p in COMPUTED_PREFIXES)


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def header_fields(preamble):
    """Key -> value from the two-column header table in the preamble."""
    fields = {}
    for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$", preamble, re.M):
        key = m.group(1).strip()
        if key and not set(key) <= {"-", " "}:
            fields[key] = m.group(2).strip()
    return fields


def merge(fresh_text, old_text):
    """Combine freshly rendered computed content with the preserved sections of
    the existing file. `fresh_text` = preamble + computed sections (+ a default
    notes section used only when the old file has none)."""
    fresh = parse(fresh_text)
    old = parse(old_text)
    out = [fresh["preamble"]]
    out += [s["text"] for s in fresh["sections"] if is_computed(s["title"])]
    preserved = [s for s in old["sections"] if not is_computed(s["title"])]
    if preserved:
        out += [s["text"] for s in preserved]
    else:
        out += [s["text"] for s in fresh["sections"] if not is_computed(s["title"])]
    return "".join(out)


def parse_notes(text):
    """[(date, note)] rows of the Advising notes table, newest first (file order)."""
    doc = parse(text)
    for s in doc["sections"]:
        if s["title"] == NOTES_TITLE:
            rows = []
            for m in re.finditer(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", s["text"], re.M):
                a, b = m.group(1), m.group(2)
                if a in ("Date", "") and b in ("Note", ""):
                    continue
                if set(a) <= {"-", " ", ":"}:
                    continue
                rows.append((a, b))
            return rows
    return []


def add_note(text, date, note):
    """Insert a new top row in the Advising notes table; creates the section if
    missing. Returns the new document text."""
    note = " ".join(note.split()).replace("|", "\\|")
    doc = parse(text)
    for s in doc["sections"]:
        if s["title"] == NOTES_TITLE:
            lines = s["text"].splitlines(keepends=True)
            for i, line in enumerate(lines):
                if re.match(r"^\|[\s\-:|]+\|\s*$", line):  # the |---|---| separator
                    lines.insert(i + 1, f"| {date} | {note} |\n")
                    s["text"] = "".join(lines)
                    return doc["preamble"] + "".join(sec["text"] for sec in doc["sections"])
            # section exists but has no table — append one
            s["text"] = s["text"].rstrip("\n") + (
                f"\n\n| Date | Note |\n|---|---|\n| {date} | {note} |\n")
            return doc["preamble"] + "".join(sec["text"] for sec in doc["sections"])
    # no notes section at all — append one at the end
    tail = (f"## {NOTES_TITLE}\n\n<!-- Hand-maintained. Add newest entries at the top. -->\n\n"
            f"| Date | Note |\n|---|---|\n| {date} | {note} |\n")
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n" + tail
