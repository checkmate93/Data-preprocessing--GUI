"""Row buttons: duplicates, filter, sort, sample, top N."""

import difflib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from utils.op_registry import OpOutput, Params, operation, require_columns, table, text
from utils.ops.fields import choice, column_field, columns_field, optional_column_field
from utils.ops.helpers import column_kind, filter_rows, label_key

KEEP_LABELS = {"first": "Κράτα την πρώτη", "last": "Κράτα την τελευταία", "none": "Διέγραψε όλες τις επαναλήψεις"}


class DropDuplicatesParams(Params):
    columns: list[str] = columns_field("Έλεγχος μόνο σε αυτές τις στήλες", "Κενό = ολόκληρη η γραμμή")
    keep: Literal["first", "last", "none"] = choice("first", "Ποια να μείνει", KEEP_LABELS)


def _keep(value):
    return False if value == "none" else value


@operation(
    "duplicates.drop", "Διαγραφή διπλότυπων", "drop_duplicates()",
    "duplicates", "transform", DropDuplicatesParams,
    code=lambda p: (f"df = df.drop_duplicates(subset={p.columns or None!r}, "
                    f"keep={_keep(p.keep)!r}).reset_index(drop=True)"),
)
def drop_duplicates(df, p, ctx):
    subset = require_columns(df, p.columns) or None
    out = df.drop_duplicates(subset=subset, keep=_keep(p.keep)).reset_index(drop=True)
    return OpOutput(df=out, message=f"Διαγράφηκαν {len(df) - len(out)} διπλότυπες γραμμές")


OPERATOR_LABELS = {
    "==": "=", "!=": "≠", ">": ">", ">=": "≥", "<": "<", "<=": "≤",
    "contains": "περιέχει", "not_contains": "δεν περιέχει", "startswith": "ξεκινά με", "endswith": "τελειώνει σε",
    "isin": "είναι ένα από (a,b,c)", "between": "μεταξύ (a,b)", "isna": "είναι κενό", "notna": "δεν είναι κενό",
}


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "contains", "not_contains", "startswith",
                "endswith", "isin", "between", "isna", "notna"]
    value: str = ""


class FilterParams(Params):
    conditions: list[Condition] = Field(
        default_factory=list, title="Συνθήκες", min_length=1,
        json_schema_extra={"ui": "conditions", "operator_labels": OPERATOR_LABELS})
    combine: Literal["and", "or"] = choice("and", "Συνδυασμός", {"and": "Όλες (AND)", "or": "Οποιαδήποτε (OR)"})
    mode: Literal["keep", "remove"] = choice(
        "keep", "Τι να γίνει", {"keep": "Κράτα τις γραμμές που ταιριάζουν", "remove": "Διέγραψε τις γραμμές που ταιριάζουν"})


@operation(
    "rows.filter", "Φίλτρο γραμμών", "Κράτα ή διέγραψε γραμμές με βάση συνθήκες",
    "rows", "transform", FilterParams,
    code=lambda p: (f"df, _ = filter_rows(df, {[c.model_dump() for c in p.conditions]!r}, "
                    f"combine={p.combine!r}, mode={p.mode!r})"),
)
def filter_op(df, p, ctx):
    require_columns(df, [c.column for c in p.conditions], at_least=1)
    out, info = filter_rows(df, [c.model_dump() for c in p.conditions], p.combine, p.mode)
    return OpOutput(df=out, message=f"Ταίριαξαν {info['matched']} γραμμές · έμειναν {info['rows_after']}")


class SortParams(Params):
    columns: list[str] = columns_field("Ταξινόμηση κατά", required=True)
    ascending: bool = Field(True, title="Αύξουσα σειρά")


@operation(
    "rows.sort", "Ταξινόμηση", "sort_values()",
    "rows", "transform", SortParams,
    code=lambda p: (f"df = df.sort_values({p.columns!r}, ascending={p.ascending!r}, "
                    f"na_position='last', kind='stable').reset_index(drop=True)"),
)
def sort(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out = df.sort_values(columns, ascending=p.ascending, na_position="last", kind="stable").reset_index(drop=True)
    return OpOutput(df=out, message=f"Ταξινόμηση κατά {', '.join(columns)}")


class FlagParams(Params):
    columns: list[str] = columns_field("Έλεγχος μόνο σε αυτές τις στήλες", "Κενό = ολόκληρη η γραμμή")
    name: str = Field("is_duplicate", title="Όνομα νέας στήλης", min_length=1)


@operation(
    "duplicates.flag", "Σήμανση διπλότυπων", "Νέα στήλη 0/1 αντί για διαγραφή (1 = επανάληψη προηγούμενης γραμμής)",
    "duplicates", "transform", FlagParams,
    code=lambda p: f"df[{p.name!r}] = df.duplicated(subset={p.columns or None!r}, keep='first').astype('int64')",
)
def flag(df, p, ctx):
    subset = require_columns(df, p.columns) or None
    out = df.copy()
    out[p.name] = out.duplicated(subset=subset, keep="first").astype("int64")
    return OpOutput(df=out, message=f"{int(out[p.name].sum())} γραμμές σημειώθηκαν ως διπλότυπες")


class FuzzyParams(Params):
    column: str = column_field()
    cutoff: float = Field(0.85, ge=0.5, le=1.0, title="Ελάχιστη ομοιότητα (0.5–1)")


@operation(
    "duplicates.fuzzy_report", "Παρόμοιες τιμές", "Βρίσκει τιμές που μάλλον είναι το ίδιο: «Αθήνα», «ΑΘΗΝΑ », «Αθηνα», «Αθήναα»",
    "duplicates", "inspect", FuzzyParams,
)
def fuzzy_report(df, p, ctx):
    require_columns(df, [p.column])
    counts = df[p.column].dropna().astype(str).value_counts()
    if len(counts) > 3000:
        counts = counts.head(3000)
    groups = {}
    for value, count in counts.items():
        groups.setdefault(label_key(value), []).append((value, int(count)))
    rows = [
        {"ομάδα": variants[0][0], "παραλλαγές": " | ".join(f"{v} ({c})" for v, c in variants), "είδος": "γραφή / τόνοι / κενά"}
        for variants in groups.values() if len(variants) > 1
    ]
    keys = list(groups)
    seen = set()
    for key in keys:
        if key in seen:
            continue
        close = [k for k in difflib.get_close_matches(key, keys, n=6, cutoff=p.cutoff) if k != key and k not in seen]
        if close:
            seen.update(close + [key])
            members = [groups[k][0] for k in [key, *close]]
            rows.append({"ομάδα": members[0][0], "παραλλαγές": " | ".join(f"{v} ({c})" for v, c in members), "είδος": "παρόμοια γραφή"})
    if not rows:
        return OpOutput(sections=[text("Δεν βρέθηκαν παρόμοιες τιμές.")])
    return OpOutput(sections=[
        table(rows, f"{len(rows)} ομάδες"),
        text("Οι ομάδες «γραφή / τόνοι / κενά» ενοποιούνται αυτόματα με «Ενοποίηση ετικετών» (Κατηγορίες)."),
    ])


class SampleParams(Params):
    mode: Literal["n", "fraction"] = choice("n", "Μέγεθος", {"n": "Αριθμός γραμμών", "fraction": "Ποσοστό %"})
    n: int = Field(1000, ge=1, title="Γραμμές")
    percent: float = Field(10.0, gt=0, le=100, title="Ποσοστό %")
    stratify: str = optional_column_field("Αναλογική δειγματοληψία ανά (προαιρετικό)")
    seed: int = Field(42, title="Random seed")


def _sample_code(p):
    size = f"n={p.n!r}" if p.mode == "n" else f"frac={p.percent / 100!r}"
    if p.stratify:
        size = f"frac={p.percent / 100!r}" if p.mode == "fraction" else f"frac=min(1.0, {p.n!r} / len(df))"
        return (f"df = df.groupby({p.stratify!r}, group_keys=False, dropna=False)"
                f".sample({size}, random_state={p.seed!r}).reset_index(drop=True)")
    return f"df = df.sample({size}, random_state={p.seed!r}).reset_index(drop=True)"


@operation(
    "rows.sample", "Δείγμα γραμμών", "Τυχαίο δείγμα (και αναλογικό ανά κατηγορία)",
    "rows", "transform", SampleParams, code=_sample_code,
)
def sample(df, p, ctx):
    if p.stratify:
        require_columns(df, [p.stratify])
        frac = p.percent / 100 if p.mode == "fraction" else min(1.0, p.n / len(df))
        out = df.groupby(p.stratify, group_keys=False, dropna=False).sample(frac=frac, random_state=p.seed)
    elif p.mode == "n":
        out = df.sample(min(p.n, len(df)), random_state=p.seed)
    else:
        out = df.sample(frac=p.percent / 100, random_state=p.seed)
    return OpOutput(df=out.reset_index(drop=True), message=f"Κρατήθηκαν {len(out)} από {len(df)} γραμμές")


class TopNParams(Params):
    column: str = column_field()
    n: int = Field(10, ge=1, title="Πλήθος")
    largest: bool = Field(True, title="Μεγαλύτερες τιμές (αλλιώς μικρότερες)")


@operation(
    "rows.top_n", "Top / Bottom N", "nlargest / nsmallest",
    "rows", "transform", TopNParams,
    code=lambda p: f"df = df.{'nlargest' if p.largest else 'nsmallest'}({p.n!r}, {p.column!r}).reset_index(drop=True)",
)
def top_n(df, p, ctx):
    require_columns(df, [p.column])
    if column_kind(df[p.column]) not in ("numeric", "datetime"):
        raise ValueError("Το Top N θέλει αριθμητική ή ημερομηνία στήλη.")
    out = (df.nlargest if p.largest else df.nsmallest)(p.n, p.column).reset_index(drop=True)
    return OpOutput(df=out, message=f"Κρατήθηκαν {len(out)} γραμμές")
