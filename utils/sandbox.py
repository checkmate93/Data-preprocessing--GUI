"""Run model-written pandas code away from the server process.

Two layers:
1. `check_code` — an AST allow-list: only data-science imports, no file/network/OS access, no dunder or
   private attributes, no exec/eval/open, no pandas readers/writers. It rejects before anything runs.
2. `run_code` — a separate `python -I` process with a timeout, an empty environment (no API keys) and a
   throwaway working folder. On Linux it also gets memory and CPU limits.

This is defence in depth for an internal tool, not a hard security boundary. For a public deployment
run the backend in a container with no outbound network (see docs/design.md).
"""

import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RUNNER = Path(__file__).with_name("sandbox_runner.py")
TIMEOUT_SECONDS = int(os.environ.get("DATAPREP_SANDBOX_TIMEOUT", "60"))
MEMORY_MB = int(os.environ.get("DATAPREP_SANDBOX_MEMORY_MB", "2048"))

ALLOWED_MODULES = {
    "pandas", "numpy", "sklearn", "scipy", "statsmodels", "math", "statistics", "re", "datetime",
    "json", "collections", "itertools", "functools", "decimal", "unicodedata", "string", "calendar",
}
BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "object", "type", "super",
}
ALLOWED_TO = {
    "to_numeric", "to_datetime", "to_timedelta", "to_period", "to_frame", "to_list", "to_dict",
    "to_numpy", "to_string", "to_timestamp", "to_series", "to_records", "to_offset",
}
BLOCKED_ATTRS = {"eval", "query", "system", "popen", "remove", "unlink", "rmtree", "get_rdataset", "webuse", "pipe"}
BLOCKED_PREFIXES = ("read_", "fetch_", "load_", "save", "dump")


class CodeRejected(ValueError):
    pass


def check_code(code):
    """Raise CodeRejected with a readable reason when the code uses something outside the allow-list."""
    try:  # turn a syntax error into the same readable rejection
        tree = ast.parse(code)
    except SyntaxError as error:
        raise CodeRejected(f"Συντακτικό λάθος στη γραμμή {error.lineno}: {error.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] not in ALLOWED_MODULES:
                    raise CodeRejected(f"Δεν επιτρέπεται import '{name}'. Επιτρέπονται: {', '.join(sorted(ALLOWED_MODULES))}")
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            raise CodeRejected(f"Δεν επιτρέπεται το '{node.id}'.")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise CodeRejected(f"Δεν επιτρέπεται το '{node.id}'.")
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("_"):
                raise CodeRejected(f"Δεν επιτρέπονται ιδιωτικά attributes ('.{attr}').")
            if attr in BLOCKED_ATTRS or attr.startswith(BLOCKED_PREFIXES):
                raise CodeRejected(f"Δεν επιτρέπεται το '.{attr}' (αρχεία, δίκτυο ή eval).")
            if attr.startswith("to_") and attr not in ALLOWED_TO:
                raise CodeRejected(f"Δεν επιτρέπεται το '.{attr}' (εγγραφή αρχείων).")
        elif isinstance(node, (ast.ClassDef, ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await)):
            raise CodeRejected("Δεν επιτρέπονται classes, global/nonlocal ή async.")
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            raise CodeRejected("Οι συναρτήσεις δεν μπορούν να ξεκινούν με '_'.")
    return tree


def _limits():  # pragma: no cover - Linux only
    import resource

    memory = MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS + 5))


def _clean_env():
    env = {"PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"}
    if os.name == "nt":  # Windows DLL loading needs these two
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = str(Path(sys.executable).parent)
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


def run_code(df, code, mode="analyze"):
    """Input: DataFrame, code, mode "analyze" (df is read-only) or "transform" (code assigns df).
    Output: {"stdout", "result", "df" (transform only), "seconds"}. Raises ValueError with the error text.
    """
    check_code(code)
    with tempfile.TemporaryDirectory(prefix="dataprep_sandbox_") as folder:
        folder = Path(folder)
        df.to_pickle(folder / "input.pkl")
        (folder / "code.py").write_text(code, encoding="utf-8")
        try:  # a hung script must not hang the request
            completed = subprocess.run(
                [sys.executable, "-I", str(RUNNER), str(folder), mode],
                cwd=folder, env=_clean_env(), capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS, preexec_fn=_limits if os.name != "nt" else None,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(f"Ο κώδικας ξεπέρασε το όριο των {TIMEOUT_SECONDS} δευτερολέπτων.") from None
        report_path = folder / "report.json"
        if not report_path.exists():
            detail = (completed.stderr or "").strip().splitlines()[-3:]
            raise ValueError("Η εκτέλεση σταμάτησε: " + (" ".join(detail) or f"exit code {completed.returncode}"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("error"):
            raise ValueError(report["error"])
        if mode == "transform":
            report["df"] = pd.read_pickle(folder / "output.pkl")
        logger.info("Sandbox %s ok in %.2fs", mode, report.get("seconds", 0))
        return report


if __name__ == "__main__":
    demo = pd.DataFrame({"sex": ["male", "female", "female"], "age": [20, 30, 40]})
    out = run_code(demo, "df['sex'] = df['sex'].map({'male': 0, 'female': 1})\nprint(df['sex'].tolist())", "transform")
    assert out["df"]["sex"].tolist() == [0, 1, 1] and "[0, 1, 1]" in out["stdout"]
    out = run_code(demo, "import statsmodels.api as sm\nresult = df['age'].mean()")
    assert out["result"].strip() == "30.0", out
    for bad in ["import os", "open('x')", "df.to_csv('x')", "df.__class__", "pd.read_csv('http://x')", "().__class__"]:
        try:
            check_code(bad)
        except CodeRejected:
            continue
        raise AssertionError(f"not rejected: {bad}")
    try:
        run_code(demo, "df['missing_column'].sum()")
    except ValueError as error:
        assert "missing_column" in str(error), error
    print("sandbox ok")
