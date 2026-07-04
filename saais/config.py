# -*- coding: utf-8 -*-
"""Configuration for SAAIS, read from saais/saais.toml.

Python 3.10 has no stdlib TOML reader, so this parses the small TOML subset
the config actually uses: [sections], key = "string" | number | true/false,
and # comments. Unknown keys are kept so the config page can round-trip them.
"""
import os
import re

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saais.toml")

DEFAULTS = {
    "term": {
        "current_ay": "2025-2026",
        "current_sem": "Second Semester",
    },
    "rules": {
        "pass_threshold": 3.0,
        "delinquency_ratio": 0.25,
        "inc_years": 1,
        "retakes_needing_attention": 3,
        "max_units_regular": 24,
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
    },
}


def _parse_value(raw):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def load():
    cfg = {sec: dict(vals) for sec, vals in DEFAULTS.items()}
    if not os.path.exists(CONFIG_PATH):
        return cfg
    section = None
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            m = re.match(r"^\[(.+)\]$", line)
            if m:
                section = m.group(1).strip()
                cfg.setdefault(section, {})
                continue
            if "=" in line and section:
                key, _, raw = line.partition("=")
                cfg[section][key.strip()] = _parse_value(raw)
    return cfg
