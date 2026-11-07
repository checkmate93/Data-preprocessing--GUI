"""Session state on disk, so a session survives a server restart and a browser refresh.

storage/<session_id>/
    session.pkl          everything in `shared` except the DataFrame (history, recipe, chat, profile…)
    versions/v<n>.pkl    the tables (already written by SaveVersionNode)

Memory: a session's current DataFrame lives in `shared["df_cache"]` only while the session is among the
most recently used ones (see app.py); otherwise it is dropped and re-read from versions/ on the next use.
The files are written and read only by this server (never taken from users), so pickle is safe here.
"""

import logging
import os
import pickle
import re
import shutil
import time
from pathlib import Path

from utils.version_store import load_version

logger = logging.getLogger(__name__)

STATE_FILE = "session.pkl"
TRANSIENT_KEYS = ("request", "result", "replay")  # per-request scratch, never needed after the request
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
UNFINISHED_UPLOAD_SECONDS = 3600


def save_state(shared):
    """Write `shared` without the DataFrame. Atomic: a crash mid-write keeps the previous file."""
    state = {key: value for key, value in shared.items() if key not in TRANSIENT_KEYS}
    state["df_cache"] = {"version": None, "df": None}
    folder = Path(shared["session"]["storage_dir"])
    temporary = folder / f"{STATE_FILE}.tmp"
    with open(temporary, "wb") as handle:
        pickle.dump(state, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temporary, folder / STATE_FILE)


def load_state(storage_root, session_id):
    """Output: `shared` (DataFrame not loaded) or None when the session is unknown or expired."""
    if not UUID_RE.match(session_id):
        return None
    path = Path(storage_root) / session_id / STATE_FILE
    if not path.is_file():
        return None
    with open(path, "rb") as handle:
        shared = pickle.load(handle)
    shared.update(request={}, result=None)
    # The folder may have moved (other machine, STORAGE_DIR changed): point every path at the real one.
    real = str(path.parent)
    old = shared["session"]["storage_dir"]
    if old != real:
        shared["session"]["storage_dir"] = real
        shared["source"]["path"] = shared["source"]["path"].replace(old, real, 1)
        for version in shared["versions"]:
            version["path"] = version["path"].replace(old, real, 1)
        for attachment in shared.get("attachments", {}).values():
            attachment["data_path"] = attachment["data_path"].replace(old, real, 1)
    logger.info("Restored session %s from disk (v%s)", session_id, shared["current_version"])
    return shared


def hydrate(shared):
    """Make sure the current version's DataFrame is in memory."""
    cache = shared["df_cache"]
    current = shared["current_version"]
    if cache.get("df") is not None and cache.get("version") == current:
        return cache["df"]
    path = next(v["path"] for v in shared["versions"] if v["version"] == current)
    shared["df_cache"] = {"version": current, "df": load_version(path)}
    return shared["df_cache"]["df"]


def evict(shared):
    """Drop the DataFrame from memory; it stays on disk as versions/v<n>.pkl."""
    shared["df_cache"] = {"version": None, "df": None}


def cleanup_expired(storage_root, ttl_seconds, now=None):
    """Delete session folders not used for `ttl_seconds` (and abandoned uploads). Output: deleted ids."""
    now = now or time.time()
    deleted = []
    root = Path(storage_root)
    if not root.is_dir():
        return deleted
    for folder in root.iterdir():
        if not (folder.is_dir() and UUID_RE.match(folder.name)):
            continue
        state = folder / STATE_FILE
        last_used = state.stat().st_mtime if state.exists() else folder.stat().st_mtime
        limit = ttl_seconds if state.exists() else UNFINISHED_UPLOAD_SECONDS
        if now - last_used > limit:
            shutil.rmtree(folder, ignore_errors=True)
            deleted.append(folder.name)
    if deleted:
        logger.info("Deleted %s expired sessions", len(deleted))
    return deleted


def touch(shared):
    """Mark the session as used (the TTL counts from the state file's mtime)."""
    path = Path(shared["session"]["storage_dir"]) / STATE_FILE
    if path.exists():
        os.utime(path)
