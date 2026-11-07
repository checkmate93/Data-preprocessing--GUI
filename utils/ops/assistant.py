"""Code written by the chat assistant, run in the sandbox.

They are ordinary registry operations (hidden from the sidebar), so a change made by the assistant gets
a version, undo, a pipeline.py snippet and recipe replay like any button.
"""

from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, text
from utils.sandbox import run_code


class PythonParams(Params):
    code: str = Field(title="Κώδικας pandas", min_length=1)
    description: str = Field("", title="Περιγραφή")


def _output(report):
    parts = [part.strip() for part in (report.get("stdout"), report.get("result")) if part and part.strip()]
    return "\n\n".join(parts)


@operation(
    "assistant.python_analyze", "Ανάλυση με κώδικα (βοηθός)",
    "Κώδικας pandas/sklearn/statsmodels που διαβάζει τα δεδομένα χωρίς να τα αλλάζει",
    "assistant", "inspect", PythonParams,
)
def python_analyze(df, p, ctx):
    report = run_code(df, p.code, "analyze")
    output = _output(report)
    return OpOutput(sections=[text(output or "(ο κώδικας δεν τύπωσε τίποτα)", p.description or "Αποτέλεσμα")],
                    message=p.description)


@operation(
    "assistant.python_transform", "Αλλαγή με κώδικα (βοηθός)",
    "Κώδικας pandas που αλλάζει τον πίνακα (νέα έκδοση, με αναίρεση)",
    "assistant", "transform", PythonParams,
    code=lambda p: (f"# {p.description}\n" if p.description else "") + p.code.strip(),
)
def python_transform(df, p, ctx):
    report = run_code(df, p.code, "transform")
    output = _output(report)
    return OpOutput(df=report["df"], sections=[text(output, "Έξοδος")] if output else [],
                    message=p.description or "Ο κώδικας εφαρμόστηκε")
