# -*- coding: utf-8 -*-
"""Render the computed parts of a student Markdown file (same layout as the
original generator, so regenerated sections diff cleanly against hand files)."""
from datetime import date

from ..domain import rules
from ..repo.curriculum import CURRICULUM_LABEL

TERM_LABEL = {"1st": "1st Semester", "2nd": "2nd Semester", "Midyear": "Midyear"}


def render(data, info, an, source="registrar scrape"):
    """Full document: preamble + computed sections + a default Advising notes
    section (used only for brand-new files; merge() keeps existing notes).

    info: {"email": ..., "contact": ...} carried over from the existing file.
    """
    s = data["student"]
    sid = s["student_number"]
    name = s["name"].rstrip(" .")
    today = date.today().isoformat()
    cur_label = CURRICULUM_LABEL[an["curkey"]]
    entry_ay = f"20{sid[:2]}-20{int(sid[:2]) + 1}"
    email = info.get("email") or f"{sid}@vsu.edu.ph"
    contact = info.get("contact") or "—"

    L = []
    L.append(f"# {name}")
    L.append("")
    L.append(f"> Status: **{an['status']}** · last updated {today} (from {source} `raw/{sid}.json`)")
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    L.append(f"| Student No. | {sid} |")
    L.append(f"| Program | {s['program']} |")
    L.append(f"| Curriculum | {cur_label} |")
    L.append(f"| Entered | AY {entry_ay} |")
    L.append(f"| Email | {email} |")
    L.append(f"| Contact | {contact} |")
    L.append(f"| Units earned | {an['units']:g} / {an['grad_units']:g} |")
    L.append(f"| Year level (by units) | {an['year_level']} |")
    L.append(f"| GWA (all final numeric grades) | {an['gwa']:.2f} |" if an["gwa"] else "| GWA | — |")
    L.append(f"| Last term with records | {rules.short_term(*an['last_term'])} |")
    L.append("")

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
    L.append("<!-- Hand-maintained. Add newest entries at the top. -->")
    L.append("")
    L.append("| Date | Note |")
    L.append("|---|---|")
    L.append(f"| {today} | File created via SAAIS. |")
    L.append("")
    return "\n".join(L)
