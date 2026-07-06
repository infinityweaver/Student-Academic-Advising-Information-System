# -*- coding: utf-8 -*-
"""Local AI advising chat.

Talks only to a local Ollama server (configured in [ai] in saais.toml, default
http://127.0.0.1:11434). Context is strictly limited to the selected student's
own record — nothing about other students is ever included, and the transcript
is persisted only inside that student's own record.json (never a shared/global
log). No other network calls are made from this module.
"""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import rules

#: Hostnames considered "this machine" — anything else is refused before any
#: request is made, so a misconfigured `[ai].host` can never exfiltrate a
#: student's record off-machine.
_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}

SYSTEM_PROMPT = (
    "You are an academic advising assistant helping a human adviser think through "
    "one specific student's situation. You are given that student's full record below: "
    "profile, flags, curriculum checklist (with grades and prior attempts), grade "
    "history by term, courses currently in progress, and recent advising notes. Only "
    "use the context provided; do not invent grades, courses, or policies you were not "
    "given. Be concise and practical, and defer to the adviser's judgment on final "
    "decisions."
)

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _plain(text):
    """Strip the **bold**/`code` markdown subset used in flag strings, for a
    plain-text model context."""
    return _BOLD_RE.sub(r"\1", text).replace("`", "")


class AIError(Exception):
    """The local AI backend could not be reached or returned an error."""


def build_context(st):
    """Plain-text summary of one student's *entire* record — profile, flags,
    curriculum checklist, grade history, in-progress courses, other courses not
    matched to the checklist, attachments on file, and recent advising notes —
    for the model's context window."""
    lines = [f"Name: {st.name}", f"Student number: {st.sid}"]
    for k, v in st.fields.items():
        lines.append(f"{k}: {v}")

    an = st.an
    if an:
        lines.append("")
        lines.append("Flags:")
        if an.get("flags"):
            for kind, txt in an["flags"]:
                lines.append(f"  - [{kind}] {_plain(txt)}")
        else:
            lines.append("  - None")

        if an.get("in_progress"):
            lines.append("")
            lines.append(f"Currently enrolled ({rules.short_term(*an['latest_term'])}), "
                         "no final grade yet:")
            for g in an["in_progress"]:
                mid = f" (midterm {g['midterm']})" if g.get("midterm") else ""
                lines.append(f"  - {g['course_code']} — {g['course_title'].title()}{mid}")

        overrides = st.record.get("checklist", {}) if st.record else {}
        lines.append("")
        lines.append("Curriculum checklist (course code, title, units — status; "
                     "grade · term; prior attempts):")
        for item in an["checklist"]:
            row = item["row"]
            override = overrides.get(row["code"])
            status, when, hist = rules.row_status(item, an["passed"], override=override)
            line = f"  - {row['code']} {row['title']} ({row['units']:g}u): {_plain(status)}"
            if when:
                line += f" — {when}"
            if hist:
                line += f"; prior attempts: {hist}"
            lines.append(line)

        if an.get("extra"):
            lines.append("")
            lines.append("Other courses taken (not matched to the checklist):")
            for g in an["extra"]:
                _, _, disp = rules.effective(g)
                lines.append(f"  - {g['course_code']} {g['course_title'].title()} — {disp} "
                             f"({rules.short_term(g['academic_year'], g['semester'])})")

        lines.append("")
        lines.append("Grade history by term:")
        for (ay, sem), recs in sorted(an["per_term"].items(),
                                      key=lambda kv: rules.term_key(*kv[0])):
            lines.append(f"  {rules.short_term(ay, sem)}:")
            for g in recs:
                _, _, disp = rules.effective(g)
                lines.append(f"    - {g['course_code']} {g['course_title'].title()} "
                             f"({g['units']:g}u): {disp}")

    if st.record and st.record.get("attachments"):
        lines.append("")
        lines.append("Attachments on file:")
        for a in st.record["attachments"]:
            lines.append(f"  - {a['name']} ({a['type']}), added {a['added']}")

    if st.notes:
        lines.append("")
        lines.append("Advising notes (newest first):")
        for n in st.notes[:15]:
            lines.append(f"  - {n['date']}: {n['text']}")

    return "\n".join(lines)


def ask(cfg, st, history, message):
    """history: [{'role': 'user'|'assistant', 'text': ...}, ...], oldest first,
    already saved in the record. Returns the assistant's reply text, or raises
    AIError if the local model can't be reached."""
    ai_cfg = cfg.get("ai", {}) if cfg else {}
    host = str(ai_cfg.get("host") or "http://127.0.0.1:11434").rstrip("/")
    model = ai_cfg.get("model") or "qwen2.5:7b"
    timeout = float(ai_cfg.get("timeout") or 30)

    hostname = (urlsplit(host).hostname or "").lower()
    if hostname not in _LOCAL_HOSTNAMES:
        raise AIError(
            f"[ai].host must point to this machine (127.0.0.1/localhost), got {host!r}. "
            "Refusing to send student data to a non-local address.")

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + build_context(st)}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["text"]})
    messages.append({"role": "user", "content": message})

    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
    req = urllib.request.Request(f"{host}/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise AIError(f"Could not reach the local AI model at {host} ({e.reason}). "
                      "Is Ollama running?") from e
    except (TimeoutError, OSError, ValueError) as e:
        raise AIError(f"Local AI request failed: {e}") from e
    reply = (data.get("message") or {}).get("content")
    if not reply:
        raise AIError("The local AI model returned an empty response.")
    return reply.strip()
