"""FastAPI server for DataPrep Studio.

The server owns one `shared` dict per session and only writes `request` (and the read
overrides on reload). Everything else is written by the PocketFlow nodes.
Run:  uvicorn app:app --reload
"""

import asyncio
import copy
import logging
import os
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from flow import (
    create_attach_flow,
    create_export_flow,
    create_move_flow,
    create_operation_flow,
    create_replay_flow,
    create_script_flow,
    create_shared,
    create_upload_flow,
)
from nodes import active_steps
from utils.file_detect import EXTENSIONS
from utils.json_safe import df_page, to_jsonable
from utils.op_registry import catalog

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dataprep")

ROOT = Path(__file__).resolve().parent
STORAGE_ROOT = Path(os.getenv("STORAGE_DIR", ROOT / "storage"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_HOURS", "24")) * 3600
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

SESSIONS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_app):
    """Sessions live in memory, so folders left from a previous run can never be reopened."""
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    for folder in STORAGE_ROOT.iterdir():
        if folder.is_dir() and UUID_RE.match(folder.name):
            shutil.rmtree(folder, ignore_errors=True)
    yield


app = FastAPI(title="DataPrep Studio", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ helpers


def _evict_idle():
    now = time.time()
    for session_id in [sid for sid, s in SESSIONS.items() if now - s["last_used"] > SESSION_TTL_SECONDS]:
        _drop_session(session_id)


def _drop_session(session_id):
    session = SESSIONS.pop(session_id, None)
    if session:
        shutil.rmtree(session["shared"]["session"]["storage_dir"], ignore_errors=True)


def _session(session_id):
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(404, "Η συνεδρία δεν βρέθηκε ή έληξε. Ανέβασε ξανά το αρχείο.")
    session["last_used"] = time.time()
    return session


async def _run(session, flow, request=None):
    """Run a sync flow in a worker thread, one at a time per session."""
    shared = session["shared"]
    async with session["lock"]:
        shared["request"] = request or {}
        shared["result"] = None
        await run_in_threadpool(flow.run, shared)
    result = shared["result"]
    if result and result.get("status") == "error":
        raise HTTPException(400, result["message"])
    return result


def _history(shared):
    steps = {s["version_after"]: s for s in shared["recipe"]}
    versions = []
    for v in shared["versions"]:
        step = steps.get(v["version"])
        versions.append({
            "version": v["version"],
            "shape": v["shape"],
            "label": step["label"] if step else "Αρχικό αρχείο",
            "op": step["op"] if step else None,
            "summary": step["summary"] if step else None,
            "params": step["params"] if step else None,
            "at": step["at"] if step else None,
        })
    current = shared["current_version"]
    last = max((v["version"] for v in shared["versions"]), default=0)
    return {"current_version": current, "versions": versions, "can_undo": current > 0, "can_redo": current < last}


def _state(shared):
    source = shared["source"]
    public_source = {k: v for k, v in source.items() if k != "path"}
    attachments = [
        {"name": a["name"], "filename": a["filename"], "format": a["format"], "encoding": a.get("encoding"),
         "shape": a["shape"], "columns": a["columns"][:200]}
        for a in shared.get("attachments", {}).values()
    ]
    return to_jsonable({
        "session_id": shared["session"]["id"],
        "source": public_source,
        "profile": shared["profile"],
        "history": _history(shared),
        "suggestions": shared["suggestions"],
        "attachments": attachments,
    })


# ------------------------------------------------------------------ catalog

@app.get("/api/operations")
def operations():
    return catalog()


# ------------------------------------------------------------------ sessions

def _checked_name(upload):
    filename = Path(upload.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in EXTENSIONS:
        allowed = ", ".join(sorted(EXTENSIONS))
        raise HTTPException(400, f"Μη υποστηριζόμενη κατάληξη '{extension}'. Επιτρέπονται: {allowed}")
    return filename, extension


def _remove(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


async def _save_upload(upload, target, cleanup):
    """Stream to disk with the size limit. `cleanup` (file or folder) is removed on failure."""
    size = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    with open(target, "wb") as out:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                _remove(cleanup)
                raise HTTPException(413, f"Το αρχείο ξεπερνά το όριο των {MAX_UPLOAD_MB} MB.")
            out.write(chunk)
    if size == 0:
        _remove(cleanup)
        raise HTTPException(400, "Το αρχείο είναι κενό.")
    return size


@app.post("/api/sessions")
async def create_session(file: UploadFile):
    _evict_idle()
    filename, extension = _checked_name(file)
    session_id = str(uuid.uuid4())
    folder = STORAGE_ROOT / session_id
    folder.mkdir(parents=True)
    source_path = folder / f"source{extension}"
    size = await _save_upload(file, source_path, folder)

    shared = create_shared(session_id, str(folder), str(source_path), filename, size)
    session = {"shared": shared, "lock": asyncio.Lock(), "last_used": time.time()}
    try:
        await _run(session, create_upload_flow())
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    SESSIONS[session_id] = session
    logger.info("Session %s created from %s (%s bytes)", session_id, filename, size)
    return {**_state(shared), "page": df_page(shared["df_cache"]["df"])}


class ReloadRequest(BaseModel):
    encoding: str | None = None
    delimiter: str | None = None
    decimal: Literal[".", ","] | None = None
    sheet: str | None = None


@app.post("/api/sessions/{session_id}/reload")
async def reload_session(session_id: str, body: ReloadRequest):
    """Read the original file again with other settings. This resets the history."""
    session = _session(session_id)
    shared = session["shared"]
    backup = copy.deepcopy(shared["source"])
    shared["source"]["read_overrides"] = {k: v for k, v in body.model_dump().items() if v}
    try:
        await _run(session, create_upload_flow())
    except HTTPException:
        shared["source"] = backup
        raise
    return {**_state(shared), "page": df_page(shared["df_cache"]["df"])}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    return _state(_session(session_id)["shared"])


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    _session(session_id)
    _drop_session(session_id)
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/data")
def get_data(session_id: str, page: int = 1, size: int = 50, sort: str | None = None, desc: bool = False):
    shared = _session(session_id)["shared"]
    return df_page(shared["df_cache"]["df"], page, size, sort, desc)


# ------------------------------------------------------------------ operations

class OperationRequest(BaseModel):
    op: str
    params: dict = {}
    preview: bool = False


@app.post("/api/sessions/{session_id}/ops")
async def run_operation(session_id: str, body: OperationRequest):
    session = _session(session_id)
    result = await _run(session, create_operation_flow(), body.model_dump())
    return {"result": result, **_state(session["shared"])}


@app.post("/api/sessions/{session_id}/undo")
async def undo(session_id: str):
    session = _session(session_id)
    result = await _run(session, create_move_flow(), {"target": "undo"})
    return {"result": result, **_state(session["shared"])}


@app.post("/api/sessions/{session_id}/redo")
async def redo(session_id: str):
    session = _session(session_id)
    result = await _run(session, create_move_flow(), {"target": "redo"})
    return {"result": result, **_state(session["shared"])}


@app.post("/api/sessions/{session_id}/checkout/{version}")
async def checkout(session_id: str, version: int):
    session = _session(session_id)
    result = await _run(session, create_move_flow(), {"target": version})
    return {"result": result, **_state(session["shared"])}


# ------------------------------------------------------------------ export

@app.get("/api/sessions/{session_id}/export")
async def export(session_id: str, format: Literal["csv", "excel", "json", "parquet"] = "csv",
                 encoding: str = "utf-8-sig", delimiter: str = ","):
    session = _session(session_id)
    result = await _run(session, create_export_flow(), {"format": format, "encoding": encoding, "delimiter": delimiter})
    payload = result["payload"]
    return FileResponse(payload["path"], media_type=payload["media_type"], filename=payload["filename"])


@app.get("/api/sessions/{session_id}/script")
async def script(session_id: str):
    session = _session(session_id)
    result = await _run(session, create_script_flow())
    return {"filename": "pipeline.py", "script": result["payload"]["script"]}


@app.get("/api/sessions/{session_id}/recipe")
def recipe(session_id: str):
    shared = _session(session_id)["shared"]
    steps = [{"op": s["op"], "label": s["label"], "params": s["params"]} for s in active_steps(shared)]
    return {"source": shared["source"]["filename"], "steps": steps}


class RecipeRequest(BaseModel):
    steps: list[dict]
    source: str | None = None


@app.post("/api/sessions/{session_id}/recipe/apply")
async def apply_recipe(session_id: str, body: RecipeRequest):
    """Replay saved steps (recipe.json) on the current version, e.g. on next month's file."""
    session = _session(session_id)
    result = await _run(session, create_replay_flow(), {"steps": body.steps})
    return {"result": result, **_state(session["shared"])}


@app.post("/api/sessions/{session_id}/attachments")
async def add_attachment(session_id: str, file: UploadFile):
    """A second file for joins. Same format/encoding detection as the main upload."""
    session = _session(session_id)
    filename, extension = _checked_name(file)
    folder = Path(session["shared"]["session"]["storage_dir"]) / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid.uuid4().hex}{extension}"
    await _save_upload(file, target, target)
    await _run(session, create_attach_flow(), {"path": str(target), "filename": filename})
    return _state(session["shared"])


ML_FILES = {"train_clean.csv", "test_clean.csv", "preprocess.py", "raw.csv", "config.json"}


@app.get("/api/sessions/{session_id}/files/{name}")
def session_file(session_id: str, name: str):
    """Files produced by buttons (ML Prep). Only known names, so no path tricks."""
    shared = _session(session_id)["shared"]
    if name not in ML_FILES:
        raise HTTPException(404, "Άγνωστο αρχείο.")
    path = Path(shared["session"]["storage_dir"]) / "exports" / "ml" / name
    if not path.is_file():
        raise HTTPException(404, "Το αρχείο δεν έχει δημιουργηθεί — τρέξε ξανά το ML Prep.")
    return FileResponse(path, filename=name)


# ------------------------------------------------------------------ frontend (production build)

class _FrontendFiles(StaticFiles):
    """index.html must not be cached, or browsers keep loading an old bundle after a rebuild.
    The hashed files under /assets can be cached forever."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


if FRONTEND_DIST.is_dir():
    app.mount("/", _FrontendFiles(directory=FRONTEND_DIST, html=True), name="frontend")
