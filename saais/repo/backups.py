# -*- coding: utf-8 -*-
"""Timestamped file backups before every mutation.

The plan offered git commits as the audit trail, but this repo is published
publicly with student files gitignored — committing them into the same
history would leak PII (and git refuses ignored paths anyway). So SAAIS uses
the plan's fallback: copies under .backups/<timestamp>/, which is gitignored.
"""
import os
import shutil
from datetime import datetime

from . import paths


def backup(*file_paths):
    """Copy existing files into .backups/<timestamp>/<repo-relative-path>."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest_root = os.path.join(paths.BACKUPS_DIR, stamp)
    copied = []
    for fp in file_paths:
        if not fp or not os.path.exists(fp):
            continue
        rel = os.path.relpath(fp, paths.ROOT)
        dest = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(fp, dest)
        copied.append(dest)
    return copied
