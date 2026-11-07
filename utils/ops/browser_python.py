"""A table computed in the browser (Pyodide) saved as a new server version.

The browser uploads the resulting df as CSV + its dtypes; the API stages the file and runs this
operation through the normal operation flow, so the change gets a version, undo, a pipeline.py
snippet (the code the user ran) and a recipe step. On recipe replay there is no staged file, so the
same code runs in the server sandbox instead.
"""

import re
from pathlib import Path

import pandas as pd
from pydantic import Field

from utils.op_registry import OpOutput, Params, operation
from utils.sandbox import run_code

STAGED_DIR = "staged"
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")


class BrowserPythonParams(Params):
    code: str = Field("", title="Κώδικας που έτρεξε στον browser")
    description: str = Field("", title="Περιγραφή")
    upload_id: str = Field("", title="Αρχείο από τον browser (εσωτερικό)")
    dtypes: dict[str, str] = Field(default_factory=dict, title="Τύποι στηλών (εσωτερικό)")


def staged_path(storage_dir, upload_id):
    if not UPLOAD_ID.match(upload_id):
        raise ValueError("Μη έγκυρο upload_id.")
    return Path(storage_dir) / STAGED_DIR / f"{upload_id}.csv"


def read_with_dtypes(path, dtypes):
    """CSV from the browser -> DataFrame with the dtypes it had there (text stays text, dates are dates)."""
    text_like = {c for c, t in dtypes.items() if t in ("object", "string", "str", "category")}
    dates = [c for c, t in dtypes.items() if t.startswith("datetime64")]
    frame = pd.read_csv(path, dtype={c: "string" for c in text_like}, parse_dates=dates, low_memory=False)
    for column, dtype in dtypes.items():
        if column not in frame.columns:
            continue
        if dtype == "category":
            frame[column] = frame[column].astype("category")
        elif dtype in ("bool", "boolean"):
            frame[column] = frame[column].map({True: True, False: False, "True": True, "False": False}).astype("boolean")
        elif dtype.startswith(("int", "Int")) and frame[column].isna().any():
            frame[column] = frame[column].astype("Int64")
    return frame


def _snippet(p):
    header = f"# {p.description}\n" if p.description else ""
    return header + "# (έτρεξε στον browser με Pyodide)\n" + (p.code.strip() or "pass")


@operation(
    "browser.python_version", "Python στον browser",
    "Αποθήκευση του df που υπολογίστηκε στον browser ως νέα έκδοση",
    "assistant", "transform", BrowserPythonParams, code=_snippet,
)
def browser_python_version(df, p, ctx):
    path = staged_path(ctx["storage_dir"], p.upload_id) if p.upload_id else None
    if path is not None and path.exists():
        new = read_with_dtypes(path, p.dtypes)
        path.unlink(missing_ok=True)
        warnings = []
    elif p.code.strip():
        # Recipe replay: no browser here, so the same code runs in the server sandbox.
        new = run_code(df, p.code, "transform")["df"]
        warnings = ["Ο κώδικας του browser ξανάτρεξε στον server (recipe replay)."]
    else:
        raise ValueError("Το αρχείο από τον browser δεν βρέθηκε και δεν υπάρχει κώδικας για να ξανατρέξει.")
    return OpOutput(df=new, warnings=warnings, message=p.description or "Αποθηκεύτηκε το df από τον browser")
