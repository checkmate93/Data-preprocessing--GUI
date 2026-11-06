"""Light profile of the current dataset version: column kinds, flags, quality score.

(utils/pandas_profiler.py stays for the v1 ML pipeline.)
"""

import logging

import pandas as pd

from utils.json_safe import to_jsonable
from utils.ops.helpers import DATE_PATTERN, MISSING_TOKENS, column_kind, snake_case_name, to_number

logger = logging.getLogger(__name__)

SAMPLE_SIZE = 2000


def _text_flags(series):
    flags = []
    sample = series.dropna().astype(str)
    if sample.empty:
        return flags
    if len(sample) > SAMPLE_SIZE:
        sample = sample.sample(SAMPLE_SIZE, random_state=0)
    stripped = sample.str.strip()
    if (stripped != sample).any() or sample.str.contains(r"\s{2,}", regex=True).any():
        flags.append("whitespace")
    if stripped.str.lower().isin(MISSING_TOKENS).any():
        flags.append("placeholders")
    real = stripped[~stripped.str.lower().isin(MISSING_TOKENS)]
    if not real.empty:
        numeric_ratio = max(to_number(real, decimal=d).notna().mean() for d in (".", ","))
        if numeric_ratio >= 0.95:
            flags.append("looks_numeric")
        elif real.str.match(DATE_PATTERN).mean() >= 0.9:
            flags.append("looks_date")
    if stripped.str.lower().nunique() < stripped.nunique():
        flags.append("case_variants")
    return flags


def build_profile(df):
    n_rows, n_cols = df.shape
    columns = {}
    for name in df.columns:
        series = df[name]
        kind = column_kind(series)
        null_count = int(series.isna().sum())
        unique = int(series.nunique(dropna=True))
        present = n_rows - null_count
        meta = {
            "dtype": str(series.dtype),
            "kind": kind,
            "null_count": null_count,
            "null_pct": round(null_count / n_rows * 100, 2) if n_rows else 0.0,
            "unique": unique,
            "flags": [],
        }
        if kind == "text":
            if unique <= 50 and unique <= max(1, present * 0.5):
                meta["kind"] = "categorical"
            meta["flags"] = _text_flags(series)
            modes = series.mode(dropna=True)
            meta["top"] = to_jsonable(modes.iloc[0]) if not modes.empty else None
        elif kind == "numeric" and present:
            values = series.dropna()
            meta.update({
                "min": to_jsonable(values.min()),
                "max": to_jsonable(values.max()),
                "mean": to_jsonable(values.mean()),
                "median": to_jsonable(values.median()),
                "skew": to_jsonable(values.skew()) if present > 2 else None,
            })
        if n_rows > 1 and unique == n_rows and kind in ("numeric", "text"):
            meta["flags"].append("id_like")
        if unique <= 1:
            meta["flags"].append("constant")
        if meta["null_pct"] >= 60:
            meta["flags"].append("high_missing")
        columns[str(name)] = meta

    duplicates = int(df.duplicated().sum())
    total_missing = int(df.isna().sum().sum())
    cells = max(n_rows * n_cols, 1)
    invalid = sum(1 for m in columns.values() if {"looks_numeric", "looks_date", "placeholders"} & set(m["flags"]))
    inconsistent = sum(1 for m in columns.values() if {"whitespace", "case_variants"} & set(m["flags"]))
    quality = {
        "completeness": round(100 * (1 - total_missing / cells), 1),
        "uniqueness": round(100 * (1 - duplicates / n_rows), 1) if n_rows else 100.0,
        "validity": round(100 * (1 - invalid / max(n_cols, 1)), 1),
        "consistency": round(100 * (1 - inconsistent / max(n_cols, 1)), 1),
    }
    quality["total"] = round(sum(quality.values()) / 4)
    profile = {
        "shape": [int(n_rows), int(n_cols)],
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1024 ** 2, 2),
        "duplicates_count": duplicates,
        "total_missing": total_missing,
        "rows_with_missing": int(df.isna().any(axis=1).sum()),
        "names_not_snake": [str(c) for c in df.columns if snake_case_name(c) != str(c)],
        "quality": quality,
        "columns": columns,
    }
    logger.info("Profile shape=%s quality=%s", profile["shape"], quality["total"])
    return profile


if __name__ == "__main__":
    frame = pd.DataFrame({
        "ID": [1, 2, 3, 4],
        "Πόλη": [" Αθήνα", "αθήνα", "N/A", "Πάτρα"],
        "amount": ["1,5", "2", "3", "4"],
    })
    result = build_profile(frame)
    assert "whitespace" in result["columns"]["Πόλη"]["flags"]
    assert "placeholders" in result["columns"]["Πόλη"]["flags"]
    assert "looks_numeric" in result["columns"]["amount"]["flags"]
    assert result["names_not_snake"] == ["ID", "Πόλη"]
    print("profile ok", result["quality"])
