"""Fit imputation and outlier bounds on the train split, then transform both splits."""

import logging

import numpy as np
import pandas as pd

from utils.structural_ops import normalize_cleaning_config

logger = logging.getLogger(__name__)


def fit_apply_imputation_and_outliers(train_df, test_df, config):
    """Fill missing values and treat outliers without reading the test split.

    Input: train_df, test_df (or None), config
    Output: (train_df, test_df, fitted_params)
    Necessity: ImputeAndOutlierNode. Every statistic is computed from train_df only.
    """
    cfg = normalize_cleaning_config(config)
    train = train_df.copy()
    test = None if test_df is None else test_df.copy()
    fitted = {"imputation": {}, "outliers": {}}

    for column, spec in cfg["imputation"].items():
        fitted["imputation"][column] = _fit_apply_imputation(train, test, column, spec)

    for column, spec in cfg["outliers"].items():
        fitted["outliers"][column] = _fit_apply_outlier(train, test, column, spec)

    logger.info(
        "Fitted imputation=%s outliers=%s",
        list(fitted["imputation"]),
        list(fitted["outliers"]),
    )
    return train, test, fitted


def _fit_apply_imputation(train, test, column, spec):
    _require_column(train, column, "imputation")
    strategy = spec.get("strategy")
    if strategy == "mode":
        value = _mode(train[column], column)
        _fillna(train, column, value)
        if test is not None:
            _require_column(test, column, "imputation")
            _fillna(test, column, value)
        return {"strategy": "mode", "value": _plain(value)}

    if strategy == "median":
        value = _median(train[column], column)
        _fillna(train, column, value)
        if test is not None:
            _require_column(test, column, "imputation")
            _fillna(test, column, value)
        return {"strategy": "median", "value": float(value)}

    if strategy == "grouped_median":
        group_by = list(spec.get("group_by") or [])
        if not group_by:
            raise ValueError(f"grouped_median for {column} needs group_by")
        for name in group_by:
            _require_column(train, name, "grouped_median")
        keys = _group_keys(train, group_by)
        medians = train.assign(_key=keys).groupby("_key")[column].median()
        global_median = _median(train[column], column)
        lookup = {}
        for key, median in medians.items():
            lookup[str(key)] = float(global_median) if pd.isna(median) else float(median)
        _apply_grouped(train, column, group_by, lookup, float(global_median))
        if test is not None:
            _require_column(test, column, "imputation")
            for name in group_by:
                _require_column(test, name, "grouped_median")
            _apply_grouped(test, column, group_by, lookup, float(global_median))
        return {
            "strategy": "grouped_median",
            "group_by": group_by,
            "group_medians": lookup,
            "global_median": float(global_median),
        }

    raise ValueError(f"Unsupported imputation strategy '{strategy}' for {column}")


def _fit_apply_outlier(train, test, column, spec):
    _require_column(train, column, "outliers")
    if train[column].isna().any():
        raise ValueError(f"Column {column} still has missing values; impute it before outlier handling")
    strategy = spec.get("strategy")
    if strategy == "log1p":
        new_col = spec.get("new_col") or f"{column}_log"
        _apply_log1p(train, column, new_col)
        if test is not None:
            _require_column(test, column, "outliers")
            _apply_log1p(test, column, new_col)
        return {"strategy": "log1p", "new_col": new_col}

    if strategy == "iqr_clip":
        factor = float(spec.get("factor", 1.5))
        q1 = float(train[column].quantile(0.25))
        q3 = float(train[column].quantile(0.75))
        iqr = q3 - q1
        lower = q1 - factor * iqr
        upper = q3 + factor * iqr
        train[column] = train[column].clip(lower, upper)
        if test is not None:
            _require_column(test, column, "outliers")
            test[column] = test[column].clip(lower, upper)
        return {
            "strategy": "iqr_clip",
            "factor": factor,
            "lower": float(lower),
            "upper": float(upper),
        }

    raise ValueError(f"Unsupported outlier strategy '{strategy}' for {column}")


def _apply_log1p(frame, column, new_col):
    frame[new_col] = np.log1p(frame[column].clip(lower=0))


def _apply_grouped(frame, column, group_by, lookup, global_median):
    keys = _group_keys(frame, group_by)
    fill_values = keys.map(lookup).fillna(global_median)
    missing = frame[column].isna()
    frame.loc[missing, column] = fill_values.loc[missing].to_numpy()


def _group_keys(frame, group_by):
    parts = [frame[column].astype("string").fillna("__NA__") for column in group_by]
    key = parts[0]
    for part in parts[1:]:
        key = key + "|" + part
    return key


def _fillna(frame, column, value):
    frame[column] = frame[column].fillna(value)


def _mode(series, column):
    present = series.dropna()
    if present.empty:
        raise ValueError(f"Cannot impute {column}: train column is empty")
    return present.mode().iloc[0]


def _median(series, column):
    value = series.median()
    if pd.isna(value):
        raise ValueError(f"Cannot impute {column}: train column is empty")
    return value


def _require_column(frame, column, step):
    if column not in frame.columns:
        raise ValueError(f"{step} column is missing: {column}")


def _plain(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    train = pd.DataFrame(
        {
            "age": [22.0, None, 40.0, 30.0],
            "sex": ["male", "male", "female", "female"],
            "pclass": [3, 3, 1, 1],
            "embarked": ["S", None, "S", "C"],
            "fare": [7.25, 8.0, 71.0, 80.0],
        }
    )
    test = pd.DataFrame(
        {
            "age": [None, 100.0],
            "sex": ["male", "female"],
            "pclass": [3, 1],
            "embarked": [None, "Q"],
            "fare": [9.0, 200.0],
        }
    )
    config = {
        "imputation": {
            "age": {"strategy": "grouped_median", "group_by": ["pclass", "sex"]},
            "embarked": {"strategy": "mode"},
            "fare": {"strategy": "median"},
        },
        "outliers": {
            "fare": {"strategy": "log1p", "new_col": "fare_log"},
            "age": {"strategy": "iqr_clip", "factor": 1.5},
        },
    }
    train_out, test_out, fitted = fit_apply_imputation_and_outliers(train, test, config)
    male_p3 = train.loc[(train["sex"] == "male") & (train["pclass"] == 3), "age"].median()
    assert test_out.loc[0, "age"] == male_p3
    assert test_out.loc[0, "embarked"] == "S"
    assert test_out["fare"].isna().sum() == 0
    assert "fare_log" in train_out.columns
    assert fitted["imputation"]["fare"]["value"] == float(train["fare"].median())
    assert train["age"].isna().sum() == 1
    print("stat_transformers ok", fitted["imputation"]["age"]["group_medians"])
