"""Date buttons."""

from typing import Literal

from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, require_columns
from utils.ops.fields import choice, column_field, optional_column_field
from utils.ops.helpers import column_kind, date_difference, extract_date_parts, to_datetime_safe

PART_LABELS = {
    "year": "Έτος", "quarter": "Τρίμηνο", "month": "Μήνας", "week": "Εβδομάδα (ISO)", "day": "Ημέρα",
    "weekday": "Ημέρα εβδομάδας (0=Δευτέρα)", "hour": "Ώρα", "is_weekend": "Σαββατοκύριακο (0/1)",
}
Part = Literal["year", "quarter", "month", "week", "day", "weekday", "hour", "is_weekend"]


class ExtractParams(Params):
    column: str = column_field("Στήλη ημερομηνίας")
    parts: list[Part] = Field(
        default=["year", "month", "day", "weekday"], title="Τι να εξαχθεί", min_length=1,
        json_schema_extra={"ui": "multienum", "enum_labels": PART_LABELS})
    dayfirst: bool = Field(True, title="Η ημέρα πρώτα (αν η στήλη είναι κείμενο)")


@operation(
    "datetime.extract_parts", "Ανάλυση ημερομηνίας", "Νέες στήλες: έτος, μήνας, ημέρα, ημέρα εβδομάδας…",
    "datetime", "transform", ExtractParams,
    code=lambda p: f"df, _ = extract_date_parts(df, {p.column!r}, {list(p.parts)!r}, dayfirst={p.dayfirst!r})",
)
def extract_parts(df, p, ctx):
    require_columns(df, [p.column])
    warnings = []
    if column_kind(df[p.column]) != "datetime":
        warnings.append(f"Η '{p.column}' δεν είναι ημερομηνία· μετατράπηκε προσωρινά για τον υπολογισμό.")
    out, created = extract_date_parts(df, p.column, list(p.parts), p.dayfirst)
    return OpOutput(df=out, warnings=warnings, message=f"Νέες στήλες: {', '.join(created)}")


class DiffParams(Params):
    start: str = column_field("Από (ημερομηνία)")
    end: str = optional_column_field("Έως (ημερομηνία)", "Κενό = σήμερα")
    unit: Literal["days", "weeks", "months", "years"] = choice(
        "days", "Μονάδα", {"days": "Ημέρες", "weeks": "Εβδομάδες", "months": "Μήνες", "years": "Έτη"})
    name: str = Field("", title="Όνομα νέας στήλης", description="Κενό = <από>_<μονάδα>")
    dayfirst: bool = Field(True, title="Η ημέρα πρώτα (αν είναι κείμενο)")


@operation(
    "datetime.diff", "Διαφορά ημερομηνιών", "Ημέρες/μήνες/έτη ανάμεσα σε δύο στήλες ή μέχρι σήμερα (π.χ. ηλικία, παλαιότητα)",
    "datetime", "transform", DiffParams,
    code=lambda p: (f"df = date_difference(df, {p.start!r}, {p.end or None!r}, unit={p.unit!r}, "
                    f"name={p.name or None!r}, dayfirst={p.dayfirst!r})"),
)
def diff(df, p, ctx):
    require_columns(df, [p.start] + ([p.end] if p.end else []))
    out = date_difference(df, p.start, p.end or None, p.unit, p.name or None, p.dayfirst)
    name = p.name or f"{p.start}_{p.unit}"
    warnings = [] if p.end else ["Χωρίς «Έως» η διαφορά υπολογίζεται ως σήμερα — αν ξανατρέξει άλλη μέρα, θα αλλάξει."]
    return OpOutput(df=out, warnings=warnings, message=f"Νέα στήλη {name} · κενές {int(out[name].isna().sum())}")


class FloorParams(Params):
    column: str = column_field()
    freq: Literal["D", "W", "M", "Q", "Y"] = choice(
        "M", "Στρογγυλοποίηση σε", {"D": "Ημέρα", "W": "Εβδομάδα (Δευτέρα)", "M": "Μήνα", "Q": "Τρίμηνο", "Y": "Έτος"})
    name: str = Field("", title="Όνομα νέας στήλης", description="Κενό = αντικατάσταση της ίδιας στήλης")


def _period(freq):
    return {"W": "W-SUN", "Y": "Y"}.get(freq, freq)


@operation(
    "datetime.floor", "Στρογγυλοποίηση ημερομηνίας", "2025-03-17 → 2025-03-01 (μήνας): για ομαδοποιήσεις ανά περίοδο",
    "datetime", "transform", FloorParams,
    code=lambda p: (f"df[{p.name or p.column!r}] = to_datetime_safe(df[{p.column!r}])"
                    f".dt.to_period({_period(p.freq)!r}).dt.start_time"),
)
def floor(df, p, ctx):
    require_columns(df, [p.column])
    out = df.copy()
    out[p.name or p.column] = to_datetime_safe(out[p.column]).dt.to_period(_period(p.freq)).dt.start_time
    return OpOutput(df=out, message=f"{out[p.name or p.column].nunique()} διαφορετικές περίοδοι")
