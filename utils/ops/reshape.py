"""Reshape buttons: group-by, pivot, melt, transpose, merge with a second file."""

from typing import Literal

import pandas as pd
from pydantic import Field

from utils.op_registry import OpOutput, Params, cards, operation, require_columns
from utils.ops.fields import AGG_LABELS, Aggregation, aggregations_field, attachment_field, choice, column_field, columns_field
from utils.ops.inspect_ops import agg_spec
from utils.version_store import load_version


class GroupAggParams(Params):
    by: list[str] = columns_field("Ομαδοποίηση κατά", required=True)
    aggregations: list[Aggregation] = aggregations_field()


@operation(
    "reshape.groupby_agg", "Συνάθροιση (group-by)", "Ο πίνακας γίνεται μία γραμμή ανά ομάδα, π.χ. πωλήσεις ανά πόλη",
    "reshape", "transform", GroupAggParams,
    code=lambda p: f"df = df.groupby({p.by!r}, dropna=False).agg(**{agg_spec(p.aggregations)!r}).reset_index()",
)
def groupby_agg(df, p, ctx):
    require_columns(df, p.by + [a.column for a in p.aggregations], at_least=1)
    out = df.groupby(p.by, dropna=False).agg(**agg_spec(p.aggregations)).reset_index()
    return OpOutput(df=out, message=f"{len(df)} γραμμές → {len(out)} ομάδες")


class PivotParams(Params):
    index: list[str] = columns_field("Γραμμές (index)", required=True)
    columns: str = column_field("Στήλες από τις τιμές της")
    values: str = column_field("Τιμές")
    aggfunc: Literal["sum", "mean", "median", "min", "max", "count", "first"] = choice(
        "sum", "Συνάθροιση", {k: v for k, v in AGG_LABELS.items() if k in ("sum", "mean", "median", "min", "max", "count", "first")})
    fill_zero: bool = Field(False, title="Κενά → 0")
    max_new_columns: int = Field(200, ge=1, le=5000, title="Μέγιστες νέες στήλες")


@operation(
    "reshape.pivot", "Pivot", "pivot_table: οι τιμές μιας στήλης γίνονται στήλες (π.χ. μήνες σε στήλες)",
    "reshape", "transform", PivotParams,
    code=lambda p: (f"df = df.pivot_table(index={p.index!r}, columns={p.columns!r}, values={p.values!r}, "
                    f"aggfunc={p.aggfunc!r}{', fill_value=0' if p.fill_zero else ''}, observed=True).reset_index()\n"
                    f"df.columns = [str(c) for c in df.columns]"),
)
def pivot(df, p, ctx):
    require_columns(df, p.index + [p.columns, p.values], at_least=1)
    distinct = df[p.columns].nunique()
    if distinct > p.max_new_columns:
        raise ValueError(f"Η '{p.columns}' έχει {distinct} διαφορετικές τιμές — θα γίνονταν τόσες στήλες. Αύξησε το όριο ή διάλεξε άλλη.")
    kwargs = {"fill_value": 0} if p.fill_zero else {}
    out = df.pivot_table(index=p.index, columns=p.columns, values=p.values, aggfunc=p.aggfunc, observed=True, **kwargs).reset_index()
    out.columns = [str(c) for c in out.columns]
    return OpOutput(df=out, message=f"{out.shape[0]} γραμμές × {out.shape[1]} στήλες")


class MeltParams(Params):
    id_vars: list[str] = columns_field("Στήλες που μένουν (αναγνωριστικά)", required=True)
    value_vars: list[str] = columns_field("Στήλες που «λιώνουν»", "Κενό = όλες οι υπόλοιπες")
    var_name: str = Field("variable", title="Όνομα στήλης για τα παλιά ονόματα", min_length=1)
    value_name: str = Field("value", title="Όνομα στήλης για τις τιμές", min_length=1)


@operation(
    "reshape.melt", "Unpivot (melt)", "Στήλες → γραμμές: Ιαν, Φεβ, Μαρ → (μήνας, τιμή)",
    "reshape", "transform", MeltParams,
    code=lambda p: (f"df = df.melt(id_vars={p.id_vars!r}, value_vars={p.value_vars or None!r}, "
                    f"var_name={p.var_name!r}, value_name={p.value_name!r})"),
)
def melt(df, p, ctx):
    require_columns(df, p.id_vars + p.value_vars, at_least=1)
    out = df.melt(id_vars=p.id_vars, value_vars=p.value_vars or None, var_name=p.var_name, value_name=p.value_name)
    return OpOutput(df=out, message=f"{len(df)} γραμμές → {len(out)} γραμμές")


class TransposeParams(Params):
    header_column: str = column_field("Στήλη που γίνεται ονόματα στηλών")


@operation(
    "reshape.transpose", "Transpose", "Γραμμές ↔ στήλες (για μικρούς πίνακες-αναφορές)",
    "reshape", "transform", TransposeParams,
    code=lambda p: (f"df = df.set_index({p.header_column!r}).T.reset_index(names='field')\n"
                    f"df.columns = [str(c) for c in df.columns]"),
)
def transpose(df, p, ctx):
    require_columns(df, [p.header_column])
    if len(df) > 1000:
        raise ValueError("Το transpose θα έφτιαχνε πάνω από 1000 στήλες.")
    if df[p.header_column].duplicated().any():
        raise ValueError(f"Η '{p.header_column}' έχει διπλές τιμές· τα ονόματα στηλών πρέπει να είναι μοναδικά.")
    out = df.set_index(p.header_column).T.reset_index(names="field")
    out.columns = [str(c) for c in out.columns]
    return OpOutput(df=out, message=f"{out.shape[0]} γραμμές × {out.shape[1]} στήλες",
                    warnings=["Οι στήλες μετά το transpose είναι συνήθως κείμενο — τρέξε «Αυτόματοι τύποι»."])


HOW_LABELS = {
    "left": "Left — κράτα όλες τις γραμμές του τρέχοντος πίνακα",
    "inner": "Inner — μόνο όσες ταιριάζουν και στα δύο",
    "outer": "Outer — όλες από τα δύο",
    "right": "Right — όλες του δεύτερου αρχείου",
}


class MergeParams(Params):
    attachment: str = attachment_field()
    left_on: list[str] = columns_field("Κλειδιά στον τρέχοντα πίνακα", required=True)
    right_on: str = Field(title="Κλειδιά στο δεύτερο αρχείο (με κόμμα, ίδια σειρά)", min_length=1,
                          description="Κενό δεν επιτρέπεται· αν τα ονόματα είναι ίδια, γράψ' τα ξανά")
    how: Literal["left", "inner", "outer", "right"] = choice("left", "Τύπος join", HOW_LABELS)


def _right_keys(p):
    return [k.strip() for k in p.right_on.split(",") if k.strip()]


def _merge_code(p, ctx):
    from utils.code_gen import read_expression

    meta = ctx["attachments"][p.attachment]
    return (f"other = {read_expression(meta)}\n"
            f"df = df.merge(other, how={p.how!r}, left_on={p.left_on!r}, right_on={_right_keys(p)!r}, suffixes=('', '_2'))")


@operation(
    "reshape.merge", "Join με δεύτερο αρχείο", "Πρόσθεσε στήλες από άλλο αρχείο με κοινό κλειδί (VLOOKUP / SQL join)",
    "reshape", "transform", MergeParams, code=_merge_code,
)
def merge(df, p, ctx):
    attachments = ctx.get("attachments") or {}
    if p.attachment not in attachments:
        raise ValueError("Το δεύτερο αρχείο δεν υπάρχει στη συνεδρία — ανέβασέ το ξανά.")
    other = load_version(attachments[p.attachment]["data_path"])
    left_keys = require_columns(df, p.left_on, at_least=1)
    right_keys = _right_keys(p)
    missing = [k for k in right_keys if k not in other.columns]
    if missing:
        raise ValueError(f"Το δεύτερο αρχείο δεν έχει τις στήλες: {', '.join(missing)}. Έχει: {', '.join(map(str, other.columns[:20]))}")
    if len(right_keys) != len(left_keys):
        raise ValueError("Χρειάζεται ίδιος αριθμός κλειδιών και στα δύο αρχεία.")
    for left, right in zip(left_keys, right_keys):
        if pd.api.types.is_numeric_dtype(df[left]) != pd.api.types.is_numeric_dtype(other[right]):
            raise ValueError(f"Το '{left}' είναι {df[left].dtype} αλλά το '{right}' είναι {other[right].dtype}· "
                             "κάνε πρώτα τους τύπους ίδιους («→ Αριθμός» ή κείμενο).")
    probe = df.merge(other, how=p.how, left_on=left_keys, right_on=right_keys, suffixes=("", "_2"), indicator="_merge_status")
    counts = probe["_merge_status"].value_counts()
    out = probe.drop(columns="_merge_status")
    warnings = []
    if other.duplicated(subset=right_keys).any() and len(out) > len(df) and p.how in ("left", "inner"):
        warnings.append("Τα κλειδιά επαναλαμβάνονται στο δεύτερο αρχείο, οπότε κάποιες γραμμές πολλαπλασιάστηκαν.")
    return OpOutput(
        df=out, warnings=warnings,
        sections=[cards([
            ("Ταίριαξαν", int(counts.get("both", 0))),
            ("Μόνο στον τρέχοντα", int(counts.get("left_only", 0))),
            ("Μόνο στο δεύτερο", int(counts.get("right_only", 0))),
            ("Νέες στήλες", out.shape[1] - df.shape[1]),
        ], "Αποτέλεσμα join")],
        message=f"{len(df)} → {len(out)} γραμμές",
    )
