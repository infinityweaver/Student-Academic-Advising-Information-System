# -*- coding: utf-8 -*-
"""Flask routes for SAAIS. Local single-user app — binds to 127.0.0.1 only."""
import csv
import io
import os
import re
from datetime import date, datetime

from flask import (Flask, Response, abort, flash, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
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
        all_students = store.all_students()
        students = [st for st in all_students if st.status_key == "active"]
        counts = {"🔴": 0, "🟡": 0, "🟢": 0, "⚪": 0}
        for st in students:
            counts[st.status[:1]] = counts.get(st.status[:1], 0) + 1
        stopouts = [st for st in students
                    if st.an and any(k == "STOPOUT" for k, _ in st.an["flags"])]

        programs = {}
        for st in all_students:
            if not st.record:
                continue
            prog = st.record["student"]["program"] or "—"
            row = programs.setdefault(prog, {"active": 0, "inactive": 0, "graduated": 0})
            if st.status_key in row:
                row[st.status_key] += 1
        programs = dict(sorted(programs.items()))

        this_year = date.today().year
        recent_grads = [st for st in all_students
                        if st.status_key == "graduated"
                        and st.record and st.record["student"].get("graduated_year")
                        and st.record["student"]["graduated_year"] >= this_year - 3]
        recent_grads.sort(key=lambda s: -(s.record["student"]["graduated_year"]))

        return render_template("home.html", students=students, counts=counts,
                               incs=inc_board(), stopouts=stopouts,
                               programs=programs, recent_grads=recent_grads)

    @app.route("/roster")
    def roster():
        students = store.students()
        f_status = request.args.get("status", "")
        f_cur = request.args.get("cur", "")
        f_year = request.args.get("year", "")
        f_q = request.args.get("q", "").strip().lower()
        years = sorted({st.an["year_level"] for st in students if st.an})
        rows = [st for st in students
                if (not f_status or st.status.startswith(f_status))
                and (not f_cur or (st.an and st.an["curkey"] == f_cur))
                and (not f_year or (st.an and st.an["year_level"] == f_year))
                and (not f_q or f_q in st.name.lower() or f_q in (st.sid or "").lower())]
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
                               f_status=f_status, f_cur=f_cur, f_year=f_year,
                               f_q=f_q, sort=sort)

    @app.route("/flags")
    def flags_board():
        groups = {"STOPOUT": [], "DELINQ": [], "INC": [], "RETAKE": []}
        for st in store.students():
            if not st.an:
                continue
            for kind, txt in st.an["flags"]:
                groups.setdefault(kind, []).append((st, txt))
        return render_template("flags.html", groups=groups)

    @app.route("/reports")
    def reports():
        f_status = request.args.get("status", "")
        f_cur = request.args.get("cur", "")
        f_year = request.args.get("year", "")
        f_flag = request.args.get("flag", "")
        f_gwa_min = request.args.get("gwa_min", "")
        f_gwa_max = request.args.get("gwa_max", "")
        f_from = request.args.get("entered_from", "")
        f_to = request.args.get("entered_to", "")

        def safe_float(s):
            try:
                return float(s) if s else None
            except ValueError:
                return None

        def safe_int(s):
            try:
                return int(s) if s else None
            except ValueError:
                return None

        gwa_min, gwa_max = safe_float(f_gwa_min), safe_float(f_gwa_max)
        from_year, to_year = safe_int(f_from), safe_int(f_to)

        def entered_year(st):
            entered = st.record["student"].get("entered") if st.record else None
            try:
                return int(entered[:4]) if entered else None
            except (TypeError, ValueError):
                return None

        def matches(st):
            if not st.record:
                return False
            if f_status and st.status_key != f_status:
                return False
            if f_cur and (not st.an or st.an["curkey"] != f_cur):
                return False
            if f_year and (not st.an or st.an["year_level"] != f_year):
                return False
            if f_flag and (not st.an or not any(k == f_flag for k, _ in st.an["flags"])):
                return False
            if gwa_min is not None:
                if not st.an or not st.an["gwa"] or st.an["gwa"] < gwa_min:
                    return False
            if gwa_max is not None:
                if not st.an or not st.an["gwa"] or st.an["gwa"] > gwa_max:
                    return False
            ey = entered_year(st)
            if from_year is not None and (ey is None or ey < from_year):
                return False
            if to_year is not None and (ey is None or ey > to_year):
                return False
            return True

        all_students = store.all_students()  # already name-sorted
        rows = [st for st in all_students if matches(st)]
        years = sorted({st.an["year_level"] for st in all_students if st.an})

        if request.args.get("format") == "csv":
            def csv_safe(v):
                """Prefix a leading =/+/-/@ with a tab so spreadsheet apps
                (Excel, Sheets, LibreOffice) never interpret a cell as a
                formula (CSV injection)."""
                s = str(v)
                return "\t" + s if s and s[0] in "=+-@" else s

            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["Name", "Student No.", "Program", "Curriculum", "Status",
                       "Year level", "Units earned", "GWA", "Entered", "Flags"])
            for st in rows:
                w.writerow([csv_safe(v) for v in (
                    st.name, st.sid or "", st.record["student"]["program"],
                    curriculum.labels().get(st.an["curkey"], "") if st.an else "",
                    st.status_key, st.an["year_level"] if st.an else "",
                    f"{st.an['units']:g}" if st.an else "",
                    f"{st.an['gwa']:.2f}" if st.an and st.an["gwa"] else "",
                    st.record["student"].get("entered", ""),
                    "; ".join(k for k, _ in st.an["flags"]) if st.an else "",
                )])
            resp = Response(buf.getvalue(), mimetype="text/csv")
            resp.headers["Content-Disposition"] = (
                f"attachment; filename=saais-report-{date.today().isoformat()}.csv")
            return resp

        return render_template("reports.html", rows=rows, years=years,
                               f_status=f_status, f_cur=f_cur, f_year=f_year,
                               f_flag=f_flag, f_gwa_min=f_gwa_min, f_gwa_max=f_gwa_max,
                               f_from=f_from, f_to=f_to)

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
                               row_status=lambda item: rules.row_status(
                                   item, st.an["passed"],
                                   override=st.record["checklist"].get(item["row"]["code"])
                               ) if st.an else None,
                               checklist_statuses=records.CHECKLIST_STATUSES)

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

    # ------------------------------------------------------------- advisee CRUD
    @app.route("/students/new", methods=["GET", "POST"])
    def student_new():
        if request.method == "POST":
            try:
                sid, folder = service.create_advisee(
                    store, request.form.get("folder", ""), request.form.get("sid", ""),
                    request.form.get("name", ""), request.form.get("program", ""),
                    request.form.get("curriculum") or None, request.form.get("entered", ""),
                    request.form.get("email", ""), request.form.get("contact", ""))
                flash(f"Created students/active/{folder}/ for {sid}.")
                return redirect(url_for("student", sid=sid))
            except ValueError as e:
                flash(f"⚠ {e}")
        return render_template("student_new.html")

    @app.route("/student/<sid>/edit", methods=["GET", "POST"])
    def student_edit(sid):
        st = get_student_or_404(sid)
        if request.method == "POST":
            action = request.form.get("action")
            try:
                if action == "profile":
                    service.edit_advisee(store, st, request.form.get("student_number", ""),
                                        request.form.get("email", ""), request.form.get("contact", ""),
                                        request.form.get("curriculum") or None,
                                        expected_hash=request.form.get("rec_hash"))
                    flash("Advisee updated.")
                elif action == "active":
                    active = request.form.get("active") == "active"
                    service.set_active(store, st, active, request.form.get("reason") or None,
                                      expected_hash=request.form.get("rec_hash"))
                    flash("Status updated.")
                elif action == "graduated":
                    if request.form.get("graduated") == "yes":
                        service.graduate(store, st, request.form.get("year", ""))
                        flash(f"{st.name} marked graduated.")
                        return redirect(url_for("roster"))
                    service.ungraduate(store, st, expected_hash=request.form.get("rec_hash"))
                    flash(f"{st.name} reinstated as active.")
                return redirect(url_for("student_edit", sid=sid))
            except (service.Conflict, ValueError) as e:
                flash(f"⚠ {e}")
                return redirect(url_for("student_edit", sid=sid))
        return render_template("student_edit.html", st=st, reasons=records.INACTIVE_REASONS)

    @app.post("/student/<sid>/delete")
    def student_delete(sid):
        st = get_student_or_404(sid)
        name = st.name
        try:
            service.delete_advisee(store, st)
            flash(f"{name} deleted (a full backup was kept under .backups/).")
        except OSError as e:
            flash(f"⚠ {e}")
            return redirect(url_for("student_edit", sid=sid))
        return redirect(url_for("roster"))

    # ------------------------------------------------------------- checklist
    @app.post("/student/<sid>/checklist")
    def save_checklist(sid):
        st = get_student_or_404(sid)
        statuses = {code[len("status_"):]: v for code, v in request.form.items()
                   if code.startswith("status_")}
        try:
            n = service.save_checklist(store, st, statuses, expected_hash=request.form.get("rec_hash"))
            flash(f"{n} checklist row(s) updated." if n else "No changes.")
        except (service.Conflict, ValueError, records.RecordError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid) + "#checklist")

    @app.post("/student/<sid>/checklist/remark")
    def add_checklist_remark(sid):
        st = get_student_or_404(sid)
        try:
            service.add_checklist_remark(store, st, request.form.get("code", ""),
                                        request.form.get("text", ""),
                                        expected_hash=request.form.get("rec_hash"))
            flash("Remark added.")
        except (service.Conflict, ValueError, records.RecordError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid) + "#checklist")

    @app.post("/student/<sid>/checklist/remark/delete")
    def delete_checklist_remark(sid):
        st = get_student_or_404(sid)
        try:
            service.delete_checklist_remark(store, st, request.form.get("code", ""),
                                           int(request.form.get("idx", -1)),
                                           expected_hash=request.form.get("rec_hash"))
            flash("Remark deleted.")
        except (service.Conflict, ValueError, records.RecordError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid) + "#checklist")

    @app.post("/student/<sid>/grades/delete")
    def delete_grade(sid):
        st = get_student_or_404(sid)
        try:
            service.delete_grade_entry(store, st, request.form.get("ay", ""),
                                      request.form.get("sem", ""), request.form.get("code", ""),
                                      expected_hash=request.form.get("rec_hash"))
            flash("Grade entry deleted.")
        except (service.Conflict, ValueError, records.RecordError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid))

    # ------------------------------------------------------------- attachments
    @app.post("/student/<sid>/attachments")
    def add_attachment(sid):
        st = get_student_or_404(sid)
        f = request.files.get("file")
        try:
            if not f or not f.filename:
                raise ValueError("Choose a file to attach.")
            service.add_attachment(store, st, f.filename, f.mimetype, f,
                                  expected_hash=request.form.get("rec_hash"))
            flash(f"Attached {f.filename}.")
        except (service.Conflict, ValueError) as e:
            flash(f"⚠ {e}")
        return redirect(url_for("student", sid=sid) + "#attachments")

    @app.get("/student/<sid>/attachments/<path:name>")
    def get_attachment(sid, name):
        st = get_student_or_404(sid)
        # Only serve files that are actually recorded as attachments — not
        # record.json or any other file in the student's folder — and force
        # a download rather than serving inline, since an uploaded HTML/SVG
        # file rendered inline could run as active content under our origin.
        if name not in {a["name"] for a in st.record["attachments"]}:
            abort(404)
        return send_from_directory(st.folder_path, name, as_attachment=True)

    @app.post("/student/<sid>/attachments/open-folder")
    def open_attachments_folder(sid):
        st = get_student_or_404(sid)
        try:
            os.startfile(st.folder_path)  # noqa — Windows-only, local single-user app
            flash(f"Opened {st.folder_path}")
        except (AttributeError, OSError) as e:
            flash(f"⚠ Could not open the folder automatically — path: {st.folder_path} ({e})")
        return redirect(url_for("student", sid=sid) + "#attachments")

    @app.route("/student/<sid>/grades", methods=["GET", "POST"])
    def encode_grades(sid):
        st = get_student_or_404(sid)
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
        # rows to offer: current-term in-progress + outstanding INCs (none yet
        # for an advisee with no grade entries — just the blank entry row)
        cur_term = (cfg["term"]["current_ay"], cfg["term"]["current_sem"])
        rows = [g for g in st.an["in_progress"]] if st.an else []
        inc_codes = {(c, ay, sem) for c, ay, sem, _ in st.an["incs"]} if st.an else set()
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
