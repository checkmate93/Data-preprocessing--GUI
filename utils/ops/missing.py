"""Missing value buttons."""

from typing import Literal

from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, require_columns, table
from utils.ops.fields import choice, columns_field, optional_column_field
from utils.ops.helpers import (
    DATE_PATTERN,
    MISSING_TOKENS,
    add_missing_indicators,
    column_kind,
    fill_directional,
    fill_with_value,
    group_fill,
    interpolate_columns,
    knn_impute,
    smart_fill,
    standardize_missing,
    to_number,
)


def _tokens(raw):
    tokens = [t.strip() for t in raw.split(",")]
    return [""] + [t for t in tokens if t]


class StandardizeParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες κειμένου")
    tokens: str = Field(
        ", ".join(t for t in MISSING_TOKENS if t), title="Τιμές που σημαίνουν «κενό»",
        description="Χωρισμένες με κόμμα, χωρίς διάκριση πεζών/κεφαλαίων. Τα κενά κελιά μετράνε πάντα.",
    )


@operation(
    "missing.standardize", "Ενοποίηση κενών", "'N/A', '-', '?', 'null', '' → πραγματικό κενό (NaN)",
    "missing", "transform", StandardizeParams,
    code=lambda p: f"df, _ = standardize_missing(df, columns={p.columns or None!r}, tokens={_tokens(p.tokens)!r})",
)
def standardize(df, p, ctx):
    require_columns(df, p.columns)
    out, report = standardize_missing(df, p.columns or None, _tokens(p.tokens))
    total = sum(r["replaced"] for r in report)
    return OpOutput(df=out, sections=[table(report, "Αντικαταστάθηκαν")] if report else [],
                    message=f"{total} τιμές έγιναν NaN")


def _text_that_is_not_text(df, columns):
    """Text columns that are really numbers or dates: filling them now would use a text mode."""
    flagged = []
    for column in columns:
        series = df[column]
        present = series.dropna()
        if column_kind(series) != "text" or present.empty:
            continue
        numeric = max(to_number(present, decimal=d).notna().mean() for d in (".", ","))
        dates = present.astype(str).str.match(DATE_PATTERN).mean()
        if numeric >= 0.9 or dates >= 0.9:
            flagged.append(column)
    return flagged


class SmartFillParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες με κενά")
    numeric_strategy: Literal["auto", "median", "mean"] = choice(
        "auto", "Αριθμητικές στήλες",
        {"auto": "Αυτόματα (mean αν συμμετρική, αλλιώς median)", "median": "Διάμεσος", "mean": "Μέσος όρος"})
    categorical_strategy: Literal["mode", "constant"] = choice(
        "mode", "Στήλες κειμένου", {"mode": "Συχνότερη τιμή", "constant": "Σταθερή τιμή"})
    constant: str = Field("Unknown", title="Σταθερή τιμή για κείμενο")
    datetime_strategy: Literal["median", "mode", "ffill"] = choice(
        "median", "Στήλες ημερομηνίας",
        {"median": "Διάμεση ημερομηνία", "mode": "Συχνότερη", "ffill": "Προηγούμενη τιμή (χρονοσειρές)"})
    skip_if_missing_pct_over: float = Field(60.0, ge=0, le=100, title="Παράλειψη στηλών με κενά πάνω από %")


@operation(
    "missing.smart_fill", "Έξυπνο γέμισμα κενών",
    "Γεμίζει κάθε στήλη ανάλογα με τον τύπο της: αριθμοί → median/mean, κείμενο → συχνότερη τιμή, ημερομηνίες → median",
    "missing", "transform", SmartFillParams,
    code=lambda p: (
        f"df, _, _ = smart_fill(df, columns={p.columns or None!r}, numeric_strategy={p.numeric_strategy!r}, "
        f"categorical_strategy={p.categorical_strategy!r}, constant={p.constant!r}, "
        f"datetime_strategy={p.datetime_strategy!r}, skip_if_missing_pct_over={p.skip_if_missing_pct_over!r})"
    ),
)
def smart_fill_op(df, p, ctx):
    require_columns(df, p.columns)
    targets = p.columns or [c for c in df.columns if df[c].isna().any()]
    suspicious = _text_that_is_not_text(df, targets)
    out, report, skipped = smart_fill(
        df, p.columns or None, p.numeric_strategy, p.categorical_strategy,
        p.constant, p.datetime_strategy, p.skip_if_missing_pct_over,
    )
    total = sum(r["filled"] for r in report)
    rows = [
        {"στήλη": r["column"], "τύπος": r["kind"], "στρατηγική": r["strategy"], "τιμή": r["value"], "γεμίστηκαν": r["filled"]}
        for r in report
    ]
    warnings = list(skipped)
    if suspicious:
        warnings.insert(0, (
            f"Οι στήλες {', '.join(suspicious)} μοιάζουν με αριθμούς/ημερομηνίες αποθηκευμένα ως κείμενο, "
            "οπότε γεμίζουν με τη συχνότερη τιμή κειμένου. Τρέξε πρώτα «Αυτόματοι τύποι»."
        ))
    return OpOutput(df=out, sections=[table(rows, "Τι γέμισε")] if rows else [], warnings=warnings,
                    message=f"Γεμίστηκαν {total} κελιά σε {len(report)} στήλες")


class FillValueParams(Params):
    columns: list[str] = columns_field(required=True)
    value: str = Field(title="Τιμή", min_length=1)


@operation(
    "missing.fill_value", "Γέμισμα με τιμή", "fillna(τιμή) στις στήλες που διαλέγεις",
    "missing", "transform", FillValueParams,
    code=lambda p: f"df, _ = fill_with_value(df, {p.columns!r}, {p.value!r})",
)
def fill_value(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    out, report = fill_with_value(df, columns, p.value)
    return OpOutput(df=out, sections=[table(report, "Γεμίστηκαν")],
                    message=f"Γεμίστηκαν {sum(r['filled'] for r in report)} κελιά")


class DropRowsParams(Params):
    how: Literal["any", "all"] = choice(
        "any", "Διαγραφή όταν", {"any": "υπάρχει έστω ένα κενό", "all": "όλες οι τιμές είναι κενές"})
    columns: list[str] = columns_field("Έλεγχος μόνο σε αυτές τις στήλες", "Κενό = όλες οι στήλες")


@operation(
    "missing.drop_rows", "Διαγραφή γραμμών με κενά", "dropna()",
    "missing", "transform", DropRowsParams,
    code=lambda p: f"df = df.dropna(how={p.how!r}, subset={p.columns or None!r}).reset_index(drop=True)",
)
def drop_rows(df, p, ctx):
    subset = require_columns(df, p.columns) or None
    out = df.dropna(how=p.how, subset=subset).reset_index(drop=True)
    removed = len(df) - len(out)
    warnings = ["Διαγράφηκαν όλες οι γραμμές!"] if len(out) == 0 else []
    return OpOutput(df=out, warnings=warnings, message=f"Διαγράφηκαν {removed} γραμμές")


def _filled_message(before, after, columns):
    filled = int(before[columns].isna().sum().sum() - after[columns].isna().sum().sum())
    left = int(after[columns].isna().sum().sum())
    return f"Γεμίστηκαν {filled} κελιά" + (f" · έμειναν {left} κενά" if left else "")


class DirectionalParams(Params):
    columns: list[str] = columns_field(required=True)
    direction: Literal["ffill", "bfill", "both"] = choice(
        "ffill", "Κατεύθυνση", {"ffill": "Προηγούμενη τιμή (ffill)", "bfill": "Επόμενη τιμή (bfill)", "both": "Προηγούμενη, μετά επόμενη"})
    group_by: list[str] = columns_field("Μέσα σε ομάδες (προαιρετικό)", "π.χ. ανά πελάτη· κενό = όλος ο πίνακας")
    limit: int | None = Field(None, ge=1, title="Μέγιστα συνεχόμενα κενά (προαιρετικό)")


@operation(
    "missing.ffill_bfill", "Forward / Backward fill", "Γεμίζει με την προηγούμενη ή επόμενη τιμή (χρονοσειρές, λίστες)",
    "missing", "transform", DirectionalParams,
    code=lambda p: (f"df = fill_directional(df, {p.columns!r}, direction={p.direction!r}, "
                    f"group_by={p.group_by or None!r}, limit={p.limit!r})"),
)
def ffill_bfill(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    require_columns(df, p.group_by)
    out = fill_directional(df, columns, p.direction, p.group_by or None, p.limit)
    return OpOutput(df=out, message=_filled_message(df, out, columns))


class InterpolateParams(Params):
    columns: list[str] = columns_field(required=True)
    method: Literal["linear", "nearest"] = choice("linear", "Μέθοδος", {"linear": "Γραμμική", "nearest": "Πλησιέστερη τιμή"})
    order_by: str = optional_column_field("Σειρά κατά (προαιρετικό)", "π.χ. στήλη ημερομηνίας· κενό = η σειρά των γραμμών")


@operation(
    "missing.interpolate", "Interpolation", "Γεμίζει αριθμητικά κενά με παρεμβολή ανάμεσα στις γειτονικές τιμές",
    "missing", "transform", InterpolateParams,
    code=lambda p: f"df = interpolate_columns(df, {p.columns!r}, method={p.method!r}, order_by={p.order_by or None!r})",
)
def interpolate(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    if p.order_by:
        require_columns(df, [p.order_by])
    not_numeric = [c for c in columns if column_kind(df[c]) != "numeric"]
    if not_numeric:
        raise ValueError(f"Η παρεμβολή θέλει αριθμητικές στήλες: {', '.join(not_numeric)}")
    out = interpolate_columns(df, columns, p.method, p.order_by or None)
    return OpOutput(df=out, message=_filled_message(df, out, columns))


class GroupFillParams(Params):
    columns: list[str] = columns_field(required=True)
    group_by: list[str] = columns_field("Ομάδες", required=True)
    strategy: Literal["median", "mean", "mode"] = choice(
        "median", "Τιμή ομάδας", {"median": "Διάμεσος", "mean": "Μέσος όρος", "mode": "Συχνότερη (και για κείμενο)"})


@operation(
    "missing.group_fill", "Γέμισμα ανά ομάδα", "Η τιμή υπολογίζεται μέσα σε κάθε ομάδα (π.χ. ηλικία ανά φύλο και κλάση)",
    "missing", "transform", GroupFillParams,
    code=lambda p: f"df, _ = group_fill(df, {p.columns!r}, {p.group_by!r}, strategy={p.strategy!r})",
)
def group_fill_op(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    require_columns(df, p.group_by, at_least=1)
    if p.strategy != "mode":
        text_columns = [c for c in columns if column_kind(df[c]) != "numeric"]
        if text_columns:
            raise ValueError(f"Median/mean μόνο για αριθμούς· για τις {', '.join(text_columns)} διάλεξε «Συχνότερη».")
    out, report = group_fill(df, columns, p.group_by, p.strategy)
    warnings = [f"{r['column']}: {r['still_missing']} κενά σε ομάδες χωρίς καμία τιμή" for r in report if r["still_missing"]]
    return OpOutput(df=out, sections=[table(report)], warnings=warnings, message=_filled_message(df, out, columns))


class KnnParams(Params):
    columns: list[str] = columns_field("Αριθμητικές στήλες", "Όλες μαζί χρησιμοποιούνται για να βρεθούν οι «γείτονες»", required=True)
    n_neighbors: int = Field(5, ge=1, le=50, title="Πλήθος γειτόνων")


@operation(
    "missing.knn_impute", "KNN impute", "Κάθε κενό παίρνει τον μέσο όρο των k πιο όμοιων γραμμών (sklearn KNNImputer)",
    "missing", "transform", KnnParams,
    code=lambda p: f"df = knn_impute(df, {p.columns!r}, n_neighbors={p.n_neighbors!r})",
)
def knn(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    not_numeric = [c for c in columns if column_kind(df[c]) != "numeric"]
    if not_numeric:
        raise ValueError(f"Το KNN θέλει αριθμητικές στήλες: {', '.join(not_numeric)}")
    out = knn_impute(df, columns, p.n_neighbors)
    return OpOutput(df=out, message=_filled_message(df, out, columns),
                    warnings=["Οι τιμές υπολογίστηκαν σε όλο το dataset· για ML χρησιμοποίησε το «ML Prep» (fit μόνο στο train)."])


class IndicatorParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες με κενά")


@operation(
    "missing.indicator", "Στήλες-δείκτες κενών", "Νέα στήλη 0/1 «ήταν κενό» — τρέξ' το πριν το γέμισμα",
    "missing", "transform", IndicatorParams,
    code=lambda p: f"df, _ = add_missing_indicators(df, {p.columns or None!r} or [c for c in df.columns if df[c].isna().any()])",
)
def indicator(df, p, ctx):
    columns = require_columns(df, p.columns) or [c for c in df.columns if df[c].isna().any()]
    if not columns:
        raise ValueError("Καμία στήλη δεν έχει κενά.")
    out, created = add_missing_indicators(df, columns)
    return OpOutput(df=out, message=f"Νέες στήλες: {', '.join(created)}")
