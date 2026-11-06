"""Numeric buttons."""

from typing import Literal

from pydantic import Field

from utils.op_registry import OpOutput, Params, bar, operation, require_columns, table
from utils.ops.fields import choice, column_field, columns_field, optional_column_field
from utils.ops.helpers import (
    bin_column,
    clip_outliers,
    column_formula,
    column_kind,
    remove_outliers,
    scale_columns,
    transform_numeric,
)


class ClipParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι αριθμητικές στήλες")
    method: Literal["iqr", "percentile"] = choice(
        "iqr", "Μέθοδος", {"iqr": "IQR (Q1 − k·IQR, Q3 + k·IQR)", "percentile": "Εκατοστημόρια"})
    factor: float = Field(1.5, gt=0, le=10, title="k για IQR")
    lower_pct: float = Field(1.0, ge=0, le=50, title="Κάτω εκατοστημόριο")
    upper_pct: float = Field(99.0, ge=50, le=100, title="Άνω εκατοστημόριο")


@operation(
    "numeric.outliers_clip", "Outliers → όρια", "Οι ακραίες τιμές κόβονται στα όρια (clip)",
    "numeric", "transform", ClipParams,
    code=lambda p: (f"df, _ = clip_outliers(df, columns={p.columns or None!r}, method={p.method!r}, "
                    f"factor={p.factor!r}, lower_pct={p.lower_pct!r}, upper_pct={p.upper_pct!r})"),
)
def outliers_clip(df, p, ctx):
    require_columns(df, p.columns)
    out, report = clip_outliers(df, p.columns or None, p.method, p.factor, p.lower_pct, p.upper_pct)
    total = sum(r["clipped"] for r in report)
    return OpOutput(df=out, sections=[table(report, "Όρια ανά στήλη")] if report else [],
                    message=f"{total} τιμές κόπηκαν στα όρια")


def _numeric_columns(df, columns, at_least=0):
    columns = require_columns(df, columns, at_least) or [c for c in df.columns if column_kind(df[c]) == "numeric"]
    wrong = [c for c in columns if column_kind(df[c]) != "numeric"]
    if wrong:
        raise ValueError(f"Δεν είναι αριθμητικές: {', '.join(wrong)} — τρέξε πρώτα «→ Αριθμός».")
    return columns


class RemoveOutliersParams(Params):
    columns: list[str] = columns_field(required=True)
    method: Literal["iqr", "zscore"] = choice("iqr", "Μέθοδος", {"iqr": "IQR", "zscore": "z-score"})
    factor: float = Field(1.5, gt=0, le=10, title="k για IQR")
    z: float = Field(3.0, gt=0, le=10, title="Όριο |z|")


@operation(
    "numeric.outliers_remove", "Outliers → διαγραφή γραμμών", "Αφαιρεί τις γραμμές με ακραίες τιμές",
    "numeric", "transform", RemoveOutliersParams,
    code=lambda p: f"df, _ = remove_outliers(df, {p.columns!r}, method={p.method!r}, factor={p.factor!r}, z={p.z!r})",
)
def outliers_remove(df, p, ctx):
    columns = _numeric_columns(df, p.columns, at_least=1)
    out, report = remove_outliers(df, columns, p.method, p.factor, p.z)
    removed = len(df) - len(out)
    warnings = [f"Διαγράφηκε το {removed / len(df) * 100:.1f}% των γραμμών."] if len(df) and removed / len(df) > 0.05 else []
    return OpOutput(df=out, sections=[table(report)], warnings=warnings, message=f"Διαγράφηκαν {removed} γραμμές")


class RoundParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι αριθμητικές")
    decimals: int = Field(2, ge=-6, le=10, title="Δεκαδικά (αρνητικό = δεκάδες/εκατοντάδες)")


@operation(
    "numeric.round", "Στρογγυλοποίηση", "round(n)",
    "numeric", "transform", RoundParams,
    code=lambda p: (f"df[{p.columns!r}] = df[{p.columns!r}].round({p.decimals!r})" if p.columns
                    else f"df = df.round({p.decimals!r})"),
)
def round_values(df, p, ctx):
    columns = _numeric_columns(df, p.columns)
    out = df.copy()
    out[columns] = out[columns].round(p.decimals)
    return OpOutput(df=out, message=f"{len(columns)} στήλες στρογγυλοποιήθηκαν σε {p.decimals} δεκαδικά")


class TransformParams(Params):
    columns: list[str] = columns_field(required=True)
    method: Literal["log1p", "sqrt", "boxcox", "yeojohnson"] = choice(
        "log1p", "Μετασχηματισμός",
        {"log1p": "log(1+x) — για θετικές skewed", "sqrt": "Τετραγωνική ρίζα", "boxcox": "Box-Cox (μόνο θετικές)", "yeojohnson": "Yeo-Johnson (και αρνητικές)"})
    suffix: str = Field("_log", title="Επίθημα νέας στήλης", description="Κενό = αντικατάσταση της στήλης")


@operation(
    "numeric.transform", "Log / Box-Cox", "Μειώνει την ασυμμετρία (skew) — δείχνει skew πριν/μετά",
    "numeric", "transform", TransformParams,
    code=lambda p: f"df, _ = transform_numeric(df, {p.columns!r}, method={p.method!r}, suffix={p.suffix!r})",
)
def transform(df, p, ctx):
    columns = _numeric_columns(df, p.columns, at_least=1)
    out, report = transform_numeric(df, columns, p.method, p.suffix)
    return OpOutput(df=out, sections=[table(report, "Skew")], message=f"{len(columns)} στήλες μετασχηματίστηκαν")


class BinParams(Params):
    column: str = column_field()
    method: Literal["equal", "quantile", "custom"] = choice(
        "quantile", "Μέθοδος", {"equal": "Ίσα διαστήματα (cut)", "quantile": "Ίσο πλήθος ανά ομάδα (qcut)", "custom": "Δικά μου όρια"})
    bins: int = Field(4, ge=2, le=50, title="Πλήθος ομάδων")
    edges: str = Field("", title="Όρια (για «Δικά μου»)", description="π.χ. 0, 18, 35, 65, 120")
    labels: str = Field("", title="Ετικέτες (προαιρετικό, με κόμμα)", description="π.χ. παιδί, νέος, ενήλικας, senior")
    name: str = Field("", title="Όνομα νέας στήλης", description="Κενό = <στήλη>_bin")


def _numbers(text_value):
    return [float(v) for v in text_value.split(",") if v.strip()]


def _labels(text_value):
    return [v.strip() for v in text_value.split(",") if v.strip()] or None


@operation(
    "numeric.binning", "Κατηγοριοποίηση (bins)", "Αριθμός → ομάδα: pd.cut / pd.qcut",
    "numeric", "transform", BinParams,
    code=lambda p: (f"df = bin_column(df, {p.column!r}, method={p.method!r}, bins={p.bins!r}, "
                    f"edges={_numbers(p.edges) if p.method == 'custom' else None!r}, labels={_labels(p.labels)!r}, name={p.name or None!r})"),
)
def binning(df, p, ctx):
    _numeric_columns(df, [p.column], at_least=1)
    edges = _numbers(p.edges) if p.method == "custom" else None
    labels = _labels(p.labels)
    if p.method == "custom" and (not edges or len(edges) < 2):
        raise ValueError("Δώσε τουλάχιστον δύο όρια, π.χ. 0, 18, 65, 120")
    expected = (len(edges) - 1) if edges else p.bins
    if labels and len(labels) != expected:
        raise ValueError(f"Χρειάζονται {expected} ετικέτες, δόθηκαν {len(labels)}.")
    out = bin_column(df, p.column, p.method, p.bins, edges, labels, p.name or None)
    name = p.name or f"{p.column}_bin"
    counts = out[name].value_counts(dropna=False).sort_index()
    return OpOutput(df=out, sections=[bar([str(i) for i in counts.index], counts.tolist(), "Γραμμές ανά ομάδα")],
                    message=f"Νέα στήλη {name} με {out[name].nunique()} ομάδες")


class ScaleParams(Params):
    columns: list[str] = columns_field(required=True)
    method: Literal["standard", "minmax", "robust"] = choice(
        "standard", "Μέθοδος", {"standard": "Standard (mean 0, std 1)", "minmax": "Min-Max (0–1)", "robust": "Robust (median, IQR)"})


@operation(
    "numeric.scale", "Κλιμάκωση", "StandardScaler / MinMax / Robust",
    "numeric", "transform", ScaleParams,
    code=lambda p: f"df, _ = scale_columns(df, {p.columns!r}, method={p.method!r})",
)
def scale(df, p, ctx):
    columns = _numeric_columns(df, p.columns, at_least=1)
    out, report = scale_columns(df, columns, p.method)
    return OpOutput(df=out, sections=[table(report, "Παράμετροι")], message=f"{len(columns)} στήλες κλιμακώθηκαν",
                    warnings=["Η κλιμάκωση έγινε σε όλο το dataset. Για μοντέλα χρησιμοποίησε το «ML Prep» (fit μόνο στο train)."])


class FormulaParams(Params):
    left: str = column_field("Στήλη Α")
    operator: Literal["+", "-", "*", "/", "%"] = choice(
        "*", "Πράξη", {"+": "Α + Β", "-": "Α − Β", "*": "Α × Β", "/": "Α ÷ Β", "%": "Α ως % του Β"})
    right: str = optional_column_field("Στήλη Β", "Κενό = χρησιμοποίησε τη σταθερά")
    constant: float | None = Field(None, title="Σταθερά Β")
    name: str = Field(title="Όνομα νέας στήλης", min_length=1)


@operation(
    "numeric.formula", "Νέα στήλη από πράξη", "π.χ. τιμή × τεμάχια = σύνολο (δομημένη φόρμα, όχι ελεύθερος κώδικας)",
    "numeric", "transform", FormulaParams,
    code=lambda p: (f"df = column_formula(df, {p.left!r}, {p.operator!r}, right={p.right or None!r}, "
                    f"constant={p.constant!r}, name={p.name!r})"),
)
def formula(df, p, ctx):
    _numeric_columns(df, [p.left] + ([p.right] if p.right else []), at_least=1)
    if not p.right and p.constant is None:
        raise ValueError("Δώσε Στήλη Β ή σταθερά.")
    if p.name in df.columns:
        raise ValueError(f"Η στήλη '{p.name}' υπάρχει ήδη.")
    out = column_formula(df, p.left, p.operator, p.right or None, p.constant, p.name)
    return OpOutput(df=out, message=f"Νέα στήλη {p.name} · κενές {int(out[p.name].isna().sum())}")
