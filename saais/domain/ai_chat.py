# -*- coding: utf-8 -*-
"""Local AI advising chat.

Talks only to a local Ollama server (configured in [ai] in saais.toml, default
http://127.0.0.1:11434). Context is strictly limited to the selected student's
own record — nothing about other students is ever included, and the transcript
is persisted only inside that student's own record.json (never a shared/global
log). No other network calls are made from this module.
"""
import json
import urllib.error
import urllib.request

SYSTEM_PROMPT = (
    "You are an academic advising assistant helping a human adviser think through "
    "one specific student's situation. Only use the student context provided below; "
    "do not invent grades, courses, or policies you were not given. Be concise and "
    "practical, and defer to the adviser's judgment on final decisions."
)


class AIError(Exception):
    """The local AI backend could not be reached or returned an error."""


def build_context(st):
    """Plain-text summary of one student's record for the model's context window."""
    lines = [f"Name: {st.name}", f"Student number: {st.sid}"]
    for k, v in st.fields.items():
        lines.append(f"{k}: {v}")
    if st.an and st.an.get("flags"):
        lines.append("Flags:")
        for kind, txt in st.an["flags"]:
            lines.append(f"  - [{kind}] {txt}")
    if st.notes:
        lines.append("Recent advising notes (newest first):")
        for n in st.notes[:10]:
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
