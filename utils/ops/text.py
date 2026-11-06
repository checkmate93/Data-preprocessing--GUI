"""Text buttons."""

import re
from typing import Literal

import pandas as pd
from pydantic import Field

from utils.op_registry import OpOutput, Params, operation, require_columns, table
from utils.ops.fields import choice, column_field, columns_field
from utils.ops.helpers import (
    change_case,
    clean_text,
    column_kind,
    fix_mojibake_text,
    map_text,
    split_column,
    strip_accents,
    transliterate_text,
    validate_values,
)


class StripParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες κειμένου")
    collapse_spaces: bool = Field(True, title="Πολλά κενά → ένα")
    empty_to_nan: bool = Field(True, title="Κενό κείμενο → NaN")


@operation(
    "text.strip", "Καθάρισμα κενών", "str.strip(): κενά στην αρχή/τέλος και διπλά κενά",
    "text", "transform", StripParams,
    code=lambda p: (f"df, _ = clean_text(df, columns={p.columns or None!r}, "
                    f"collapse_spaces={p.collapse_spaces!r}, empty_to_nan={p.empty_to_nan!r})"),
)
def strip(df, p, ctx):
    require_columns(df, p.columns)
    out, report = clean_text(df, p.columns or None, p.collapse_spaces, p.empty_to_nan)
    changed = sum(r["changed"] for r in report)
    return OpOutput(df=out, sections=[table(report, "Αλλαγές")] if report else [],
                    message=f"Καθαρίστηκαν {changed} τιμές σε {len(report)} στήλες")


class CaseParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες κειμένου")
    mode: Literal["lower", "upper", "title", "capitalize"] = choice(
        "lower", "Μορφή",
        {"lower": "πεζά", "upper": "ΚΕΦΑΛΑΙΑ", "title": "Κάθε Λέξη Κεφαλαίο", "capitalize": "Πρώτο γράμμα κεφαλαίο"})
    remove_accents: bool = Field(False, title="Αφαίρεση τόνων (Αθήνα → Αθηνα)")


@operation(
    "text.case", "Πεζά / Κεφαλαία", "str.lower() / upper() / title()",
    "text", "transform", CaseParams,
    code=lambda p: (f"df, _ = change_case(df, columns={p.columns or None!r}, mode={p.mode!r}, "
                    f"remove_accents={p.remove_accents!r})"),
)
def case(df, p, ctx):
    require_columns(df, p.columns)
    out, report = change_case(df, p.columns or None, p.mode, p.remove_accents)
    return OpOutput(df=out, sections=[table(report, "Αλλαγές")] if report else [],
                    message=f"Άλλαξαν {sum(r['changed'] for r in report)} τιμές")


def _text_columns(df, columns):
    columns = require_columns(df, columns) or [c for c in df.columns if column_kind(df[c]) == "text"]
    if not columns:
        raise ValueError("Δεν υπάρχουν στήλες κειμένου.")
    return columns


def _mapped(df, columns, fn, label):
    out, report = map_text(df, _text_columns(df, columns), fn)
    changed = sum(r["changed"] for r in report)
    return OpOutput(df=out, sections=[table([r for r in report if r["changed"]], "Αλλαγές")] if changed else [],
                    message=f"{label}: άλλαξαν {changed} τιμές")


class TextColumns(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι στήλες κειμένου")


@operation(
    "text.remove_accents", "Αφαίρεση τόνων", "Αθήνα → Αθηνα, Ελλάδα → Ελλαδα (βοηθά σε αναζητήσεις και joins)",
    "text", "transform", TextColumns,
    code=lambda p: f"df, _ = map_text(df, {p.columns or None!r} or [c for c in df.columns if column_kind(df[c]) == 'text'], strip_accents)",
)
def remove_accents(df, p, ctx):
    return _mapped(df, p.columns, strip_accents, "Τόνοι")


@operation(
    "text.transliterate", "Greeklish (ELOT 743)", "Αθήνα → Athina, Θεσσαλονίκη → Thessaloniki",
    "text", "transform", TextColumns,
    code=lambda p: f"df, _ = map_text(df, {p.columns or None!r} or [c for c in df.columns if column_kind(df[c]) == 'text'], transliterate_text)",
)
def transliterate(df, p, ctx):
    return _mapped(df, p.columns, transliterate_text, "Greeklish")


@operation(
    "text.fix_mojibake", "Διόρθωση σπασμένων χαρακτήρων", "«Ξ‘ΞΈΞ®Ξ½Ξ±» → «Αθήνα», «CafÃ©» → «Café» (UTF-8 που διαβάστηκε λάθος)",
    "text", "transform", TextColumns,
    code=lambda p: f"df, _ = map_text(df, {p.columns or None!r} or [c for c in df.columns if column_kind(df[c]) == 'text'], fix_mojibake_text)",
)
def fix_mojibake(df, p, ctx):
    result = _mapped(df, p.columns, fix_mojibake_text, "Διορθώσεις")
    if not result.sections:
        result.warnings.append("Δεν βρέθηκαν σπασμένοι χαρακτήρες. Αν όλο το αρχείο φαίνεται λάθος, δοκίμασε «Ξαναδιάβασε» με άλλο encoding.")
    return result


class ReplaceParams(Params):
    columns: list[str] = columns_field(required=True)
    find: str = Field(title="Βρες", min_length=1)
    replace: str = Field("", title="Αντικατάσταση με")
    regex: bool = Field(False, title="Regular expression")
    whole_value: bool = Field(False, title="Μόνο όταν ταιριάζει όλη η τιμή")
    case_sensitive: bool = Field(True, title="Διάκριση πεζών/κεφαλαίων")


def _replace_pattern(p):
    pattern = p.find if p.regex else re.escape(p.find)
    if p.whole_value:
        pattern = f"^(?:{pattern})$"
    return ("" if p.case_sensitive else "(?i)") + pattern


@operation(
    "text.replace", "Αντικατάσταση", "Βρες & αντικατέστησε (απλό κείμενο ή regex)",
    "text", "transform", ReplaceParams,
    code=lambda p: f"df[{p.columns!r}] = df[{p.columns!r}].apply(lambda s: s.str.replace({_replace_pattern(p)!r}, {p.replace!r}, regex=True))",
)
def replace(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    pattern = _replace_pattern(p)
    re.compile(pattern)
    out = df.copy()
    changed = 0
    for column in columns:
        before = out[column]
        if column_kind(before) != "text":
            raise ValueError(f"Η '{column}' δεν είναι κείμενο.")
        out[column] = before.str.replace(pattern, p.replace, regex=True)
        changed += int((out[column] != before).fillna(False).sum())
    return OpOutput(df=out, message=f"Άλλαξαν {changed} τιμές")


class ExtractParams(Params):
    column: str = column_field()
    pattern: str = Field(title="Regex με μία ομάδα ( )", min_length=1,
                         description=r"π.χ. (\d{5}) για ΤΚ, ,\s*([^.]+)\. για τίτλο από «Braund, Mr. Owen»")
    name: str = Field(title="Όνομα νέας στήλης", min_length=1)


@operation(
    "text.extract", "Εξαγωγή με regex", "Νέα στήλη από κομμάτι κειμένου (ΤΚ, κωδικός, τίτλος…)",
    "text", "transform", ExtractParams,
    code=lambda p: f"df.insert(df.columns.get_loc({p.column!r}) + 1, {p.name!r}, df[{p.column!r}].astype('string').str.extract({p.pattern!r}, expand=False))",
)
def extract(df, p, ctx):
    require_columns(df, [p.column])
    if re.compile(p.pattern).groups != 1:
        raise ValueError("Το regex πρέπει να έχει ακριβώς μία ομάδα σε παρενθέσεις.")
    if p.name in df.columns:
        raise ValueError(f"Η στήλη '{p.name}' υπάρχει ήδη.")
    out = df.copy()
    out.insert(out.columns.get_loc(p.column) + 1, p.name, out[p.column].astype("string").str.extract(p.pattern, expand=False))
    found = int(out[p.name].notna().sum())
    return OpOutput(df=out, message=f"Βρέθηκε τιμή σε {found} από {len(out)} γραμμές")


class SplitParams(Params):
    column: str = column_field()
    separator: str = Field(",", title="Διαχωριστικό", min_length=1)
    max_parts: int = Field(2, ge=2, le=20, title="Μέγιστα κομμάτια")
    names: str = Field("", title="Ονόματα νέων στηλών (με κόμμα, προαιρετικό)", description="π.χ. eponymo, onoma")
    keep_original: bool = Field(True, title="Κράτα την αρχική στήλη")


def _split_names(p):
    return [n.strip() for n in p.names.split(",") if n.strip()] or None


@operation(
    "text.split", "Διαχωρισμός στήλης", "«Παπαδόπουλος, Γιάννης» → δύο στήλες",
    "text", "transform", SplitParams,
    code=lambda p: (f"df = split_column(df, {p.column!r}, {p.separator!r}, max_parts={p.max_parts!r}, "
                    f"names={_split_names(p)!r}, keep_original={p.keep_original!r})"),
)
def split(df, p, ctx):
    require_columns(df, [p.column])
    out = split_column(df, p.column, p.separator, p.max_parts, _split_names(p), p.keep_original)
    added = [c for c in out.columns if c not in df.columns]
    return OpOutput(df=out, message=f"Νέες στήλες: {', '.join(map(str, added))}")


class ConcatParams(Params):
    columns: list[str] = columns_field("Στήλες με τη σειρά", required=True)
    separator: str = Field(" ", title="Ανάμεσα")
    name: str = Field(title="Όνομα νέας στήλης", min_length=1)


@operation(
    "text.concat", "Ένωση στηλών", "π.χ. οδός + αριθμός + ΤΚ → διεύθυνση (τα κενά παραλείπονται)",
    "text", "transform", ConcatParams,
    code=lambda p: (f"df[{p.name!r}] = df[{p.columns!r}].astype('string').apply("
                    f"lambda r: {p.separator!r}.join(v for v in r if pd.notna(v)), axis=1)"),
)
def concat(df, p, ctx):
    columns = require_columns(df, p.columns, at_least=1)
    if p.name in df.columns:
        raise ValueError(f"Η στήλη '{p.name}' υπάρχει ήδη.")
    out = df.copy()
    out[p.name] = out[columns].astype("string").apply(lambda r: p.separator.join(v for v in r if pd.notna(v)), axis=1)
    return OpOutput(df=out, message=f"Νέα στήλη {p.name}")


class LengthParams(Params):
    column: str = column_field()


@operation(
    "text.length", "Μήκος κειμένου", "Νέα στήλη με τον αριθμό χαρακτήρων",
    "text", "transform", LengthParams,
    code=lambda p: f"df.insert(df.columns.get_loc({p.column!r}) + 1, {p.column + '_length'!r}, df[{p.column!r}].astype('string').str.len())",
)
def length(df, p, ctx):
    require_columns(df, [p.column])
    out = df.copy()
    out.insert(out.columns.get_loc(p.column) + 1, f"{p.column}_length", out[p.column].astype("string").str.len())
    return OpOutput(df=out, message=f"Νέα στήλη {p.column}_length")


VALIDATION_LABELS = {
    "email": "Email", "phone_gr": "Τηλέφωνο (Ελλάδα)", "postal_gr": "ΤΚ (5 ψηφία)",
    "afm": "ΑΦΜ (με έλεγχο ψηφίου)", "iban": "IBAN (mod 97)", "custom": "Δικό μου regex",
}


class ValidateParams(Params):
    column: str = column_field()
    kind: Literal["email", "phone_gr", "postal_gr", "afm", "iban", "custom"] = choice("email", "Έλεγχος", VALIDATION_LABELS)
    pattern: str = Field("", title="Regex (μόνο για «Δικό μου regex»)")


@operation(
    "text.validate_pattern", "Έλεγχος μορφής", "Νέα στήλη True/False: email, τηλέφωνο, ΤΚ, ΑΦΜ, IBAN ή δικό σου regex",
    "text", "transform", ValidateParams,
    code=lambda p: (f"df.insert(df.columns.get_loc({p.column!r}) + 1, {p.column + '_valid'!r}, "
                    f"validate_values(df[{p.column!r}], {p.kind!r}, {p.pattern or None!r}))"),
)
def validate(df, p, ctx):
    require_columns(df, [p.column])
    if p.kind == "custom":
        if not p.pattern:
            raise ValueError("Δώσε regex.")
        re.compile(p.pattern)
    out = df.copy()
    valid = validate_values(out[p.column], p.kind, p.pattern or None)
    out.insert(out.columns.get_loc(p.column) + 1, f"{p.column}_valid", valid)
    bad = out.loc[valid == False, p.column].astype(str).head(10).tolist()  # noqa: E712
    return OpOutput(
        df=out, message=f"Έγκυρες {int(valid.sum())} · μη έγκυρες {int((valid == False).sum())} · κενές {int(valid.isna().sum())}",  # noqa: E712
        warnings=[f"Παραδείγματα μη έγκυρων: {', '.join(bad)}"] if bad else [],
    )
