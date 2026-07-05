# -*- coding: utf-8 -*-
"""Flask routes for SAAIS. Local single-user app — binds to 127.0.0.1 only."""
import io
import re
from datetime import date, datetime

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, url_for)
from markupsafe import Markup, escape

from . import config as config_mod
from . import service
from .domain import advising, rules
from .index.store import Store
from .repo import curriculum, records, scrape


def mini_md(text):
    """Render the **bold**/`code` subset used in flag strings."""
    out = str(escape(text))
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`(.+?)`", r"<code>\1</code>", out)
    return Markup(out)


def days_until(iso):
    try:
        return (datetime.strptime(iso, "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        return None


def create_app():
    app = Flask(__name__)
    app.secret_key = "saais-local"  # localhost-only, single user; used for flash only
    cfg = config_mod.load()
    store = Store(cfg)
    app.jinja_env.filters["mini_md"] = mini_md
    app.jinja_env.globals.update(
        cfg=cfg, today=lambda: date.today().isoformat(), days_until=days_until,
        cur_labels=curriculum.labels, flag_icon=rules.FLAG_ICON,
        short_term=rules.short_term,
    )

    def get_student_or_404(sid):
        st = store.get(sid)
        if st is None:
            abort(404)
        return st

    def inc_board():
        rows = []
        for st in store.students():
            if not st.an:
                continue
            for code, ay, sem, deadline in st.an["incs"]:
                rows.append({"st": st, "code": code, "term": rules.short_term(ay, sem),
                             "deadline": deadline, "days": days_until(deadline)})
        rows.sort(key=lambda r: r["deadline"])
        return rows

    # ------------------------------------------------------------- pages
    @app.route("/")
    def home():
        students = store.students()
        counts = {"🔴": 0, "🟡": 0, "🟢": 0, "⚪": 0}
        for st in students:
            counts[st.status[:1]] = counts.get(st.status[:1], 0) + 1
        stopouts = [st for st in students
                    if st.an and any(k == "STOPOUT" for k, _ in st.an["flags"])]
        return render_template("home.html", students=students, counts=counts,
                               incs=inc_board(), stopouts=stopouts)

    @app.route("/roster")
    def roster():
        students = store.students()
        f_status = request.args.get("status", "")
        f_cur = request.args.get("cur", "")
        f_year = request.args.get("year", "")
        years = sorted({st.an["year_level"] for st in students if st.an})
        rows = [st for st in students
                if (not f_status or st.status.startswith(f_status))
                and (not f_cur or (st.an and st.an["curkey"] == f_cur))
                and (not f_year or (st.an and st.an["year_level"] == f_year))]
        sort = request.args.get("sort", "name")
        keyers = {
            "name": lambda s: rules.strip_accents(s.name).upper(),
            "gwa": lambda s: s.an["gwa"] if s.an and s.an["gwa"] else 99,
            "units": lambda s: -(s.an["units"] if s.an else -1),
            "flags": lambda s: -(len(s.an["flags"]) if s.an else -1),
            "status": lambda s: {"🔴": 0, "🟡": 1, "🟢": 2}.get(s.status[:1], 3),
        }
        rows.sort(key=keyers.get(sort, keyers["name"]))
        return render_template("roster.html", rows=rows, years=years,
                               f_status=f_status, f_cur=f_cur, f_year=f_year, sort=sort)

    @app.route("/flags")
    def flags_board():
        groups = {"STOPOUT": [], "DELINQ": [], "INC": [], "RETAKE": []}
        for st in store.students():
            if not st.an:
                continue
            for kind, txt in st.an["flags"]:
                groups.setdefault(kind, []).append((st, txt))
        return render_template("flags.html", groups=groups)

    @app.route("/student/<sid>")
    def student(sid):
        st = get_student_or_404(sid)
        history = []
        if st.an:
            for (ay, sem), recs in sorted(st.an["per_term"].items(),
                                          key=lambda kv: rules.term_key(*kv[0])):
                num = den = 0.0
                for g in recs:
                    _, val, _ = rules.effective(g)
                    if val is not None:
                        num += val * g["units"]
                        den += g["units"]
                history.append({
                    "label": rules.short_term(ay, sem), "recs": recs,
                    "units": sum(g["units"] for g in recs),
                    "gwa": (num / den) if den else None,
                })
        return render_template("student.html", st=st, history=history,
                               row_status=lambda item: rules.row_status(item, st.an["passed"]) if st.an else None)

    # ------------------------------------------------------------- writes
    @app.post("/student/<sid>/note")
    def add_note(sid):
        st = get_student_or_404(sid)
        try:
            service.add_note(store, st, request.form["note"],
                             expected_hash=request.form.get("rec_hash"),
                             when=request.form.get("date") or None)
            flash("Note added.")
        except (service.Conflict, ValueError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid) + "#notes")

    @app.post("/student/<sid>/profile")
    def edit_profile(sid):
        st = get_student_or_404(sid)
        try:
            service.edit_profile(store, st, request.form.get("email", ""),
                                 request.form.get("contact", ""),
                                 request.form.get("curriculum") or None,
                                 expected_hash=request.form.get("rec_hash"))
            flash("Profile updated.")
        except (service.Conflict, ValueError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid))

    @app.route("/student/<sid>/grades", methods=["GET", "POST"])
    def encode_grades(sid):
        st = get_student_or_404(sid)
        if not st.an:
            flash("⚠ No grade entries — import a scrape first.")
            return redirect(url_for("student", sid=sid))
        if request.method == "POST":
            form = request.form
            updates = []
            for i in range(int(form.get("nrows", 0))):
                if not form.get(f"code{i}"):
                    continue
                updates.append({
                    "academic_year": form[f"ay{i}"], "semester": form[f"sem{i}"],
                    "course_code": form[f"code{i}"], "course_title": form.get(f"title{i}", ""),
                    "units": form.get(f"units{i}", ""), "midterm": form.get(f"mid{i}", ""),
                    "grade": form.get(f"grade{i}", ""), "completion": form.get(f"comp{i}", ""),
                })
            try:
                n = service.encode_grades(store, st, updates,
                                          expected_hash=form.get("rec_hash"))
                flash(f"{n} record(s) updated." if n else "No changes.")
                return redirect(url_for("student", sid=sid))
            except (service.Conflict, ValueError, records.RecordError) as e:
                flash(f"⚠ {e}")
        # rows to offer: current-term in-progress + outstanding INCs
        cur_term = (cfg["term"]["current_ay"], cfg["term"]["current_sem"])
        rows = [g for g in st.an["in_progress"]]
        inc_codes = {(c, ay, sem) for c, ay, sem, _ in st.an["incs"]}
        for g in st.record["grades"]:
            if (g["course_code"], g["academic_year"], g["semester"]) in inc_codes:
                rows.append(g)
        return render_template("grades.html", st=st, rows=rows, cur_term=cur_term)

    @app.route("/student/<sid>/advise", methods=["GET", "POST"])
    def advise(sid):
        st = get_student_or_404(sid)
        if not st.an:
            flash("⚠ No grade entries — import a scrape first.")
            return redirect(url_for("student", sid=sid))
        options = advising.can_enroll(st.an)
        if request.method == "POST":
            chosen_codes = set(request.form.getlist("enroll"))
            chosen = [o for o in options if o["row"]["code"] in chosen_codes]
            total_units = sum(o["row"]["units"] for o in chosen)
            if request.form.get("save_note"):
                courses = ", ".join(o["row"]["code"] for o in chosen) or "none"
                service.add_note(store, st,
                                 f"Enrollment advising for {request.form.get('term', 'next term')}: "
                                 f"advised {courses} ({total_units:g} units).")
            return render_template("slip.html", st=st, chosen=chosen,
                                   total_units=total_units,
                                   term=request.form.get("term", ""),
                                   max_units=cfg["rules"]["max_units_regular"])
        return render_template("advise.html", st=st, options=options,
                               max_units=cfg["rules"]["max_units_regular"])

    @app.post("/student/<sid>/graduate")
    def graduate(sid):
        st = get_student_or_404(sid)
        try:
            dest = service.graduate(store, st, request.form.get("year", ""))
            flash(f"{st.name} moved to {dest}.")
            return redirect(url_for("home"))
        except (ValueError, OSError) as e:
            flash(f"⚠ {e}")
            return redirect(url_for("student", sid=sid))

    @app.route("/import", methods=["GET", "POST"])
    def import_scrape():
        if request.method == "POST":
            text = request.form.get("json", "")
            f = request.files.get("file")
            if f and f.filename:
                text = f.read().decode("utf-8")
            try:
                sid, st = service.import_scrape(store, text)
                if st:
                    flash(f"Imported scrape for {sid}; merged into {st.folder}'s record.")
                    return redirect(url_for("student", sid=sid))
                flash(f"Imported raw/{sid}.json, but no matching advisee record — "
                      f"use New advisee to scaffold a folder.")
                return redirect(url_for("intake"))
            except (scrape.ScrapeError, ValueError) as e:
                flash(f"⚠ {e}")
        return render_template("import.html", unmatched=store.unmatched_raw())

    @app.route("/intake", methods=["GET", "POST"])
    def intake():
        if request.method == "POST":
            text = request.form.get("json", "")
            f = request.files.get("file")
            if f and f.filename:
                text = f.read().decode("utf-8")
            try:
                sid, folder = service.intake(store, text, request.form.get("folder", ""))
                flash(f"Created students/active/{folder}/ for {sid}.")
                return redirect(url_for("student", sid=sid))
            except (scrape.ScrapeError, ValueError) as e:
                flash(f"⚠ {e}")
        return render_template("intake.html")

    # ------------------------------------------------------------- curricula
    def _parse_course_lines(text, sec_label):
        """One course per line: 'code | title | units | prerequisite'."""
        courses = []
        for ln, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                raise ValueError(f"{sec_label}, line {ln}: expected "
                                 "'code | title | units | prerequisite'.")
            courses.append({"code": parts[0], "title": parts[1], "units": parts[2],
                            "prereq": parts[3] if len(parts) > 3 and parts[3] else "None"})
        return courses

    def _parse_sections(form):
        sections, i = [], 0
        while f"sec{i}_year" in form:
            year, term = form[f"sec{i}_year"], form.get(f"sec{i}_term", "1st")
            text = form.get(f"sec{i}_courses", "")
            i += 1
            if not year.strip() and not text.strip():
                continue  # empty extra block
            sections.append({"year": year, "term": term,
                             "courses": _parse_course_lines(text, f"Section {i}")})
        return sections

    @app.route("/curricula")
    def curricula():
        rows = []
        counts = service.curriculum_ref_counts(store)
        for cid, cur in sorted(curriculum.load_all().items(),
                               key=lambda kv: (kv[1]["program"], kv[1]["effective_start"])):
            rows.append({"cur": cur, "label": curriculum.label(cur),
                         "n_courses": len(cur["courses"]),
                         "units": curriculum.total_units(cur),
                         "n_students": counts.get(cid, 0)})
        return render_template("curricula.html", rows=rows)

    @app.route("/curricula/new", methods=["GET", "POST"])
    def curriculum_new():
        if request.method == "POST":
            try:
                cid = service.create_curriculum(
                    request.form.get("program", ""), request.form.get("start", ""),
                    request.form.get("end", "").strip() or None,
                    _parse_sections(request.form),
                    thresholds=rules.parse_thresholds(request.form.get("thresholds", "")))
                flash(f"Curriculum {cid} created.")
                return redirect(url_for("curricula"))
            except (ValueError, curriculum.CurriculumError) as e:
                flash(f"⚠ {e}")
        return render_template("curriculum_new.html")

    @app.route("/curricula/<cid>/edit", methods=["GET", "POST"])
    def curriculum_edit(cid):
        cur = curriculum.get(cid)
        if not cur:
            abort(404)
        if request.method == "POST":
            try:
                service.edit_curriculum_years(cid, request.form.get("start", ""),
                                              request.form.get("end", "").strip() or None)
                flash(f"Effective years updated for {cid}.")
                return redirect(url_for("curricula"))
            except (ValueError, curriculum.CurriculumError) as e:
                flash(f"⚠ {e}")
        return render_template("curriculum_edit.html", cur=cur,
                               label=curriculum.label(cur),
                               n_students=len(service.curriculum_refs(store, cid)))

    @app.post("/curricula/<cid>/delete")
    def curriculum_delete(cid):
        try:
            service.delete_curriculum(store, cid)
            flash(f"Curriculum {cid} deleted (previous version backed up).")
        except (ValueError, curriculum.CurriculumError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("curricula"))

    @app.post("/curricula/import")
    def curriculum_import():
        f = request.files.get("file")
        if not f or not f.filename:
            flash("⚠ Choose a Course-Checklist .xlsx file to import.")
            return redirect(url_for("curricula"))
        try:
            cid = service.import_curriculum_xlsx(
                f, request.form.get("program", ""), request.form.get("start", ""),
                request.form.get("end", "").strip() or None)
            flash(f"Imported {f.filename} as curriculum {cid}.")
        except (ValueError, curriculum.CurriculumError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("curricula"))

    @app.post("/export-md")
    def export_md():
        sids = request.form.getlist("sids")
        try:
            zip_bytes, names = service.export_md(store, sids,
                                                 out_dir=request.form.get("out_dir") or None)
        except (ValueError, records.RecordError) as e:
            flash(f"⚠ {e}")
            return redirect(url_for("roster"))
        if request.form.get("out_dir"):
            flash(f"Wrote {len(names)} MD file(s) to {request.form['out_dir']}.")
            return redirect(url_for("roster"))
        return send_file(io.BytesIO(zip_bytes), mimetype="application/zip",
                         as_attachment=True,
                         download_name=f"saais-md-export-{date.today().isoformat()}.zip")

    @app.post("/sync-roster")
    def sync_roster():
        path = service.sync_roster(store)
        flash(f"Roster written to {path}.")
        return redirect(url_for("home"))

    return app
