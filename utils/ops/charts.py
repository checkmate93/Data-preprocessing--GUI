"""Chart buttons. The backend sends data (bins, quartiles, points), the React side draws SVG."""

from typing import Literal

import pandas as pd
from pydantic import Field

from utils.op_registry import OpOutput, Params, bar, box, histogram, line, operation, require_columns, scatter, text
from utils.ops.fields import AGG_LABELS, choice, column_field, columns_field, optional_column_field
from utils.ops.helpers import column_kind, to_datetime_safe


def _numeric(df, columns):
    wrong = [c for c in columns if column_kind(df[c]) != "numeric"]
    if wrong:
        raise ValueError(f"Δεν είναι αριθμητικές: {', '.join(wrong)} — τρέξε πρώτα «→ Αριθμός».")


class HistogramParams(Params):
    column: str = column_field()
    bins: int = Field(20, ge=2, le=200, title="Κάδοι")


@operation("charts.histogram", "Histogram", "Κατανομή μιας αριθμητικής στήλης", "charts", "inspect", HistogramParams)
def histogram_chart(df, p, ctx):
    require_columns(df, [p.column])
    _numeric(df, [p.column])
    return OpOutput(sections=[histogram(df[p.column], p.bins, f"Κατανομή — {p.column}")])


class BoxParams(Params):
    columns: list[str] = columns_field(required=True)
    by: str = optional_column_field("Ανά κατηγορία (προαιρετικό)", "Ένα κουτί ανά τιμή της στήλης· μόνο με μία αριθμητική στήλη")


@operation("charts.boxplot", "Boxplot", "Διάμεσος, τεταρτημόρια και outliers — και σύγκριση ανά κατηγορία", "charts", "inspect", BoxParams)
def boxplot(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    _numeric(df, columns)
    if p.by:
        require_columns(df, [p.by])
        if len(columns) != 1:
            raise ValueError("Με «ανά κατηγορία» διάλεξε μία αριθμητική στήλη.")
        top = df[p.by].value_counts().head(15).index
        wide = pd.DataFrame({str(k): df.loc[df[p.by] == k, columns[0]].reset_index(drop=True) for k in top})
        return OpOutput(sections=[box(wide, list(wide.columns), f"{columns[0]} ανά {p.by}")])
    return OpOutput(sections=[box(df, columns, "Boxplot")])


class BarParams(Params):
    column: str = column_field("Κατηγορία")
    value: str = optional_column_field("Τιμή (προαιρετικό)", "Κενό = πλήθος γραμμών")
    agg: Literal["sum", "mean", "median", "min", "max"] = choice(
        "sum", "Συνάθροιση τιμής", {k: AGG_LABELS[k] for k in ("sum", "mean", "median", "min", "max")})
    top: int = Field(20, ge=1, le=100, title="Πόσες κατηγορίες")


@operation("charts.bar", "Bar chart", "Πλήθος ή άθροισμα ανά κατηγορία (π.χ. πωλήσεις ανά πόλη)", "charts", "inspect", BarParams)
def bar_chart(df, p, ctx):
    require_columns(df, [p.column] + ([p.value] if p.value else []))
    if p.value:
        _numeric(df, [p.value])
        series = df.groupby(p.column, dropna=False)[p.value].agg(p.agg).sort_values(ascending=False)
        title = f"{AGG_LABELS[p.agg]} {p.value} ανά {p.column}"
    else:
        series = df[p.column].value_counts(dropna=False)
        title = f"Γραμμές ανά {p.column}"
    shown = series.head(p.top)
    labels = ["(κενό)" if pd.isna(i) else str(i) for i in shown.index]
    sections = [bar(labels, [round(float(v), 4) for v in shown.values], title)]
    if len(series) > p.top:
        sections.append(text(f"Εμφανίζονται {p.top} από {len(series)} κατηγορίες."))
    return OpOutput(sections=sections)


class ScatterParams(Params):
    x: str = column_field("Άξονας X")
    y: str = column_field("Άξονας Y")


@operation("charts.scatter", "Scatter", "Σχέση δύο αριθμητικών στηλών (έως 5.000 σημεία)", "charts", "inspect", ScatterParams)
def scatter_chart(df, p, ctx):
    require_columns(df, [p.x, p.y])
    _numeric(df, [p.x, p.y])
    r = df[[p.x, p.y]].astype("float64").corr().iloc[0, 1]
    title = f"{p.y} vs {p.x}" + (f" · r = {r:.3f}" if pd.notna(r) else "")
    return OpOutput(sections=[scatter(df[p.x], df[p.y], title)])


class LineParams(Params):
    x: str = column_field("Άξονας X (ημερομηνία ή αριθμός)")
    y: list[str] = columns_field("Τιμές", required=True)
    freq: Literal["none", "D", "W", "M", "Q", "Y"] = choice(
        "M", "Ομαδοποίηση ημερομηνιών", {"none": "Καμία", "D": "Ημέρα", "W": "Εβδομάδα", "M": "Μήνας", "Q": "Τρίμηνο", "Y": "Έτος"})
    agg: Literal["sum", "mean", "count", "median", "max", "min"] = choice(
        "sum", "Συνάθροιση", {k: AGG_LABELS[k] for k in ("sum", "mean", "count", "median", "max", "min")})


@operation("charts.line", "Line chart", "Εξέλιξη στον χρόνο (π.χ. πωλήσεις ανά μήνα)", "charts", "inspect", LineParams)
def line_chart(df, p, ctx):
    y = require_columns(df, p.y, at_least=1)
    require_columns(df, [p.x])
    _numeric(df, y)
    frame = df[[p.x, *y]].copy()
    if column_kind(frame[p.x]) in ("datetime", "text"):
        frame[p.x] = to_datetime_safe(frame[p.x])
        frame = frame.dropna(subset=[p.x])
        if frame.empty:
            raise ValueError(f"Η '{p.x}' δεν περιέχει ημερομηνίες.")
        if p.freq != "none":
            frame[p.x] = frame[p.x].dt.to_period({"W": "W-SUN"}.get(p.freq, p.freq)).dt.start_time
    grouped = frame.groupby(p.x)[y].agg(p.agg).sort_index()
    if len(grouped) > 2000:
        grouped = grouped.iloc[:: len(grouped) // 2000 + 1]
    x_values = [i.strftime("%Y-%m-%d") if hasattr(i, "strftime") else i for i in grouped.index]
    series = {c: [None if pd.isna(v) else round(float(v), 4) for v in grouped[c]] for c in y}
    return OpOutput(sections=[line(x_values, series, f"{AGG_LABELS[p.agg]} ανά {p.x}", p.x)])
