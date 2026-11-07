"""Pure pandas helpers.

The operations call these, and the generated pipeline.py embeds their source code
(utils/code_gen.py copies them with inspect.getsource). So keep the imports to
pandas, numpy, re, unicodedata, warnings and unidecode, and do not import project code.
Every transform helper returns (new_df, report) and never changes its input in place.
"""

import re
import unicodedata
import warnings

import numpy as np
import pandas as pd
from unidecode import unidecode

MISSING_TOKENS = ["", "na", "n/a", "nan", "null", "none", "-", "--", "?", "#n/a", "missing"]


def column_kind(series):
    """numeric | boolean | datetime | text"""
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "text"


def strip_accents(text):
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


GREEKLISH_DIGRAPHS = {"ου": "ou", "αυ": "av", "ευ": "ev", "ηυ": "iv", "γγ": "ng", "γξ": "nx", "γχ": "nch"}
GREEKLISH_LETTERS = dict(zip(
    "αβγδεζηθικλμνξοπρσςτυφχψω",
    ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m", "n", "x", "o", "p", "r", "s", "s",
     "t", "y", "f", "ch", "ps", "o"],
))


def greeklish(text):
    """ELOT 743 style, lower case: 'πελάτη' -> 'pelati', 'ημερομηνία' -> 'imerominia'."""
    text = strip_accents(text).lower()
    for pair, latin in GREEKLISH_DIGRAPHS.items():
        text = text.replace(pair, latin)
    return "".join(GREEKLISH_LETTERS.get(ch, ch) for ch in text)


def snake_case_name(name, transliterate=True):
    """'Customer ID ' -> customer_id, 'PassengerId' -> passenger_id, 'Όνομα Πελάτη' -> onoma_pelati."""
    text = strip_accents(str(name)).strip()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = text.lower()
    if transliterate:
        text = unidecode(greeklish(text))
    text = re.sub(r"[^\w]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if text and text[0].isdigit():
        text = "col_" + text
    return text


def snake_case_columns(df, transliterate=True):
    used = set()
    new_names = []
    for position, column in enumerate(df.columns):
        base = snake_case_name(column, transliterate) or f"column_{position + 1}"
        name = base
        counter = 1
        while name in used:
            counter += 1
            name = f"{base}_{counter}"
        used.add(name)
        new_names.append(name)
    out = df.copy()
    out.columns = new_names
    report = [
        {"from": str(old), "to": new}
        for old, new in zip(df.columns, new_names)
        if str(old) != new
    ]
    return out, report


def to_number(series, decimal=".", strip_symbols=True):
    """Text -> float/int. '1.234,56 €' with decimal=',' -> 1234.56. Unparseable -> NaN."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return series
    text = series.astype("string").str.strip()
    if strip_symbols:
        text = text.str.replace(r"[\s€$£%]", "", regex=True)
    thousands = "," if decimal == "." else "."
    text = text.str.replace(rf"(?<=\d){re.escape(thousands)}(?=\d{{3}}(\D|$))", "", regex=True)
    if decimal == ",":
        text = text.str.replace(",", ".", regex=False)
    values = pd.to_numeric(text, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    result = pd.Series(values, index=series.index, name=series.name)
    present = result.dropna()
    if len(present) == len(result) and len(present) > 0 and (present % 1 == 0).all():
        return result.astype("int64")
    return result


def to_datetime_safe(series, fmt=None, dayfirst=True):
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):
        series = series.astype("string")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, format=fmt or "mixed", dayfirst=dayfirst, errors="coerce")


def _failed_examples(before, after, limit=5):
    failed = before[before.notna() & after.isna()]
    return int(len(failed)), [str(v) for v in failed.astype(str).unique()[:limit]]


def convert_numeric(df, columns, decimal=".", strip_symbols=True):
    out = df.copy()
    report = []
    for column in columns:
        before = out[column]
        out[column] = to_number(before, decimal=decimal, strip_symbols=strip_symbols)
        failed, examples = _failed_examples(before, out[column])
        report.append({"column": column, "dtype": str(out[column].dtype), "failed": failed, "examples": ", ".join(examples)})
    return out, report


def convert_datetime(df, columns, fmt=None, dayfirst=True):
    out = df.copy()
    report = []
    for column in columns:
        before = out[column]
        out[column] = to_datetime_safe(before, fmt=fmt, dayfirst=dayfirst)
        failed, examples = _failed_examples(before, out[column])
        report.append({"column": column, "dtype": str(out[column].dtype), "failed": failed, "examples": ", ".join(examples)})
    return out, report


DATE_PATTERN = r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}"


def auto_infer_types(df, columns=None, threshold=0.95, dayfirst=True):
    """Text columns that are really numbers or dates get converted."""
    out = df.copy()
    report = []
    targets = columns or [c for c in out.columns if column_kind(out[c]) == "text"]
    for column in targets:
        series = out[column]
        if column_kind(series) != "text":
            continue
        present = series.dropna()
        if present.empty:
            continue
        best = None
        for decimal in (".", ","):
            converted = to_number(series, decimal=decimal)
            ratio = converted[series.notna()].notna().mean()
            if best is None or ratio > best[0]:
                best = (ratio, converted, f"αριθμός (δεκαδικό '{decimal}')")
        if best[0] < threshold:
            looks_like_date = present.astype(str).str.match(DATE_PATTERN).mean() >= threshold
            if looks_like_date:
                converted = to_datetime_safe(series, dayfirst=dayfirst)
                ratio = converted[series.notna()].notna().mean()
                if ratio >= threshold:
                    best = (ratio, converted, "ημερομηνία")
        if best[0] >= threshold:
            out[column] = best[1]
            report.append({
                "column": column,
                "from": str(series.dtype),
                "to": str(out[column].dtype),
                "detected": best[2],
                "parsed_pct": round(float(best[0]) * 100, 2),
            })
    return out, report


def standardize_missing(df, columns=None, tokens=None):
    """'N/A', '-', '?', '' ... -> NaN, only in text columns."""
    tokens = [t.strip().lower() for t in (tokens or MISSING_TOKENS)]
    out = df.copy()
    report = []
    targets = columns or [c for c in out.columns if column_kind(out[c]) == "text"]
    for column in targets:
        series = out[column]
        if column_kind(series) != "text":
            continue
        normalized = series.astype("string").str.strip().str.lower()
        mask = normalized.isin(tokens).fillna(False).astype(bool)
        count = int(mask.sum())
        if count:
            out[column] = series.mask(mask)
            report.append({"column": column, "replaced": count})
    return out, report


def _is_whole(series):
    present = series.dropna()
    return len(present) > 0 and bool((present % 1 == 0).all())


def _fill(series, value):
    if isinstance(series.dtype, pd.CategoricalDtype) and value not in series.cat.categories:
        series = series.cat.add_categories([value])
    return series.fillna(value)


def smart_fill(df, columns=None, numeric_strategy="auto", categorical_strategy="mode",
               constant="Unknown", datetime_strategy="median", skip_if_missing_pct_over=60.0):
    """Fill NaN per column type: numbers median/mean, text mode/constant, dates median/ffill."""
    out = df.copy()
    report = []
    skipped = []
    targets = columns or [c for c in out.columns if out[c].isna().any()]
    for column in targets:
        series = out[column]
        missing = int(series.isna().sum())
        if missing == 0:
            continue
        missing_pct = missing / len(series) * 100
        if missing_pct > skip_if_missing_pct_over:
            skipped.append(f"{column}: {missing_pct:.1f}% κενά (> {skip_if_missing_pct_over}%)")
            continue
        kind = column_kind(series)
        present = series.dropna()
        if present.empty:
            skipped.append(f"{column}: όλες οι τιμές είναι κενές")
            continue
        if kind == "numeric":
            strategy = numeric_strategy
            if strategy == "auto":
                skew = present.skew() if len(present) > 2 else 0.0
                strategy = "mean" if abs(skew) < 0.5 else "median"
            value = present.mean() if strategy == "mean" else present.median()
            if _is_whole(present):
                value = round(value)
            out[column] = series.fillna(value)
            if _is_whole(present) and pd.api.types.is_float_dtype(out[column]):
                out[column] = out[column].astype("int64")  # NaN forced float; no gaps left now
        elif kind == "datetime":
            strategy = datetime_strategy
            if strategy == "ffill":
                out[column] = series.ffill().bfill()
                value = "προηγούμενη τιμή"
            else:
                value = present.median() if strategy == "median" else present.mode().iloc[0]
                out[column] = series.fillna(value)
        elif kind == "boolean":
            strategy = "mode"
            value = present.mode().iloc[0]
            out[column] = series.fillna(value)
        else:
            strategy = categorical_strategy
            value = constant if strategy == "constant" else present.mode().iloc[0]
            out[column] = _fill(series, value)
        report.append({"column": column, "kind": kind, "strategy": strategy, "value": value, "filled": missing})
    return out, report, skipped


def fill_with_value(df, columns, value):
    out = df.copy()
    report = []
    for column in columns:
        series = out[column]
        kind = column_kind(series)
        if kind == "numeric":
            parsed = to_number(pd.Series([value]))
            if parsed.isna().iloc[0]:
                raise ValueError(f"Η στήλη '{column}' είναι αριθμητική· το '{value}' δεν είναι αριθμός.")
            typed = parsed.iloc[0]
        elif kind == "datetime":
            typed = pd.Timestamp(value)
        elif kind == "boolean":
            typed = str(value).strip().lower() in {"true", "1", "yes", "ναι", "y"}
        else:
            typed = value
        missing = int(series.isna().sum())
        out[column] = _fill(series, typed)
        report.append({"column": column, "value": typed, "filled": missing})
    return out, report


def clean_text(df, columns=None, collapse_spaces=True, empty_to_nan=True):
    out = df.copy()
    report = []
    targets = columns or [c for c in out.columns if column_kind(out[c]) == "text"]
    for column in targets:
        series = out[column]
        if column_kind(series) != "text":
            continue
        mask = series.notna()
        original = series[mask].astype(str)
        cleaned = original.str.strip()
        if collapse_spaces:
            cleaned = cleaned.str.replace(r"\s+", " ", regex=True)
        changed = int((cleaned != original).sum())
        new = series.copy()
        new[mask] = cleaned
        emptied = 0
        if empty_to_nan:
            empty = new.astype("string").eq("").fillna(False).astype(bool)
            emptied = int(empty.sum())
            new = new.mask(empty)
        out[column] = new
        if changed or emptied:
            report.append({"column": column, "changed": changed, "emptied": emptied})
    return out, report


def change_case(df, columns=None, mode="lower", remove_accents=False):
    out = df.copy()
    report = []
    targets = columns or [c for c in out.columns if column_kind(out[c]) == "text"]
    for column in targets:
        series = out[column]
        if column_kind(series) != "text":
            continue
        mask = series.notna()
        original = series[mask].astype(str)
        changed_values = original
        if remove_accents:
            changed_values = changed_values.map(strip_accents)
        changed_values = getattr(changed_values.str, mode)()
        new = series.copy()
        new[mask] = changed_values
        out[column] = new
        report.append({"column": column, "changed": int((changed_values != original).sum())})
    return out, report


DATE_PARTS = ["year", "quarter", "month", "week", "day", "weekday", "hour", "is_weekend"]


def extract_date_parts(df, column, parts, dayfirst=True):
    out = df.copy()
    dates = to_datetime_safe(out[column], dayfirst=dayfirst)
    values = {
        "year": lambda d: d.dt.year,
        "quarter": lambda d: d.dt.quarter,
        "month": lambda d: d.dt.month,
        "week": lambda d: d.dt.isocalendar().week,
        "day": lambda d: d.dt.day,
        "weekday": lambda d: d.dt.day_of_week,
        "hour": lambda d: d.dt.hour,
        "is_weekend": lambda d: (d.dt.day_of_week >= 5).where(d.notna()),
    }
    position = out.columns.get_loc(column) + 1
    created = []
    for part in parts:
        name = f"{column}_{part}"
        series = values[part](dates).astype("Int64")
        if name in out.columns:
            out[name] = series
        else:
            out.insert(position, name, series)
            position += 1
        created.append(name)
    return out, created


def clip_outliers(df, columns=None, method="iqr", factor=1.5, lower_pct=1.0, upper_pct=99.0):
    out = df.copy()
    report = []
    targets = columns or [c for c in out.columns if column_kind(out[c]) == "numeric"]
    for column in targets:
        series = out[column]
        if column_kind(series) != "numeric":
            continue
        present = series.dropna()
        if present.empty:
            continue
        if method == "iqr":
            q1, q3 = present.quantile(0.25), present.quantile(0.75)
            lower, upper = q1 - factor * (q3 - q1), q3 + factor * (q3 - q1)
        else:
            lower, upper = present.quantile(lower_pct / 100), present.quantile(upper_pct / 100)
        if pd.api.types.is_integer_dtype(series):
            lower, upper = int(np.ceil(lower)), int(np.floor(upper))
        clipped = int(((series < lower) | (series > upper)).sum())
        out[column] = series.clip(lower, upper)
        report.append({"column": column, "lower": float(lower), "upper": float(upper), "clipped": clipped})
    return out, report


def _typed_value(series, raw):
    kind = column_kind(series)
    if kind == "numeric":
        parsed = to_number(pd.Series([raw]))
        if parsed.isna().iloc[0]:
            raise ValueError(f"Η στήλη '{series.name}' είναι αριθμητική· το '{raw}' δεν είναι αριθμός.")
        return parsed.iloc[0]
    if kind == "datetime":
        return pd.Timestamp(raw)
    if kind == "boolean":
        return str(raw).strip().lower() in {"true", "1", "yes", "ναι", "y"}
    return raw


def _condition_mask(df, column, op, value):
    series = df[column]
    if op == "isna":
        return series.isna()
    if op == "notna":
        return series.notna()
    if op in ("contains", "not_contains", "startswith", "endswith"):
        # case- and accent-insensitive, like the grid search: 'αθηνα' matches 'Αθήνα'
        text = series.astype("string").str.lower().str.normalize("NFKD").str.replace(r"[̀-ͯ]", "", regex=True)
        needle = strip_accents(str(value)).lower()
        if op == "startswith":
            mask = text.str.startswith(needle)
        elif op == "endswith":
            mask = text.str.endswith(needle)
        else:
            mask = text.str.contains(needle, regex=False)
        mask = mask.fillna(False).astype(bool)
        return ~mask if op == "not_contains" else mask
    if op == "isin":
        options = [_typed_value(series, part.strip()) for part in str(value).split(",")]
        return series.isin(options)
    if op == "between":
        parts = [part.strip() for part in str(value).split(",")]
        if len(parts) != 2:
            raise ValueError("Το 'between' θέλει δύο τιμές χωρισμένες με κόμμα, π.χ. 10,20")
        low, high = _typed_value(series, parts[0]), _typed_value(series, parts[1])
        return series.between(low, high)
    typed = _typed_value(series, value)
    compare = {
        "==": series.eq, "!=": series.ne, ">": series.gt,
        ">=": series.ge, "<": series.lt, "<=": series.le,
    }[op]
    return compare(typed)


def filter_rows(df, conditions, combine="and", mode="keep"):
    """conditions: [{'column': 'age', 'op': '>=', 'value': '18'}, ...]"""
    masks = [
        _condition_mask(df, c["column"], c["op"], c.get("value")).fillna(False).astype(bool)
        for c in conditions
    ]
    mask = masks[0]
    for other in masks[1:]:
        mask = (mask & other) if combine == "and" else (mask | other)
    selected = df[mask] if mode == "keep" else df[~mask]
    return selected.reset_index(drop=True), {"matched": int(mask.sum()), "rows_after": int(len(selected))}


def label_encode(df, columns, order="alphabetical"):
    out = df.copy()
    mappings = {}
    for column in columns:
        series = out[column]
        if order == "frequency":
            categories = list(series.value_counts().index)
        else:
            categories = sorted(series.dropna().unique(), key=lambda v: str(v))
        mapping = {category: code for code, category in enumerate(categories)}
        out[column] = series.map(mapping).astype("Int64")
        mappings[column] = mapping
    return out, mappings


# ---------------------------------------------------------------- phase 2: columns & types

def drop_columns_by_rule(df, max_missing_pct=60.0, drop_constant=True, drop_id_like=False):
    dropped = []
    n_rows = len(df)
    for column in df.columns:
        series = df[column]
        missing_pct = series.isna().mean() * 100 if n_rows else 0
        unique = series.nunique(dropna=True)
        if missing_pct > max_missing_pct:
            dropped.append({"column": column, "reason": f"{missing_pct:.1f}% κενά"})
        elif drop_constant and unique <= 1:
            dropped.append({"column": column, "reason": "σταθερή τιμή"})
        elif drop_id_like and n_rows > 1 and unique == n_rows and column_kind(series) in ("numeric", "text"):
            dropped.append({"column": column, "reason": "μοναδική τιμή ανά γραμμή (ID)"})
    return df.drop(columns=[d["column"] for d in dropped]), dropped


def promote_header(df, row=0):
    """Use a data row as the header (files with a title above the table)."""
    header = [str(v).strip() if pd.notna(v) and str(v).strip() else f"column_{i + 1}" for i, v in enumerate(df.iloc[row])]
    out = df.iloc[row + 1:].reset_index(drop=True)
    out.columns = header
    return out


BOOL_TRUE = {"true", "1", "yes", "y", "ναι", "ν", "t", "on", "αληθές"}
BOOL_FALSE = {"false", "0", "no", "n", "όχι", "οχι", "ο", "f", "off", "ψευδές"}


def to_boolean(df, columns):
    out = df.copy()
    report = []
    for column in columns:
        series = out[column]
        text = series.astype("string").str.strip().str.lower()
        mapped = pd.Series(pd.NA, index=series.index, dtype="boolean")
        mapped[text.isin(BOOL_TRUE).fillna(False).astype(bool)] = True
        mapped[text.isin(BOOL_FALSE).fillna(False).astype(bool)] = False
        failed = int((series.notna() & mapped.isna()).sum())
        out[column] = mapped
        report.append({"column": column, "true": int(mapped.sum()), "false": int((mapped == False).sum()), "failed": failed})  # noqa: E712
    return out, report


def downcast_numeric(df, columns=None):
    out = df.copy()
    report = []
    targets = columns or [c for c in out.columns if column_kind(out[c]) in ("numeric", "text")]
    for column in targets:
        series = out[column]
        before = series.memory_usage(deep=True)
        if pd.api.types.is_integer_dtype(series) and not isinstance(series.dtype, pd.api.extensions.ExtensionDtype):
            new = pd.to_numeric(series, downcast="integer")
        elif pd.api.types.is_float_dtype(series) and not isinstance(series.dtype, pd.api.extensions.ExtensionDtype):
            new = pd.to_numeric(series, downcast="float")
        elif column_kind(series) == "text" and series.nunique() <= max(50, len(series) * 0.5):
            new = series.astype("category")
        else:
            continue
        after = new.memory_usage(deep=True)
        if after < before:
            out[column] = new
            report.append({"column": column, "from": str(series.dtype), "to": str(new.dtype),
                           "saved_kb": round((before - after) / 1024, 1)})
    return out, report


# ---------------------------------------------------------------- phase 2: missing values

def fill_directional(df, columns, direction="ffill", group_by=None, limit=None):
    """ffill = previous value, bfill = next value, both = previous then next. Optional per group."""
    out = df.copy()
    keys = [out[g] for g in group_by] if group_by else None

    def run(series, how):
        target = series.groupby(keys, dropna=False) if keys else series
        return getattr(target, how)(limit=limit)

    for column in columns:
        series = out[column]
        if direction == "both":
            series = run(run(series, "ffill"), "bfill")
        else:
            series = run(series, direction)
        out[column] = series
    return out


def interpolate_columns(df, columns, method="linear", order_by=None):
    out = df.copy()
    if order_by:
        order = out[order_by].sort_values(kind="stable").index
        work = out.loc[order]
        for column in columns:
            work[column] = work[column].interpolate(method="linear", limit_direction="both")
        out.loc[order, columns] = work[columns]
    else:
        for column in columns:
            out[column] = out[column].interpolate(method=method, limit_direction="both")
    return out


def group_fill(df, columns, group_by, strategy="median"):
    out = df.copy()
    report = []
    for column in columns:
        before = int(out[column].isna().sum())
        grouped = out.groupby(group_by, dropna=False)[column]
        if strategy == "mode":
            values = grouped.transform(lambda s: s.mode().iloc[0] if not s.mode().empty else np.nan)
        else:
            values = grouped.transform(strategy)
        out[column] = out[column].fillna(values)
        report.append({"column": column, "filled": before - int(out[column].isna().sum()),
                       "still_missing": int(out[column].isna().sum())})
    return out, report


def knn_impute(df, columns, n_neighbors=5):
    from sklearn.impute import KNNImputer

    out = df.copy()
    imputer = KNNImputer(n_neighbors=n_neighbors)
    out[columns] = imputer.fit_transform(out[columns].astype("float64"))
    return out


def add_missing_indicators(df, columns, suffix="_was_missing"):
    out = df.copy()
    created = []
    for column in columns:
        name = f"{column}{suffix}"
        out.insert(out.columns.get_loc(column) + 1, name, out[column].isna().astype("int64"))
        created.append(name)
    return out, created


# ---------------------------------------------------------------- phase 2: text

def map_text(df, columns, fn):
    """Apply fn to the non-missing values of text columns; returns (df, changed per column)."""
    out = df.copy()
    report = []
    for column in columns:
        series = out[column]
        mask = series.notna()
        original = series[mask].astype(str)
        changed_values = original.map(fn)
        new = series.copy()
        new[mask] = changed_values
        out[column] = new
        report.append({"column": column, "changed": int((changed_values != original).sum())})
    return out, report


def transliterate_text(text):
    """ELOT 743 that keeps capitalisation: 'Αθήνα' -> 'Athina', 'ΘΕΣΗ' -> 'THESI'."""
    plain = strip_accents(text)
    out = []
    i = 0
    while i < len(plain):
        pair = plain[i:i + 2]
        if pair.lower() in GREEKLISH_DIGRAPHS:
            chunk, latin = pair, GREEKLISH_DIGRAPHS[pair.lower()]
        elif plain[i].lower() in GREEKLISH_LETTERS:
            chunk, latin = plain[i], GREEKLISH_LETTERS[plain[i].lower()]
        else:
            out.append(plain[i])
            i += 1
            continue
        i += len(chunk)
        next_upper = i < len(plain) and plain[i].isupper()
        if chunk.isupper() and (len(chunk) > 1 or next_upper):
            latin = latin.upper()
        elif chunk[0].isupper():
            latin = latin.capitalize()
        out.append(latin)
    return "".join(out)


MOJIBAKE_MARKERS = re.compile("[ΞΟÃÂÎÏ]")


def fix_mojibake_text(text):
    """'Ξ‘ΞΈΞ®Ξ½Ξ±' -> 'Αθήνα': UTF-8 bytes that were read with a one-byte codepage."""
    if not MOJIBAKE_MARKERS.search(text):
        return text
    for encoding in ("cp1253", "cp1252", "latin-1"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if len(candidate) < len(text):
            return candidate
    return text


def split_column(df, column, separator, max_parts=2, names=None, keep_original=True):
    parts = df[column].astype("string").str.split(separator, n=max_parts - 1, expand=True, regex=False)
    names = names or [f"{column}_{i + 1}" for i in range(parts.shape[1])]
    parts.columns = names[: parts.shape[1]]
    parts = parts.apply(lambda s: s.str.strip())
    out = df.copy()
    position = out.columns.get_loc(column) + 1
    for offset, name in enumerate(parts.columns):
        out.insert(position + offset, name, parts[name])
    if not keep_original:
        out = out.drop(columns=[column])
    return out


def is_valid_afm(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 9 or digits == "000000000":
        return False
    total = sum(int(d) * 2 ** (8 - i) for i, d in enumerate(digits[:8]))
    return total % 11 % 10 == int(digits[8])


def is_valid_iban(value):
    text = re.sub(r"\s", "", str(value)).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", text):
        return False
    rearranged = text[4:] + text[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


PATTERNS = {
    "email": r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$",
    "phone_gr": r"^(\+30|0030)?(2\d{9}|69\d{8})$",
    "postal_gr": r"^\d{5}$",
}


def validate_values(series, kind, custom=None):
    text = series.astype("string").str.strip()
    if kind == "afm":
        valid = text.map(lambda v: is_valid_afm(v) if pd.notna(v) else pd.NA)
    elif kind == "iban":
        valid = text.map(lambda v: is_valid_iban(v) if pd.notna(v) else pd.NA)
    else:
        pattern = custom if kind == "custom" else PATTERNS[kind]
        cleaned = text.str.replace(r"[\s\-().]", "", regex=True) if kind in ("phone_gr", "postal_gr") else text
        valid = cleaned.str.match(pattern)
    return valid.astype("boolean")


# ---------------------------------------------------------------- phase 2: dates & numbers

def date_difference(df, start, end=None, unit="days", name=None, dayfirst=True):
    out = df.copy()
    start_dates = to_datetime_safe(out[start], dayfirst=dayfirst)
    end_dates = to_datetime_safe(out[end], dayfirst=dayfirst) if end else pd.Timestamp.today().normalize()
    delta = end_dates - start_dates
    days = delta.dt.days if hasattr(delta, "dt") else delta.days
    values = {"days": days, "weeks": days / 7, "months": days / 30.4375, "years": days / 365.25}[unit]
    out[name or f"{start}_{unit}"] = values.round(2) if unit != "days" else values.astype("Int64")
    return out


def remove_outliers(df, columns, method="iqr", factor=1.5, z=3.0):
    mask = pd.Series(False, index=df.index)
    report = []
    for column in columns:
        series = df[column]
        if method == "iqr":
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            bad = (series < q1 - factor * (q3 - q1)) | (series > q3 + factor * (q3 - q1))
        else:
            bad = ((series - series.mean()) / series.std()).abs() > z
        bad = bad.fillna(False)
        report.append({"column": column, "outlier_rows": int(bad.sum())})
        mask |= bad
    return df[~mask].reset_index(drop=True), report


def transform_numeric(df, columns, method="log1p", suffix=""):
    from scipy import stats

    out = df.copy()
    report = []
    for column in columns:
        series = out[column].astype("float64")
        if method == "log1p":
            if (series.dropna() < 0).any():
                raise ValueError(f"Το log1p θέλει τιμές ≥ 0· η '{column}' έχει αρνητικές. Δοκίμασε yeo-johnson.")
            values = np.log1p(series)
        elif method == "sqrt":
            if (series.dropna() < 0).any():
                raise ValueError(f"Η ρίζα θέλει τιμές ≥ 0· η '{column}' έχει αρνητικές.")
            values = np.sqrt(series)
        elif method == "boxcox":
            if (series.dropna() <= 0).any():
                raise ValueError(f"Το Box-Cox θέλει θετικές τιμές· η '{column}' δεν έχει. Δοκίμασε yeo-johnson.")
            values = series.copy()
            values[series.notna()], _ = stats.boxcox(series.dropna())
        else:
            values = series.copy()
            values[series.notna()], _ = stats.yeojohnson(series.dropna())
        target = f"{column}{suffix}" if suffix else column
        out[target] = values
        report.append({"column": target, "skew_before": round(float(series.skew()), 3), "skew_after": round(float(values.skew()), 3)})
    return out, report


def bin_column(df, column, method="equal", bins=5, edges=None, labels=None, name=None):
    series = df[column]
    if method == "quantile":
        binned = pd.qcut(series, q=bins, labels=labels, duplicates="drop")
    elif method == "custom":
        binned = pd.cut(series, bins=edges, labels=labels, include_lowest=True)
    else:
        binned = pd.cut(series, bins=bins, labels=labels, include_lowest=True)
    out = df.copy()
    target = name or f"{column}_bin"
    out.insert(out.columns.get_loc(column) + 1, target, binned.astype("string"))
    return out


def scale_columns(df, columns, method="standard"):
    out = df.copy()
    report = []
    for column in columns:
        series = out[column].astype("float64")
        if method == "standard":
            center, scale = series.mean(), series.std(ddof=0)
        elif method == "minmax":
            center, scale = series.min(), series.max() - series.min()
        else:
            center, scale = series.median(), series.quantile(0.75) - series.quantile(0.25)
        scale = scale if scale else 1.0
        out[column] = (series - center) / scale
        report.append({"column": column, "center": float(center), "scale": float(scale)})
    return out, report


def column_formula(df, left, operator, right=None, constant=None, name="new_column"):
    a = df[left].astype("float64")
    b = df[right].astype("float64") if right else float(constant)
    result = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b, "%": lambda: a / b * 100}[operator]()
    out = df.copy()
    out[name] = result.replace([np.inf, -np.inf], np.nan)
    return out


# ---------------------------------------------------------------- phase 2: categories

def ordinal_encode(df, column, order, name=None):
    mapping = {value: code for code, value in enumerate(order)}
    unknown = sorted(set(df[column].dropna().astype(str)) - set(order))
    out = df.copy()
    out[name or column] = df[column].astype("string").map(mapping).astype("Int64")
    return out, unknown


def group_rare(df, columns, min_pct=1.0, other="Other"):
    out = df.copy()
    report = []
    for column in columns:
        shares = out[column].value_counts(normalize=True) * 100
        rare = list(shares[shares < min_pct].index)
        if rare:
            mask = out[column].isin(rare)
            out[column] = out[column].astype("object").where(~mask, other)
        report.append({"column": column, "grouped_categories": len(rare), "rows": int(out[column].eq(other).sum())})
    return out, report


def label_key(value):
    """Spelling-insensitive key: 'Αθήνα ', 'ΑΘΗΝΑ', 'αθηνα' -> 'αθηνα'."""
    return re.sub(r"\s+", " ", strip_accents(str(value))).strip().lower()


def standardize_labels(df, columns):
    """Variants that differ only by case/accents/spaces become the most frequent spelling."""
    out = df.copy()
    report = []
    for column in columns:
        series = out[column]
        counts = series.dropna().astype(str).value_counts()
        canonical = {}
        for value in counts.index:  # most frequent first
            canonical.setdefault(label_key(value), value)
        mapping = {value: canonical[label_key(value)] for value in counts.index if canonical[label_key(value)] != value}
        if mapping:
            out[column] = series.map(lambda v: mapping.get(str(v), v) if pd.notna(v) else v)
        report.append({"column": column, "merged_variants": len(mapping)})
    return out, report


if __name__ == "__main__":
    frame = pd.DataFrame({
        "Customer ID": [1, 2, 3, 4],
        "Όνομα Πελάτη": ["  Γιάννης ", "Μαρία", None, "N/A"],
        "Ποσό": ["1.234,50", "12,00", "7", "bad"],
        "Date": ["05/01/2024", "06/01/2024", None, "07/01/2024"],
    })
    renamed, changes = snake_case_columns(frame)
    assert list(renamed.columns) == ["customer_id", "onoma_pelati", "poso", "date"], renamed.columns
    assert snake_case_name("Ημερομηνία Παραγγελίας") == "imerominia_paraggelias".replace("gg", "ng")
    assert snake_case_name("PassengerId") == "passenger_id"
    assert snake_case_name("ΚΩΔΙΚΟΣ ΕΥΡΩ") == "kodikos_evro"
    assert snake_case_name("Όνομα", transliterate=False) == "ονομα"
    nums, _ = convert_numeric(renamed, ["poso"], decimal=",")
    assert nums["poso"].tolist()[:3] == [1234.5, 12.0, 7.0]
    std, rep = standardize_missing(renamed)
    assert std["onoma_pelati"].isna().sum() == 2
    filled, rep, skipped = smart_fill(nums)
    assert filled["poso"].isna().sum() == 0
    inferred, rep = auto_infer_types(renamed[["date"]], threshold=0.9)
    assert str(inferred["date"].dtype).startswith("datetime64"), rep
    kept, info = filter_rows(nums, [{"column": "customer_id", "op": ">=", "value": "3"}])
    assert info["matched"] == 2
    print("helpers ok")
