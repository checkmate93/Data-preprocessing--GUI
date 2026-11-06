"""Column name and structure buttons."""

from typing import Literal

from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, require_columns, table
from utils.ops.fields import choice, column_field, columns_field
from utils.ops.helpers import drop_columns_by_rule, promote_header, snake_case_columns


class SnakeParams(Params):
    transliterate: bool = Field(True, title="Ελληνικά → λατινικοί χαρακτήρες (Όνομα → onoma)")


@operation(
    "columns.snake_case", "snake_case ονόματα",
    "Μικρά γράμματα, χωρίς τόνους/κενά/σύμβολα: 'Customer ID' → customer_id",
    "columns", "transform", SnakeParams,
    code=lambda p: f"df, _ = snake_case_columns(df, transliterate={p.transliterate!r})",
)
def snake_case(df, p, ctx):
    out, changes = snake_case_columns(df, transliterate=p.transliterate)
    sections = [table(changes, "Μετονομασίες", columns=["from", "to"])] if changes else []
    return OpOutput(df=out, sections=sections, message=f"{len(changes)} στήλες μετονομάστηκαν")


class RenameParams(Params):
    mapping: dict[str, str] = Field(
        default_factory=dict, title="Νέα ονόματα", json_schema_extra={"ui": "rename_map"})


@operation(
    "columns.rename", "Μετονομασία", "Άλλαξε το όνομα συγκεκριμένων στηλών",
    "columns", "transform", RenameParams,
    code=lambda p: f"df = df.rename(columns={ {k: v for k, v in p.mapping.items() if v.strip()}!r})",
)
def rename(df, p, ctx):
    mapping = {old: new.strip() for old, new in p.mapping.items() if new.strip() and new.strip() != old}
    if not mapping:
        raise ValueError("Δεν δόθηκε κανένα νέο όνομα.")
    require_columns(df, list(mapping))
    result_names = [mapping.get(c, c) for c in df.columns]
    clashes = sorted({n for n in result_names if result_names.count(n) > 1})
    if clashes:
        raise ValueError(f"Μετά τη μετονομασία θα υπήρχαν διπλά ονόματα: {', '.join(clashes)}")
    out = df.rename(columns=mapping)
    rows = [{"from": k, "to": v} for k, v in mapping.items()]
    return OpOutput(df=out, sections=[table(rows, "Μετονομασίες")], message=f"{len(mapping)} στήλες μετονομάστηκαν")


class DropParams(Params):
    columns: list[str] = columns_field("Στήλες προς διαγραφή", required=True)


@operation(
    "columns.drop", "Διαγραφή στηλών", "Αφαίρεσε στήλες που δεν χρειάζεσαι",
    "columns", "transform", DropParams,
    code=lambda p: f"df = df.drop(columns={p.columns!r})",
)
def drop(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    if len(columns) == df.shape[1]:
        raise ValueError("Δεν γίνεται να διαγραφούν όλες οι στήλες.")
    return OpOutput(df=df.drop(columns=columns), message=f"Διαγράφηκαν {len(columns)} στήλες: {', '.join(columns)}")


class DropRuleParams(Params):
    max_missing_pct: float = Field(60.0, ge=0, le=100, title="Διαγραφή στηλών με κενά πάνω από %")
    drop_constant: bool = Field(True, title="Διαγραφή σταθερών στηλών (μία τιμή)")
    drop_id_like: bool = Field(False, title="Διαγραφή στηλών-ID (μοναδική τιμή ανά γραμμή)")


@operation(
    "columns.drop_by_rule", "Διαγραφή με κανόνα", "Αφαιρεί στήλες με πολλά κενά, σταθερές ή ID",
    "columns", "transform", DropRuleParams,
    code=lambda p: (f"df, _ = drop_columns_by_rule(df, max_missing_pct={p.max_missing_pct!r}, "
                    f"drop_constant={p.drop_constant!r}, drop_id_like={p.drop_id_like!r})"),
)
def drop_by_rule(df, p, ctx):
    out, dropped = drop_columns_by_rule(df, p.max_missing_pct, p.drop_constant, p.drop_id_like)
    if out.shape[1] == 0:
        raise ValueError("Ο κανόνας θα διέγραφε όλες τις στήλες.")
    return OpOutput(df=out, sections=[table(dropped, "Διαγράφηκαν")] if dropped else [],
                    message=f"Διαγράφηκαν {len(dropped)} στήλες")


class PrefixParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες")
    prefix: str = Field("", title="Πρόθεμα")
    suffix: str = Field("", title="Επίθημα")


@operation(
    "columns.prefix_suffix", "Πρόθεμα / επίθημα", "π.χ. πριν από join: τιμή → crm_τιμή",
    "columns", "transform", PrefixParams,
    code=lambda p: (f"df = df.rename(columns={{c: {p.prefix!r} + c + {p.suffix!r} "
                    f"for c in {p.columns or None!r} or df.columns}})"),
)
def prefix_suffix(df, p, ctx):
    if not p.prefix and not p.suffix:
        raise ValueError("Δώσε πρόθεμα ή επίθημα.")
    columns = require_columns(df, p.columns) or list(df.columns)
    mapping = {c: f"{p.prefix}{c}{p.suffix}" for c in columns}
    clashes = [n for n in mapping.values() if n in df.columns and n not in mapping]
    if clashes:
        raise ValueError(f"Υπάρχουν ήδη στήλες με αυτά τα ονόματα: {', '.join(clashes)}")
    return OpOutput(df=df.rename(columns=mapping), message=f"{len(mapping)} στήλες μετονομάστηκαν")


class ReorderParams(Params):
    columns: list[str] = columns_field("Στήλες που πάνε μπροστά", required=True)
    position: Literal["first", "last"] = choice("first", "Θέση", {"first": "Στην αρχή", "last": "Στο τέλος"})


@operation(
    "columns.reorder", "Αναδιάταξη στηλών", "Μετακινεί στήλες στην αρχή ή στο τέλος, με τη σειρά που τις διαλέγεις",
    "columns", "transform", ReorderParams,
    code=lambda p: (f"df = df[{p.columns!r} + [c for c in df.columns if c not in {p.columns!r}]]" if p.position == "first"
                    else f"df = df[[c for c in df.columns if c not in {p.columns!r}] + {p.columns!r}]"),
)
def reorder(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    rest = [c for c in df.columns if c not in columns]
    order = columns + rest if p.position == "first" else rest + columns
    return OpOutput(df=df[order], message="Νέα σειρά: " + ", ".join(order[:8]) + ("…" if len(order) > 8 else ""))


class PromoteParams(Params):
    row: int = Field(0, ge=0, le=100, title="Γραμμή που γίνεται header (0 = πρώτη)")


@operation(
    "columns.promote_header", "Γραμμή → ονόματα στηλών", "Όταν το αρχείο έχει τίτλο πάνω από τον πίνακα",
    "columns", "transform", PromoteParams,
    code=lambda p: f"df = promote_header(df, row={p.row!r})",
)
def promote(df, p, ctx):
    if p.row >= len(df):
        raise ValueError("Η γραμμή δεν υπάρχει.")
    out = promote_header(df, p.row)
    return OpOutput(df=out, message=f"Νέα ονόματα: {', '.join(map(str, out.columns[:8]))}",
                    warnings=["Οι τύποι στηλών μένουν κείμενο — τρέξε «Αυτόματοι τύποι»."])


class DuplicateColumnParams(Params):
    column: str = column_field()
    name: str = Field("", title="Όνομα νέας στήλης", description="Κενό = <στήλη>_copy")


@operation(
    "columns.duplicate", "Αντίγραφο στήλης", "Κράτα την αρχική τιμή πριν τη μετατρέψεις",
    "columns", "transform", DuplicateColumnParams,
    code=lambda p: f"df.insert(df.columns.get_loc({p.column!r}) + 1, {p.name or p.column + '_copy'!r}, df[{p.column!r}])",
)
def duplicate(df, p, ctx):
    require_columns(df, [p.column])
    name = p.name or f"{p.column}_copy"
    if name in df.columns:
        raise ValueError(f"Η στήλη '{name}' υπάρχει ήδη.")
    out = df.copy()
    out.insert(out.columns.get_loc(p.column) + 1, name, out[p.column])
    return OpOutput(df=out, message=f"Νέα στήλη {name}")
