"""Categorical encoding buttons."""

from typing import Literal

import pandas as pd
from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, require_columns, table
from utils.ops.fields import choice, column_field, columns_field
from utils.ops.helpers import column_kind, group_rare, label_encode, ordinal_encode, standardize_labels


class OneHotParams(Params):
    columns: list[str] = columns_field(required=True)
    drop_first: bool = Field(False, title="drop_first (μία στήλη λιγότερη ανά κατηγορία)")
    dummy_na: bool = Field(False, title="Στήλη και για τα κενά")
    max_categories: int = Field(50, ge=2, le=1000, title="Μέγιστες κατηγορίες ανά στήλη")


@operation(
    "categorical.one_hot", "One-hot encoding", "pd.get_dummies(): μία στήλη 0/1 ανά κατηγορία",
    "categorical", "transform", OneHotParams,
    code=lambda p: (f"df = pd.get_dummies(df, columns={p.columns!r}, drop_first={p.drop_first!r}, "
                    f"dummy_na={p.dummy_na!r}, dtype=int)"),
)
def one_hot(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    too_many = {c: int(df[c].nunique()) for c in columns if df[c].nunique() > p.max_categories}
    if too_many:
        detail = ", ".join(f"{c} ({n})" for c, n in too_many.items())
        raise ValueError(f"Πάρα πολλές κατηγορίες: {detail}. Αύξησε το όριο ή χρησιμοποίησε label encoding.")
    out = pd.get_dummies(df, columns=columns, drop_first=p.drop_first, dummy_na=p.dummy_na, dtype=int)
    added = [c for c in out.columns if c not in df.columns]
    return OpOutput(df=out, message=f"{len(columns)} στήλες → {len(added)} νέες στήλες 0/1")


class LabelParams(Params):
    columns: list[str] = columns_field(required=True)
    order: Literal["alphabetical", "frequency"] = choice(
        "alphabetical", "Σειρά κωδικών", {"alphabetical": "Αλφαβητική", "frequency": "Συχνότερη πρώτα"})


@operation(
    "categorical.label", "Label encoding", "Κάθε κατηγορία → ακέραιος (0, 1, 2…)· τα κενά μένουν κενά",
    "categorical", "transform", LabelParams,
    code=lambda p: f"df, _ = label_encode(df, {p.columns!r}, order={p.order!r})",
)
def label(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out, mappings = label_encode(df, columns, p.order)
    rows = [
        {"στήλη": column, "τιμή": str(value), "κωδικός": code}
        for column, mapping in mappings.items()
        for value, code in list(mapping.items())[:50]
    ]
    return OpOutput(df=out, sections=[table(rows, "Αντιστοίχιση")], message=f"{len(columns)} στήλες κωδικοποιήθηκαν")


class OrdinalParams(Params):
    column: str = column_field()
    order: str = Field(title="Σειρά τιμών, από τη μικρότερη (με κόμμα)", min_length=1,
                       description="π.χ. χαμηλή, μεσαία, υψηλή → 0, 1, 2")
    name: str = Field("", title="Όνομα νέας στήλης", description="Κενό = αντικατάσταση της στήλης")


def _order(p):
    return [v.strip() for v in p.order.split(",") if v.strip()]


@operation(
    "categorical.ordinal", "Ordinal encoding", "Κατηγορίες με φυσική σειρά → 0, 1, 2… με τη σειρά που ορίζεις",
    "categorical", "transform", OrdinalParams,
    code=lambda p: f"df, _ = ordinal_encode(df, {p.column!r}, {_order(p)!r}, name={p.name or None!r})",
)
def ordinal(df, p, ctx):
    require_columns(df, [p.column])
    out, unknown = ordinal_encode(df, p.column, _order(p), p.name or None)
    warnings = [f"Τιμές εκτός σειράς (έγιναν κενές): {', '.join(unknown[:15])}"] if unknown else []
    return OpOutput(df=out, warnings=warnings, message=f"{len(_order(p))} επίπεδα κωδικοποιήθηκαν")


class BinaryParams(Params):
    column: str = column_field()
    positive: str = Field(title="Τιμή που γίνεται 1", min_length=1, description="Όλες οι άλλες (μη κενές) γίνονται 0")


@operation(
    "categorical.binary_map", "Binary (0/1)", "Μία τιμή → 1, οι υπόλοιπες → 0 (π.χ. Ενεργός = 1)",
    "categorical", "transform", BinaryParams,
    code=lambda p: (f"df[{p.column!r}] = (df[{p.column!r}].astype('string').str.strip() == {p.positive!r})"
                    f".astype('Int64').where(df[{p.column!r}].notna())"),
)
def binary_map(df, p, ctx):
    require_columns(df, [p.column])
    series = df[p.column]
    hits = series.astype("string").str.strip() == p.positive
    if not hits.fillna(False).any():
        examples = ", ".join(map(str, series.dropna().unique()[:8]))
        raise ValueError(f"Η τιμή '{p.positive}' δεν υπάρχει στη στήλη. Υπάρχουν: {examples}")
    out = df.copy()
    out[p.column] = hits.astype("Int64").where(series.notna())
    return OpOutput(df=out, message=f"1: {int(out[p.column].sum())} · 0: {int((out[p.column] == 0).sum())}")


class FrequencyParams(Params):
    columns: list[str] = columns_field(required=True)
    normalize: bool = Field(False, title="Ως ποσοστό (0–1) αντί για πλήθος")
    suffix: str = Field("_freq", title="Επίθημα νέας στήλης", description="Κενό = αντικατάσταση")


@operation(
    "categorical.frequency", "Frequency encoding", "Κάθε κατηγορία → πόσο συχνά εμφανίζεται",
    "categorical", "transform", FrequencyParams,
    code=lambda p: "\n".join(
        f"df[{c + p.suffix!r}] = df[{c!r}].map(df[{c!r}].value_counts(normalize={p.normalize!r}))" for c in p.columns),
)
def frequency(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out = df.copy()
    for c in columns:
        out[c + p.suffix] = out[c].map(out[c].value_counts(normalize=p.normalize))
    return OpOutput(df=out, message=f"{len(columns)} στήλες κωδικοποιήθηκαν")


class RareParams(Params):
    columns: list[str] = columns_field(required=True)
    min_pct: float = Field(1.0, gt=0, le=50, title="Κατηγορίες κάτω από %")
    other: str = Field("Other", title="Νέα ετικέτα", min_length=1)


@operation(
    "categorical.rare_group", "Σπάνιες → «Other»", "Ενώνει τις σπάνιες κατηγορίες πριν από one-hot",
    "categorical", "transform", RareParams,
    code=lambda p: f"df, _ = group_rare(df, {p.columns!r}, min_pct={p.min_pct!r}, other={p.other!r})",
)
def rare_group(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out, report = group_rare(df, columns, p.min_pct, p.other)
    return OpOutput(df=out, sections=[table(report)], message=f"Ενώθηκαν {sum(r['grouped_categories'] for r in report)} κατηγορίες")


class LabelsParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες κειμένου")


@operation(
    "categorical.standardize_labels", "Ενοποίηση ετικετών", "«αθήνα », «ΑΘΗΝΑ», «Αθηνα» → «Αθήνα» (η συχνότερη γραφή)",
    "categorical", "transform", LabelsParams,
    code=lambda p: f"df, _ = standardize_labels(df, {p.columns or None!r} or [c for c in df.columns if column_kind(df[c]) == 'text'])",
)
def standardize(df, p, ctx):
    columns = require_columns(df, p.columns) or [c for c in df.columns if column_kind(df[c]) == "text"]
    out, report = standardize_labels(df, columns)
    merged = sum(r["merged_variants"] for r in report)
    return OpOutput(df=out, sections=[table([r for r in report if r["merged_variants"]])] if merged else [],
                    message=f"Ενοποιήθηκαν {merged} παραλλαγές")
