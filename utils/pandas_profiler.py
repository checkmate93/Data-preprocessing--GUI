"""Profile a DataFrame for the upload inspector and the final numeric check."""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def profile_dataframe(df):
    """Summarize a dataframe for the React inspector and the schema advisor.

    Input: df (pd.DataFrame)
    Output: dict with shape, dtypes, missing_counts, missing_pct, duplicates_count,
    numeric_stats, categorical_stats, columns, sample_rows, total_nulls, all_numeric.
    Necessity: ProfileAndInspectNode and the final check inside EncodeAndScaleNode.
    """
    logger.info("Profiling dataframe shape=%s", tuple(df.shape))
    n_rows, n_cols = df.shape
    dtypes = {column: str(dtype) for column, dtype in df.dtypes.items()}
    missing_counts = {column: int(df[column].isna().sum()) for column in df.columns}
    missing_pct = {
        column: 0.0 if n_rows == 0 else round(missing_counts[column] / n_rows * 100, 2)
        for column in df.columns
    }
    numeric_df = df.select_dtypes(include="number")
    categorical_df = df.drop(columns=numeric_df.columns)
    numeric_stats = _numeric_stats(numeric_df)
    categorical_stats = _categorical_stats(categorical_df)
    columns = {}
    for column in df.columns:
        meta = {
            "dtype": dtypes[column],
            "null_count": missing_counts[column],
            "null_pct": missing_pct[column],
            "unique": int(df[column].nunique(dropna=True)),
        }
        if column in numeric_stats:
            meta["skew"] = numeric_stats[column]["skew"]
            meta["median"] = numeric_stats[column]["median"]
            meta["mean"] = numeric_stats[column]["mean"]
        else:
            meta["top"] = categorical_stats[column]["top"]
            meta["categories"] = categorical_stats[column]["categories"]
        columns[column] = meta

    sample_n = min(5, n_rows)
    if sample_n == 0:
        sample_rows = []
    else:
        sample = df.sample(n=sample_n, random_state=42)
        sample_rows = [
            {column: _to_builtin(value) for column, value in row.items()}
            for row in sample.to_dict(orient="records")
        ]

    profile = {
        "shape": [int(n_rows), int(n_cols)],
        "dtypes": dtypes,
        "missing_counts": missing_counts,
        "missing_pct": missing_pct,
        "duplicates_count": int(df.duplicated().sum()),
        "numeric_stats": numeric_stats,
        "categorical_stats": categorical_stats,
        "columns": columns,
        "sample_rows": sample_rows,
        "total_nulls": int(df.isna().sum().sum()),
        "all_numeric": _all_numeric(df),
    }
    logger.info(
        "Profile ready columns=%s nulls=%s all_numeric=%s",
        n_cols,
        profile["total_nulls"],
        profile["all_numeric"],
    )
    return profile


def _numeric_stats(numeric_df):
    stats = {}
    if numeric_df.empty:
        return stats
    described = numeric_df.describe()
    skews = numeric_df.skew(numeric_only=True)
    for column in numeric_df.columns:
        column_stats = {
            key: _to_builtin(value) for key, value in described[column].to_dict().items()
        }
        column_stats["skew"] = _to_builtin(skews[column])
        column_stats["median"] = _to_builtin(numeric_df[column].median())
        column_stats["mean"] = column_stats.get("mean")
        column_stats["unique"] = int(numeric_df[column].nunique(dropna=True))
        stats[column] = column_stats
    return stats


def _categorical_stats(categorical_df):
    stats = {}
    for column in categorical_df.columns:
        series = categorical_df[column]
        present = series.dropna()
        top = None
        freq = 0
        if not present.empty:
            modes = present.mode()
            top = _to_builtin(modes.iloc[0])
            freq = int((present == modes.iloc[0]).sum())
        unique_count = int(series.nunique(dropna=True))
        limit = unique_count if unique_count <= 20 else 5
        categories = [_to_builtin(value) for value in present.drop_duplicates().head(limit)]
        stats[column] = {
            "unique": unique_count,
            "top": top,
            "freq": freq,
            "categories": categories,
        }
    return stats


def _all_numeric(df):
    if df.empty and len(df.columns) == 0:
        return False
    return all(pd.api.types.is_numeric_dtype(dtype) for dtype in df.dtypes)


def _to_builtin(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if np.isnan(value):
            return None
        return round(float(value), 6)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value if isinstance(value, (int, str)) else str(value)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo = pd.DataFrame(
        {
            "Age": [22, None, 26, 35],
            "Sex": ["male", "female", "female", "male"],
            "Cabin": [None, "C85", None, None],
        }
    )
    report = profile_dataframe(demo)
    assert report["shape"] == [4, 3]
    assert report["missing_counts"]["Age"] == 1
    assert report["columns"]["Age"]["median"] == 26
    assert report["duplicates_count"] == 0
    assert report["all_numeric"] is False
    print("pandas_profiler ok", report["shape"], report["missing_pct"])
