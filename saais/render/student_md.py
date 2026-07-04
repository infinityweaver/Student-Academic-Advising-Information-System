# -*- coding: utf-8 -*-
"""Render a student's advising Markdown from their JSON record (same layout as
the v1 files, so exports diff cleanly against the legacy documents).

Since the v2 data layer MD is an export format generated on demand — it is
never parsed back; record.json is the source of truth."""
from datetime import date

from ..domain import rules
from ..repo import records
from ..repo.curriculum import CURRICULUM_LABEL

TERM_LABEL = {"1st": "1st Semester", "2nd": "2nd Semester", "Midyear": "Midyear"}


def render(rec, an, source="record"):
    """Full document from a record + its rules.analyze() output (an may be
    None when the student has no grade entries yet)."""
    s = rec["student"]
    sid = s["student_number"]
    name = s["name"].rstrip(" .")
    today = date.today().isoformat()
    status = an["status"] if an else "⚪ No data"

    L = []
    L.append(f"# {name}")
    L.append("")
    L.append(f"> Status: **{status}** · exported {today} (generated from {source} — do not hand-edit; "
             "the JSON record is the source of truth)")
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    L.append(f"| Student No. | {sid} |")
    L.append(f"| Program | {s['program']} |")
    if an:
        L.append(f"| Curriculum | {CURRICULUM_LABEL.get(an['curkey'], an['curkey'])} |")
    elif s.get("curriculum"):
        L.append(f"| Curriculum | {CURRICULUM_LABEL.get(s['curriculum'], s['curriculum'])} |")
    L.append(f"| Entered | {('AY ' + s['entered']) if s.get('entered') else '—'} |")
    L.append(f"| Email | {s.get('email') or '—'} |")
    L.append(f"| Contact | {s.get('contact') or '—'} |")
    L.append(f"| Status | {s['status']}"
             + (f" ({s['inactive_reason']})" if s.get("inactive_reason") else "")
             + (f" ({s['graduated_year']})" if s.get("graduated_year") else "") + " |")
    if an:
        L.append(f"| Units earned | {an['units']:g} / {an['grad_units']:g} |")
        L.append(f"| Year level (by units) | {an['year_level']} |")
        L.append(f"| GWA (all final numeric grades) | {an['gwa']:.2f} |" if an["gwa"] else "| GWA | — |")
        L.append(f"| Last term with records | {rules.short_term(*an['last_term'])} |")
    L.append("")

    if an:
        L.append("## Flags")
        L.append("")
        if an["flags"]:
            for k, txt in sorted(an["flags"], key=lambda f: rules.FLAG_ORDER.get(f[0], 9)):
                L.append(f"- {rules.FLAG_ICON[k]} {txt}")
        else:
            L.append("- None 🎉")
        L.append("")

        if an["in_progress"]:
            L.append(f"## Currently enrolled — no final grade yet ({rules.short_term(*an['latest_term'])})")
            L.append("")
            for g in an["in_progress"]:
                mt = f" (midterm {g['midterm']})" if g.get("midterm") else ""
                L.append(f"- {g['course_code']} — {g['course_title'].title()}{mt}")
            L.append("")

        L.append("## Curriculum checklist")
        L.append("")
        L.append("Grade rules: 1.00 best – 3.00 pass; 5.00 fail; INC must be completed within 1 year; DR = dropped.")
        L.append("")
        cur_year = cur_term = None
        for item in an["checklist"]:
            r = item["row"]
            if (r["year"], r["term"]) != (cur_year, cur_term):
                if cur_year is not None:
                    L.append("")
                cur_year, cur_term = r["year"], r["term"]
                L.append(f"### Year {cur_year} — {TERM_LABEL.get(cur_term, cur_term)}")
                L.append("")
                L.append("| Course | Title | Units | Prerequisite | Status | Grade · When | Prior attempts |")
                L.append("|---|---|---|---|---|---|---|")
            st, gw, hist = rules.row_status(item, an["passed"])
            L.append(f"| {r['code']} | {r['title']} | {r['units']:g} | {r['prereq']} | {st} | {gw} | {hist} |")
        L.append("")

        if an["extra"]:
            L.append("## Other courses taken (not matched to checklist)")
            L.append("")
            L.append("| Course | Title | Units | Grade | When |")
            L.append("|---|---|---|---|---|")
            for g in sorted(an["extra"], key=lambda r: rules.term_key(r["academic_year"], r["semester"])):
                _, _, disp = rules.effective(g)
                L.append(f"| {g['course_code']} | {g['course_title'].title()} | {g['units']:g} | {disp} | {rules.short_term(g['academic_year'], g['semester'])} |")
            L.append("")

        L.append("## Grade history by term")
        L.append("")
        for (ay, sem), recs in sorted(an["per_term"].items(), key=lambda kv: rules.term_key(*kv[0])):
            num = den = 0.0
            for g in recs:
                _, val, _ = rules.effective(g)
                if val is not None:
                    num += val * g["units"]
                    den += g["units"]
            twa = f" · term GWA {num / den:.2f}" if den else ""
            tot = sum(g["units"] for g in recs)
            L.append(f"### {rules.short_term(ay, sem)} — {tot:g} units{twa}")
            L.append("")
            L.append("| Course | Title | Units | Midterm | Final | Completion |")
            L.append("|---|---|---|---|---|---|")
            for g in recs:
                L.append(f"| {g['course_code']} | {g['course_title'].title()} | {g['units']:g} |"
                         f" {g['midterm'] or '—'} | {g['grade'] or '—'} | {g['completion'] or '—'} |")
            L.append("")

    L.append("## Advising notes")
    L.append("")
    L.append("| Date | Note |")
    L.append("|---|---|")
    notes = records.notes_newest_first(rec)
    if notes:
        for n in notes:
            L.append(f"| {n['date']} | {n['text'].replace('|', chr(92) + '|')} |")
    else:
        L.append("| — | No notes yet. |")
    L.append("")
    return "\n".join(L)
