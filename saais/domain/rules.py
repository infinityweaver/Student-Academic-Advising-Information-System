# -*- coding: utf-8 -*-
"""Grading and flag rules — extracted from tools/generate_student_md.py (M0).

All aggregates (units earned, GWA, year level, flags, status) are recomputed
from the raw grade records on every call; nothing here is stored as truth.
"""
import re
import unicodedata
from collections import defaultdict

SEM_ORDER = {"First Semester": 1, "Second Semester": 2, "Summer": 3, "Mid Year": 3, "Midyear": 3}

FLAG_ORDER = {"STOPOUT": 0, "DELINQ": 1, "INC": 2, "RETAKE": 3}
FLAG_ICON = {"RETAKE": "❌", "INC": "⏳", "DELINQ": "📉", "STOPOUT": "🚪"}


def term_key(ay, sem):
    return (ay, SEM_ORDER.get(sem, 9))


def short_term(ay, sem):
    s = {"First Semester": "1st Sem", "Second Semester": "2nd Sem", "Summer": "Summer",
         "Mid Year": "Midyear", "Midyear": "Midyear"}.get(sem, sem)
    return f"{s} {ay}"


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_code(code):
    return re.sub(r"\s+", " ", code.strip()).upper()


def base_code(code):
    # drop single trailing section-variant letter: "PhEd 11c" -> "PHED 11"
    return re.sub(r"(\d)[A-Z]$", r"\1", norm_code(code))


def grade_kind(g):
    g = (g or "").strip()
    if g == "":
        return "none"
    if g == "INC":
        return "inc"
    if g in ("DR", "DRP"):
        return "dr"
    if g == "S":
        return "s"
    if g == "NA":
        return "na"
    try:
        float(g)
        return "num"
    except ValueError:
        return "other"


def effective(rec, pass_threshold=3.0):
    """Effective outcome of one enrollment: (passed, numeric_grade_or_None, display)."""
    kind = grade_kind(rec["grade"])
    if kind == "inc":
        comp = (rec["completion"] or "").strip()
        if comp:
            try:
                v = float(comp)
                return (v <= pass_threshold, v, f"INC → {comp}")
            except ValueError:
                return (False, None, f"INC ({comp})")
        return (False, None, "INC (outstanding)")
    if kind == "num":
        v = float(rec["grade"])
        return (v <= pass_threshold, v, rec["grade"])
    if kind == "s":
        return (True, None, "S")
    if kind == "dr":
        return (False, None, "DR")
    if kind == "na":
        return (False, None, "NA")
    if kind == "none":
        return (False, None, "—")
    return (False, None, rec["grade"])


def year_level(units, thresholds):
    label = thresholds[0][1]
    for u, lab in thresholds:
        if units >= u:
            label = lab
    return label


def parse_thresholds(spec):
    """'0=1st year;36=2nd year' -> [(0.0, '1st year'), (36.0, '2nd year')].
    Empty/invalid spec -> [] (caller falls back to curriculum thresholds)."""
    out = []
    for part in (spec or "").split(";"):
        if "=" not in part:
            continue
        units, _, label = part.partition("=")
        try:
            out.append((float(units.strip()), label.strip()))
        except ValueError:
            return []
    return sorted(out)


def detect_curriculum(grades):
    return "2025" if any(norm_code(g["course_code"]).startswith("CSIT") for g in grades) else "2018"


def inc_deadline(ay, sem, inc_years=1):
    """Approximate completion deadline for an INC: end of the term it was
    incurred in, plus `inc_years`. Term-end approximations: 1st Sem → Dec of
    the AY's first year; 2nd Sem → Jun of the second; Summer/Midyear → Aug."""
    y1, y2 = int(ay[:4]), int(ay[5:9])
    month = {1: 12, 2: 6, 3: 8}.get(SEM_ORDER.get(sem, 2), 6)
    year = y1 if month == 12 else y2
    return f"{year + inc_years:04d}-{month:02d}-30"


def analyze(data, curriculum, config, curkey=None):
    """Full per-student computation from a raw scrape dict.

    curriculum: dict key -> {"courses": [...], "thresholds": [...]}
    curkey: explicit curriculum override (per-student field); autodetected if None.
    """
    rules = config["rules"]
    passth = float(rules["pass_threshold"])
    latest_term = (config["term"]["current_ay"], config["term"]["current_sem"])

    grades = data["grades"]
    if curkey not in curriculum:
        curkey = detect_curriculum(grades)
    if curkey not in curriculum:
        if not curriculum:
            raise ValueError("No curricula defined — add or import one first.")
        curkey = next(iter(curriculum))
    cur = curriculum[curkey]

    # group attempts per base code, chronological
    attempts = defaultdict(list)
    for g in sorted(grades, key=lambda r: term_key(r["academic_year"], r["semester"])):
        attempts[base_code(g["course_code"])].append(g)

    # match curriculum rows -> attempts (duplicate codes e.g. CSci 200 matched in order)
    used = defaultdict(int)
    dup_codes = defaultdict(list)
    for row in cur["courses"]:
        dup_codes[base_code(row["code"])].append(row)

    matched_recs = set()
    checklist = []
    for row in cur["courses"]:
        bc = base_code(row["code"])
        recs = attempts.get(bc, [])
        if len(dup_codes[bc]) > 1 and recs:
            recs = [r for r in recs if abs(r["units"] - row["units"]) < 0.01] or recs
            i = used[bc]
            recs = recs[i:i + 1]
            used[bc] += 1
        for r in recs:
            matched_recs.add(id(r))
        checklist.append({"row": row, "recs": recs})

    extra = [g for g in grades if id(g) not in matched_recs]

    # ---- aggregates ----
    passed_codes = set()
    units_earned = 0.0
    gwa_num = gwa_den = 0.0
    per_term = defaultdict(list)
    for g in grades:
        per_term[(g["academic_year"], g["semester"])].append(g)
        ok, val, _ = effective(g, passth)
        if val is not None:
            gwa_num += val * g["units"]
            gwa_den += g["units"]
    for code, recs in attempts.items():
        best = None
        for r in recs:
            ok, val, _ = effective(r, passth)
            if ok:
                best = r
        if best is not None:
            passed_codes.add(code)
            units_earned += best["units"]
    gwa = gwa_num / gwa_den if gwa_den else None

    # ---- flags ----
    flags = []
    incs = []  # (course_code, ay, sem, deadline) for the INC tracker
    for item in checklist:
        recs = item["recs"]
        if not recs:
            continue
        bc = base_code(item["row"]["code"])
        if bc in passed_codes:
            continue
        last = recs[-1]
        kind = grade_kind(last["grade"])
        if kind == "none":
            continue  # still in progress
        if kind == "inc" and not (last["completion"] or "").strip():
            flags.append(("INC", f"**{last['course_code']}** — INC from {short_term(last['academic_year'], last['semester'])};"
                                 f" must be completed within 1 year or it lapses to 5.00"))
            incs.append((last["course_code"], last["academic_year"], last["semester"],
                         inc_deadline(last["academic_year"], last["semester"], int(rules["inc_years"]))))
        elif kind in ("num", "dr", "na"):
            _, val, disp = effective(last, passth)
            flags.append(("RETAKE", f"**{last['course_code']}** {item['row']['title']} — {disp} in "
                                    f"{short_term(last['academic_year'], last['semester'])}; retake required"))
    for g in extra:
        ok, val, disp = effective(g, passth)
        kind = grade_kind(g["grade"])
        if kind in ("num", "dr", "na") and not ok and base_code(g["course_code"]) not in passed_codes:
            flags.append(("RETAKE", f"**{g['course_code']}** {g['course_title'].title()} — {disp} in "
                                    f"{short_term(g['academic_year'], g['semester'])}; not in checklist, verify if still required"))
        if kind == "inc" and not (g["completion"] or "").strip():
            flags.append(("INC", f"**{g['course_code']}** — INC from {short_term(g['academic_year'], g['semester'])};"
                                 f" must be completed within 1 year or it lapses to 5.00"))
            incs.append((g["course_code"], g["academic_year"], g["semester"],
                         inc_deadline(g["academic_year"], g["semester"], int(rules["inc_years"]))))

    # delinquency per term (>= delinquency_ratio of enrolled units failed, final grades only)
    delinquent_terms = []
    for (ay, sem), recs in sorted(per_term.items(), key=lambda kv: term_key(*kv[0])):
        tot = sum(r["units"] for r in recs)
        failed = sum(r["units"] for r in recs
                     if grade_kind(r["grade"]) in ("num", "na") and not effective(r, passth)[0]
                     and grade_kind(r["grade"]) != "none")
        if tot and failed / tot >= float(rules["delinquency_ratio"]):
            delinquent_terms.append((ay, sem, failed, tot))
    for ay, sem, f_, t_ in delinquent_terms:
        flags.append(("DELINQ", f"Failed {f_:g}/{t_:g} units in {short_term(ay, sem)} (≥25% — delinquency rule)"))

    # enrollment currency
    last_term = max(per_term.keys(), key=lambda k: term_key(*k))
    enrolled_now = term_key(*last_term) >= term_key(*latest_term)
    if not enrolled_now:
        flags.append(("STOPOUT", f"No enrollment record since {short_term(*last_term)} — verify LOA/returnee status"))
    in_progress = [g for g in per_term.get(latest_term, []) if grade_kind(g["grade"]) == "none"]

    # status light
    recent_delinq = any(term_key(ay, sem) >= term_key(latest_term[0], "First Semester")
                        for ay, sem, _, _ in delinquent_terms)
    n_retakes = sum(1 for k, _ in flags if k == "RETAKE")
    if not enrolled_now or recent_delinq or n_retakes >= int(rules["retakes_needing_attention"]):
        status = "🔴 Needs attention"
    elif flags:
        status = "🟡 Watch"
    else:
        status = "🟢 On track"

    grad_units = cur["thresholds"][-1][0]
    remaining = [item for item in checklist
                 if base_code(item["row"]["code"]) not in passed_codes]
    yl_thresholds = (parse_thresholds(config.get("year_level", {}).get("thresholds", ""))
                     or cur["thresholds"])

    return {
        "curkey": curkey, "cur": cur, "checklist": checklist, "extra": extra,
        "attempts": attempts, "passed": passed_codes, "units": units_earned,
        "gwa": gwa, "flags": flags, "per_term": per_term, "status": status,
        "last_term": last_term, "in_progress": in_progress, "incs": incs,
        "year_level": year_level(units_earned, yl_thresholds),
        "grad_units": grad_units, "remaining": remaining,
        "delinquent_terms": delinquent_terms, "latest_term": latest_term,
    }


def row_status(item, passed_codes, pass_threshold=3.0):
    """Checklist row rendering: (status label, 'grade · when', prior attempts)."""
    recs = item["recs"]
    if not recs:
        return ("⬜ Not taken", "", "")
    bc = base_code(item["row"]["code"])
    last = recs[-1]
    when = short_term(last["academic_year"], last["semester"])
    hist = "; ".join(f"{effective(r, pass_threshold)[2]} ({short_term(r['academic_year'], r['semester'])})" for r in recs[:-1])
    ok, val, disp = effective(last, pass_threshold)
    kind = grade_kind(last["grade"])
    if bc in passed_codes and ok:
        st = "✅ Passed"
    elif bc in passed_codes:
        st = "✅ Passed"  # passed on a different attempt/row with the same code
        ok2 = [r for r in recs if effective(r, pass_threshold)[0]]
        if ok2:
            last = ok2[-1]
            _, _, disp = effective(last, pass_threshold)
            when = short_term(last["academic_year"], last["semester"])
    elif kind == "none":
        st = "✳️ In progress"
        disp = f"midterm {last['midterm']}" if last.get("midterm") else "—"
    elif kind == "inc" and not (last["completion"] or "").strip():
        st = "⏳ INC"
    else:
        st = "❌ Failed" if kind in ("num", "na") else "❌ Dropped"
    return (st, f"{disp} · {when}", hist)
