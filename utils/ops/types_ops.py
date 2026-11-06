"""Data type buttons."""

from typing import Literal

from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, require_columns, table
from utils.ops.fields import choice, columns_field
from utils.ops.helpers import auto_infer_types, convert_datetime, convert_numeric, downcast_numeric, to_boolean


class AutoInferParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες κειμένου")
    threshold: float = Field(0.95, ge=0.5, le=1.0, title="Ελάχιστο ποσοστό τιμών που πρέπει να μετατρέπονται")
    dayfirst: bool = Field(True, title="Ημερομηνίες με την ημέρα πρώτα (31/12/2024)")


@operation(
    "types.auto_infer", "Αυτόματοι τύποι",
    "Βρίσκει αριθμούς και ημερομηνίες που είναι αποθηκευμένα ως κείμενο και τα μετατρέπει",
    "types", "transform", AutoInferParams,
    code=lambda p: (f"df, _ = auto_infer_types(df, columns={p.columns or None!r}, "
                    f"threshold={p.threshold!r}, dayfirst={p.dayfirst!r})"),
)
def auto_infer(df, p, ctx):
    require_columns(df, p.columns)
    out, report = auto_infer_types(df, p.columns or None, p.threshold, p.dayfirst)
    if not report:
        return OpOutput(df=out, message="Δεν βρέθηκαν στήλες για μετατροπή.")
    return OpOutput(df=out, sections=[table(report, "Μετατροπές")], message=f"{len(report)} στήλες άλλαξαν τύπο")


def _failure_warnings(report):
    return [
        f"{r['column']}: {r['failed']} τιμές έγιναν κενές (π.χ. {r['examples']})"
        for r in report if r["failed"]
    ]


class ToNumericParams(Params):
    columns: list[str] = columns_field(required=True)
    decimal: Literal[".", ","] = choice(".", "Δεκαδικό σύμβολο", {".": "Τελεία (1,234.56)", ",": "Κόμμα (1.234,56)"})
    strip_symbols: bool = Field(True, title="Αφαίρεση €, $, %, κενών")


@operation(
    "types.to_numeric", "→ Αριθμός", "pd.to_numeric(errors='coerce'), με υποστήριξη ευρωπαϊκής μορφής",
    "types", "transform", ToNumericParams,
    code=lambda p: f"df, _ = convert_numeric(df, {p.columns!r}, decimal={p.decimal!r}, strip_symbols={p.strip_symbols!r})",
)
def to_numeric(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out, report = convert_numeric(df, columns, p.decimal, p.strip_symbols)
    return OpOutput(df=out, sections=[table(report, "Αποτέλεσμα")], warnings=_failure_warnings(report),
                    message=f"{len(columns)} στήλες μετατράπηκαν σε αριθμούς")


class ToDatetimeParams(Params):
    columns: list[str] = columns_field(required=True)
    format: str = Field("", title="Format (προαιρετικό)", description="π.χ. %d/%m/%Y — κενό για αυτόματη αναγνώριση")
    dayfirst: bool = Field(True, title="Η ημέρα πρώτα (31/12/2024)")


@operation(
    "types.to_datetime", "→ Ημερομηνία", "pd.to_datetime(errors='coerce')",
    "types", "transform", ToDatetimeParams,
    code=lambda p: f"df, _ = convert_datetime(df, {p.columns!r}, fmt={p.format or None!r}, dayfirst={p.dayfirst!r})",
)
def to_datetime(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out, report = convert_datetime(df, columns, p.format or None, p.dayfirst)
    return OpOutput(df=out, sections=[table(report, "Αποτέλεσμα")], warnings=_failure_warnings(report),
                    message=f"{len(columns)} στήλες μετατράπηκαν σε ημερομηνίες")


class ColumnsOnly(Params):
    columns: list[str] = columns_field(required=True)


@operation(
    "types.to_category", "→ Category", "astype('category'): λιγότερη μνήμη για επαναλαμβανόμενες τιμές",
    "types", "transform", ColumnsOnly,
    code=lambda p: f"df[{p.columns!r}] = df[{p.columns!r}].astype('category')",
)
def to_category(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out = df.copy()
    out[columns] = out[columns].astype("category")
    return OpOutput(df=out, message=f"{len(columns)} στήλες έγιναν category")


@operation(
    "types.to_bool", "→ Boolean", "ναι/όχι, yes/no, true/false, 1/0 → True/False",
    "types", "transform", ColumnsOnly,
    code=lambda p: f"df, _ = to_boolean(df, {p.columns!r})",
)
def to_bool(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out, report = to_boolean(df, columns)
    warnings = [f"{r['column']}: {r['failed']} τιμές δεν αναγνωρίστηκαν και έγιναν κενές" for r in report if r["failed"]]
    return OpOutput(df=out, sections=[table(report)], warnings=warnings, message=f"{len(columns)} στήλες έγιναν boolean")


class DowncastParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες")


@operation(
    "types.downcast", "Μείωση μνήμης", "int64 → int8/16/32, float64 → float32, κείμενο με λίγες τιμές → category",
    "types", "transform", DowncastParams,
    code=lambda p: f"df, _ = downcast_numeric(df, {p.columns or None!r})",
)
def downcast(df, p, ctx):
    require_columns(df, p.columns)
    out, report = downcast_numeric(df, p.columns or None)
    saved = sum(r["saved_kb"] for r in report)
    return OpOutput(df=out, sections=[table(report)] if report else [], message=f"Εξοικονόμηση {saved:.1f} KB σε {len(report)} στήλες")
