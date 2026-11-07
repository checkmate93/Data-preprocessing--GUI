"""Runs one piece of model-written code in its own `python -I` process. Started only by utils/sandbox.py.

Usage: python -I sandbox_runner.py <folder> <analyze|transform>
Reads <folder>/input.pkl and <folder>/code.py, writes <folder>/report.json (and output.pkl for transform).
Self-contained on purpose: it must not import project code.
"""

import contextlib
import datetime
import decimal
import io
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

MAX_OUTPUT = 6000
SAFE_SCALARS = (str, int, float, bool, type(None), decimal.Decimal, datetime.date, datetime.datetime,
                datetime.time, datetime.timedelta, pd.Timestamp, pd.Timedelta, np.generic)


def show(value):
    if isinstance(value, pd.DataFrame):
        return value.head(30).to_string(max_cols=30, max_colwidth=40) + (f"\n… {len(value)} γραμμές" if len(value) > 30 else "")
    if isinstance(value, pd.Series):
        return value.head(40).to_string(max_rows=40) + (f"\n… {len(value)} τιμές" if len(value) > 40 else "")
    summary = getattr(value, "summary", None)
    if callable(summary):  # statsmodels results
        return str(summary())
    if isinstance(value, np.generic):
        value = value.item()
    return repr(value)


def safe_frame(df):
    """Object columns may only hold plain values, so the server can unpickle the result safely."""
    out = df.copy()
    for column in out.columns:
        if out[column].dtype == object:
            out[column] = out[column].map(lambda v: v if isinstance(v, SAFE_SCALARS) or v is pd.NA else str(v))
    out.columns = [str(c) for c in out.columns]
    return out


def main():
    folder, mode = Path(sys.argv[1]), sys.argv[2]
    df = pd.read_pickle(folder / "input.pkl")
    code = (folder / "code.py").read_text(encoding="utf-8")
    scope = {"pd": pd, "np": np, "df": df.copy() if mode == "transform" else df}
    buffer = io.StringIO()
    report = {"stdout": "", "result": None, "error": None}
    started = time.perf_counter()
    try:  # report the user's error instead of crashing the runner
        with contextlib.redirect_stdout(buffer):
            exec(compile(code, "<assistant>", "exec"), scope)  # noqa: S102 - code passed utils.sandbox.check_code
        if "result" in scope:
            report["result"] = show(scope["result"])[:MAX_OUTPUT]
        if mode == "transform":
            new = scope.get("df")
            if not isinstance(new, pd.DataFrame):
                raise TypeError("Σε λειτουργία transform ο κώδικας πρέπει να αφήνει πίνακα (DataFrame) στη μεταβλητή df.")
            safe_frame(new).to_pickle(folder / "output.pkl")
    except Exception as error:  # noqa: BLE001
        frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == "<assistant>"]
        line = f" (γραμμή {frames[-1].lineno})" if frames else ""
        report["error"] = f"{type(error).__name__}{line}: {error}"
    report["stdout"] = buffer.getvalue()[:MAX_OUTPUT]
    report["seconds"] = round(time.perf_counter() - started, 3)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
