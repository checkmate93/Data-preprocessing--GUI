"""FastAPI owner of the session dict. Nodes never see the request."""

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"

from flow import create_process_flow, create_shared, create_upload_flow
from utils.artifact_exporter import EXPORT_ROOT

app = FastAPI(title="DataPrep Studio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS = {}
UPLOAD_ROOT = Path("uploads")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sample.csv")
def sample_csv():
    from utils.artifact_exporter import pd_sample

    sample_path = UPLOAD_ROOT / "sample.csv"
    UPLOAD_ROOT.mkdir(exist_ok=True)
    pd_sample().to_csv(sample_path, index=False)
    return FileResponse(sample_path, media_type="text/csv", filename="sample.csv")


@app.post("/api/upload")
async def upload_csv(file: UploadFile, advisor_mode: str = "heuristic"):
    mode = advisor_mode.strip().lower()
    if mode not in {"heuristic", "llm"}:
        raise HTTPException(status_code=400, detail="advisor_mode must be heuristic or llm")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")

    session_id = str(uuid.uuid4())
    UPLOAD_ROOT.mkdir(exist_ok=True)
    raw_path = UPLOAD_ROOT / f"{session_id}_raw.csv"
    raw_path.write_bytes(await file.read())

    shared = create_shared(session_id, str(raw_path), mode)
    SESSIONS[session_id] = shared
    try:
        await create_upload_flow().run_async(shared)
    except Exception as exc:
        SESSIONS.pop(session_id, None)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "session_id": session_id,
        "initial_profile": shared["initial_profile"],
        "cleaning_config": shared["cleaning_config"],
    }


@app.post("/api/process/{session_id}")
def process_csv(session_id: str, cleaning_config: dict):
    shared = _session(session_id)
    if shared.get("working_df") is None:
        raise HTTPException(status_code=400, detail="Upload a CSV before processing")
    shared["cleaning_config"] = cleaning_config
    try:
        create_process_flow().run(shared)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return shared["final_report"]


@app.get("/api/export/{session_id}/{kind}")
def export_file(session_id: str, kind: str):
    _session(session_id)
    folder = EXPORT_ROOT / session_id
    names = {"train": "train_clean.csv", "test": "test_clean.csv", "script": "preprocess.py"}
    if kind not in names:
        raise HTTPException(status_code=404, detail="Export kind must be train, test, or script")
    path = folder / names[kind]
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{kind} export is not ready")
    media = "text/x-python" if kind == "script" else "text/csv"
    return FileResponse(path, media_type=media, filename=names[kind])


def _session(session_id):
    shared = SESSIONS.get(session_id)
    if shared is None:
        raise HTTPException(status_code=404, detail="Unknown session_id")
    return shared
