"""Operation registry: one entry per button.

An operation is a pure function fn(df, params, ctx) -> OpOutput.
- kind "inspect": returns sections only, never a DataFrame.
- kind "transform": returns the new DataFrame plus sections describing the change.
`code(params)` returns the pandas snippet that goes into pipeline.py.
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

CATEGORIES = [
    ("inspect", "Επιθεώρηση"),
    ("columns", "Στήλες"),
    ("types", "Τύποι δεδομένων"),
    ("missing", "Κενές τιμές"),
    ("duplicates", "Διπλότυπα"),
    ("text", "Κείμενο"),
    ("datetime", "Ημερομηνίες"),
    ("numeric", "Αριθμητικά"),
    ("categorical", "Κατηγορίες (encoding)"),
    ("rows", "Γραμμές"),
    ("reshape", "Αναδιάρθρωση"),
    ("charts", "Γραφήματα"),
    ("ml", "ML Prep"),
    ("assistant", "Βοηθός (AI)"),
]
HIDDEN_CATEGORIES = {"assistant"}  # run by the chat assistant, not shown as buttons


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class OpOutput:
    df: Any = None
    sections: list = field(default_factory=list)
    message: str = ""
    warnings: list = field(default_factory=list)


@dataclass
class OperationSpec:
    id: str
    label: str
    description: str
    category: str
    kind: str
    params_model: type
    fn: Callable
    code: Callable | None = None


_REGISTRY: dict[str, OperationSpec] = {}


def operation(op_id, label, description, category, kind, params=Params, code=None):
    if kind not in ("inspect", "transform"):
        raise ValueError(f"kind must be inspect or transform, got {kind}")
    if category not in dict(CATEGORIES):
        raise ValueError(f"Unknown category {category}")

    def register(fn):
        _REGISTRY[op_id] = OperationSpec(op_id, label, description, category, kind, params, fn, code)
        return fn

    return register


def render_code(spec, params, ctx):
    """code(params) for most ops; code(params, ctx) when the snippet needs session context (merge)."""
    if spec.code is None:
        return None
    if len(inspect.signature(spec.code).parameters) == 2:
        return spec.code(params, ctx)
    return spec.code(params)


def get_op(op_id):
    _load_operations()
    if op_id not in _REGISTRY:
        raise KeyError(f"Άγνωστη λειτουργία: {op_id}")
    return _REGISTRY[op_id]


def catalog():
    _load_operations()
    return {
        "categories": [{"id": key, "label": label, "hidden": key in HIDDEN_CATEGORIES} for key, label in CATEGORIES],
        "operations": [
            {
                "id": spec.id,
                "label": spec.label,
                "description": spec.description,
                "category": spec.category,
                "kind": spec.kind,
                "schema": spec.params_model.model_json_schema(),
            }
            for spec in _REGISTRY.values()
        ],
    }


def _load_operations():
    import utils.ops  # noqa: F401  registers every operation module


# ---------- small helpers shared by the operation modules ----------

def require_columns(df, columns, at_least=0):
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"Οι στήλες δεν υπάρχουν: {', '.join(missing)}")
    if len(columns) < at_least:
        raise ValueError("Διάλεξε τουλάχιστον μία στήλη.")
    return list(columns)


def table(rows, title=None, columns=None):
    """rows: list of dicts or a DataFrame."""
    if isinstance(rows, pd.DataFrame):
        frame = rows
    else:
        frame = pd.DataFrame(rows, columns=columns)
    return {"type": "table", "title": title, "data": frame}


def cards(items, title=None):
    return {"type": "cards", "title": title, "items": [{"label": k, "value": v} for k, v in items]}


def text(content, title=None):
    return {"type": "text", "title": title, "content": content}


def bar(labels, values, title=None, unit=""):
    return {"type": "bar", "title": title, "labels": list(labels), "values": list(values), "unit": unit}


def histogram(series, bins=20, title=None):
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return text("Δεν υπάρχουν αριθμητικές τιμές.", title)
    counts, edges = np.histogram(values, bins=bins)
    return {"type": "histogram", "title": title, "column": str(series.name),
            "edges": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def box(frame, columns, title=None, max_outliers=40):
    items = []
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if values.empty:
            continue
        q1, median, q3 = (float(values.quantile(q)) for q in (0.25, 0.5, 0.75))
        low_fence, high_fence = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        inside = values[(values >= low_fence) & (values <= high_fence)]
        outliers = values[(values < low_fence) | (values > high_fence)]
        items.append({
            "label": str(column), "count": int(len(values)), "q1": q1, "median": median, "q3": q3,
            "whisker_low": float(inside.min()), "whisker_high": float(inside.max()),
            "min": float(values.min()), "max": float(values.max()),
            "outliers": [float(v) for v in outliers.sample(min(len(outliers), max_outliers), random_state=0)],
            "outlier_count": int(len(outliers)),
        })
    return {"type": "box", "title": title, "items": items}


def heatmap(matrix, title=None, diverging=False):
    """matrix: DataFrame with row/column labels."""
    values = matrix.to_numpy(dtype="float64")
    return {"type": "heatmap", "title": title, "x_labels": [str(c) for c in matrix.columns],
            "y_labels": [str(i) for i in matrix.index],
            "values": [[None if np.isnan(v) else round(float(v), 4) for v in row] for row in values],
            "diverging": diverging}


def scatter(x, y, title=None, limit=5000):
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    total = len(frame)
    if total > limit:
        frame = frame.sample(limit, random_state=0)
    return {"type": "scatter", "title": title, "x_label": str(x.name), "y_label": str(y.name),
            "points": frame.round(6).to_numpy().tolist(), "total": total, "sampled": total > limit}


def line(x_values, series, title=None, x_label=""):
    """series: {name: list of values aligned with x_values}."""
    return {"type": "line", "title": title, "x_label": x_label, "x": list(x_values),
            "series": [{"name": str(name), "values": list(values)} for name, values in series.items()]}


def downloads(files, title=None):
    """files: [{"label", "name", "size"}]; the frontend builds the URL from the session id."""
    return {"type": "downloads", "title": title, "files": files}
