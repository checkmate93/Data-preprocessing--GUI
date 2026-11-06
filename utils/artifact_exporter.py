"""Save the cleaned splits and a standalone pandas script of the chosen rules."""

import logging
import pprint
from pathlib import Path

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path(__file__).resolve().parent.parent / "exports"

_SCRIPT = '''\
"""DataPrep Studio preprocess script. Session: __SESSION__

Run from this folder after pointing RAW_CSV at the original upload:
    python preprocess.py
Statistics are fit on the train split only, then applied to the test split.
"""

from pathlib import Path
import re

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

RAW_CSV = "raw.csv"
HAS_TEST = __HAS_TEST__
CONFIG = __CONFIG__

SIBLING_COLUMNS = ("siblings_spouses", "sibsp")
PARENT_COLUMNS = ("parents_children", "parch")


def to_snake(name):
    text = str(name).strip()
    text = re.sub(r"[\\s\\-]+", "_", text)
    text = re.sub(r"[^0-9A-Za-z_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text.lower()


def apply_structural(df):
    frame = df.copy()
    frame.columns = [to_snake(column) for column in frame.columns]
    if len(frame.columns) != len(set(frame.columns)):
        raise ValueError(f"Column names collide after normalization: {list(frame.columns)}")
    rename_map = CONFIG.get("rename_map") or {}
    missing = [name for name in rename_map if name not in frame.columns]
    if missing:
        raise ValueError(f"rename_map columns are not in the dataframe: {missing}")
    frame = frame.rename(columns=rename_map)
    frame = frame.drop_duplicates().reset_index(drop=True)

    for column, how in (CONFIG.get("string_cleaning") or {}).items():
        cleaned = frame[column].astype("string").str.strip()
        if how == "lower_strip":
            cleaned = cleaned.str.lower()
        elif how == "upper_strip":
            cleaned = cleaned.str.upper()
        elif how != "strip":
            raise ValueError(f"Unsupported string cleaning '{how}' for {column}")
        frame[column] = cleaned.mask(cleaned.str.len() == 0, pd.NA)

    for column, kind in (CONFIG.get("type_casting") or {}).items():
        if kind != "numeric":
            raise ValueError(f"Unsupported type cast '{kind}' for {column}")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    features = CONFIG.get("feature_engineering") or {}
    if features.get("extract_title_from_name"):
        frame["title"] = (
            frame["name"].astype("string").str.extract(r",\\s*([^.]+)\\.", expand=False).str.strip().str.title()
        )
        frame = frame.drop(columns=["name"])
    if features.get("create_family_size") or features.get("create_is_alone"):
        sibling = next(name for name in SIBLING_COLUMNS if name in frame.columns)
        parent = next(name for name in PARENT_COLUMNS if name in frame.columns)
        family_size = frame[sibling] + frame[parent] + 1
        if features.get("create_family_size"):
            frame["family_size"] = family_size
        if features.get("create_is_alone"):
            frame["is_alone"] = (family_size == 1).astype(int)

    drop_columns = [column for column in (CONFIG.get("drop_columns") or []) if column in frame.columns]
    if drop_columns:
        frame = frame.drop(columns=drop_columns)
    return frame


def _group_keys(frame, group_by):
    parts = [frame[column].astype("string").fillna("__NA__") for column in group_by]
    key = parts[0]
    for part in parts[1:]:
        key = key + "|" + part
    return key


def impute_and_outliers(train_df, test_df):
    train = train_df.copy()
    test = None if test_df is None else test_df.copy()
    frames = [train] if test is None else [train, test]

    for column, spec in (CONFIG.get("imputation") or {}).items():
        strategy = spec["strategy"]
        if strategy == "mode":
            value = train[column].dropna().mode().iloc[0]
            for frame in frames:
                frame[column] = frame[column].fillna(value)
        elif strategy == "median":
            value = train[column].median()
            for frame in frames:
                frame[column] = frame[column].fillna(value)
        elif strategy == "grouped_median":
            group_by = spec["group_by"]
            keys = _group_keys(train, group_by)
            medians = train.assign(_key=keys).groupby("_key")[column].median()
            global_median = float(train[column].median())
            lookup = {
                str(key): global_median if pd.isna(median) else float(median)
                for key, median in medians.items()
            }
            for frame in frames:
                fill_values = _group_keys(frame, group_by).map(lookup).fillna(global_median)
                missing = frame[column].isna()
                frame.loc[missing, column] = fill_values.loc[missing].to_numpy()
        else:
            raise ValueError(f"Unsupported imputation strategy '{strategy}' for {column}")

    for column, spec in (CONFIG.get("outliers") or {}).items():
        strategy = spec["strategy"]
        if strategy == "log1p":
            new_col = spec.get("new_col") or f"{column}_log"
            for frame in frames:
                frame[new_col] = np.log1p(frame[column].clip(lower=0))
        elif strategy == "iqr_clip":
            factor = float(spec.get("factor", 1.5))
            q1 = float(train[column].quantile(0.25))
            q3 = float(train[column].quantile(0.75))
            lower = q1 - factor * (q3 - q1)
            upper = q3 + factor * (q3 - q1)
            for frame in frames:
                frame[column] = frame[column].clip(lower, upper)
        else:
            raise ValueError(f"Unsupported outlier strategy '{strategy}' for {column}")
    return train, test


def encode_and_scale(train_df, test_df):
    train = train_df.copy()
    test = None if test_df is None else test_df.copy()
    encoding = CONFIG.get("encoding") or {}
    target = CONFIG.get("target_column")
    binary_map = encoding.get("binary_map") or {}
    one_hot = [column for column in (encoding.get("one_hot") or []) if column not in binary_map]

    for column, mapping in binary_map.items():
        train[column] = train[column].map(mapping)
        if test is not None:
            test[column] = test[column].map(mapping)

    if one_hot:
        train_dummies = pd.get_dummies(train[one_hot], drop_first=True, dtype="int64")
        train = pd.concat([train.drop(columns=one_hot), train_dummies], axis=1)
        if test is not None:
            test_dummies = pd.get_dummies(test[one_hot], dtype="int64")
            test_dummies = test_dummies.reindex(columns=train_dummies.columns, fill_value=0)
            test = pd.concat([test.drop(columns=one_hot), test_dummies], axis=1)

    if test is not None:
        test = test.reindex(columns=train.columns, fill_value=0)

    scaling = CONFIG.get("scaling") or {}
    columns = [column for column in (scaling.get("columns") or []) if column != target]
    if columns:
        float_columns = {column: "float64" for column in columns}
        train = train.astype(float_columns)
        if test is not None:
            test = test.astype(float_columns)
        scaler = StandardScaler()
        train.loc[:, columns] = scaler.fit_transform(train[columns])
        if test is not None:
            test.loc[:, columns] = scaler.transform(test[columns])
    return train, test


def split_dataset(df):
    target = CONFIG.get("target_column")
    splitter = {
        "test_size": CONFIG.get("test_size", 0.2),
        "random_state": CONFIG.get("random_state", 42),
    }
    if target and target in df.columns:
        splitter["stratify"] = df[target]
    return train_test_split(df, **splitter)


def main():
    frame = apply_structural(pd.read_csv(Path(RAW_CSV)))
    if HAS_TEST:
        train_df, test_df = split_dataset(frame)
    else:
        train_df, test_df = frame, None
    train_df, test_df = impute_and_outliers(train_df, test_df)
    train_df, test_df = encode_and_scale(train_df, test_df)
    train_df.to_csv("train_clean.csv", index=False)
    if test_df is not None:
        test_df.to_csv("test_clean.csv", index=False)


if __name__ == "__main__":
    main()
'''


def export_artifacts(session_id, train_df, test_df, config, folder=None):
    """Write train/test CSV files and a standalone preprocess.py.

    Input: session_id, train_df, test_df, config, optional folder (default exports/<session_id>)
    Output: dict with train_csv_path, test_csv_path, script_path, generated_python_code
    Necessity: EncodeAndScaleNode (v1) and the ML Prep button. The script refits every statistic on the train split.
    """
    if not session_id or any(token in str(session_id) for token in ("/", "\\", "..")):
        raise ValueError("session_id must be a plain folder name")
    if train_df is None:
        raise ValueError("train_df is required")

    from utils.structural_ops import normalize_cleaning_config

    folder = Path(folder) if folder else EXPORT_ROOT / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    train_path = folder / "train_clean.csv"
    train_df.to_csv(train_path, index=False)
    test_path = None
    if test_df is not None:
        test_path = folder / "test_clean.csv"
        test_df.to_csv(test_path, index=False)

    normalized = normalize_cleaning_config(config)
    code = (
        _SCRIPT.replace("__SESSION__", str(session_id))
        .replace("__HAS_TEST__", "True" if test_df is not None else "False")
        .replace("__CONFIG__", pprint.pformat(normalized, sort_dicts=False))
    )
    script_path = folder / "preprocess.py"
    script_path.write_text(code, encoding="utf-8")
    logger.info("Exported session %s to %s", session_id, folder)
    return {
        "train_csv_path": str(train_path),
        "test_csv_path": None if test_path is None else str(test_path),
        "script_path": str(script_path),
        "generated_python_code": code,
    }


def pd_sample():
    import pandas as pd

    return pd.DataFrame(
        {
            "PassengerId": list(range(1, 11)),
            "Survived": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "Pclass": [3, 1, 3, 1, 2, 3, 2, 1, 3, 2],
            "Name": [
                "Braund, Mr. Owen",
                "Cumings, Mrs. John",
                "Heikkinen, Miss. Laina",
                "Futrelle, Mrs. Jacques",
                "Allen, Mr. William",
                "Moran, Mr. James",
                "Bonnell, Miss. Elizabeth",
                "Hewlett, Mrs. Mary",
                "Johnson, Master. Eric",
                "Nasser, Mrs. Nicholas",
            ],
            "Sex": ["male", "female", "female", "female", "male", "male", "female", "female", "male", "female"],
            "Age": [22, 38, 26, None, 35, 28, 19, 55, 9, 42],
            "SibSp": [1, 1, 0, 1, 0, 0, 0, 0, 1, 0],
            "Parch": [0, 0, 0, 0, 0, 0, 1, 0, 2, 0],
            "Ticket": [f"T{i}" for i in range(10)],
            "Fare": [7.25, 71.3, 7.9, 53.1, 8.05, 8.4, 16.0, 80.0, 11.1, 30.0],
            "Cabin": [None, "C85", None, "C123", None, None, None, None, None, None],
            "Embarked": ["S", "C", "S", "S", None, "Q", "S", "C", "S", "C"],
        }
    )


if __name__ == "__main__":
    import shutil
    import subprocess
    import sys

    from sklearn.model_selection import train_test_split

    from utils.encode_scale_ops import fit_apply_encoding_and_scaling
    from utils.pandas_profiler import profile_dataframe
    from utils.schema_advisor import suggest_cleaning_config
    from utils.stat_transformers import fit_apply_imputation_and_outliers
    from utils.structural_ops import apply_structural_cleaning

    logging.basicConfig(level=logging.INFO)
    raw = pd_sample()
    raw_path = EXPORT_ROOT / "_raw_preview.csv"
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    raw.to_csv(raw_path, index=False)
    loaded = __import__("pandas").read_csv(raw_path)
    profile = profile_dataframe(loaded)
    config = suggest_cleaning_config(profile, target_column="Survived")
    cleaned = apply_structural_cleaning(loaded, config)
    train_df, test_df = train_test_split(
        cleaned,
        test_size=config["test_size"],
        random_state=config["random_state"],
        stratify=cleaned[config["target_column"]],
    )
    train_df, test_df, _fitted = fit_apply_imputation_and_outliers(train_df, test_df, config)
    train_df, test_df, _info = fit_apply_encoding_and_scaling(train_df, test_df, config)
    assert int(train_df.isna().sum().sum()) == 0
    assert int(test_df.isna().sum().sum()) == 0
    assert list(train_df.columns) == list(test_df.columns)
    exported = export_artifacts("dataprep_demo", train_df, test_df, config)
    demo = Path(exported["script_path"]).parent
    raw_path.replace(demo / "raw.csv")
    subprocess.run([sys.executable, str(demo / "preprocess.py")], cwd=demo, check=True)
    pandas = __import__("pandas")
    from_script_train = pandas.read_csv(demo / "train_clean.csv")
    from_script_test = pandas.read_csv(demo / "test_clean.csv")
    pandas.testing.assert_frame_equal(
        from_script_train.reset_index(drop=True),
        train_df.reset_index(drop=True),
        check_dtype=False,
        rtol=1e-5,
        atol=1e-5,
    )
    pandas.testing.assert_frame_equal(
        from_script_test.reset_index(drop=True),
        test_df.reset_index(drop=True),
        check_dtype=False,
        rtol=1e-5,
        atol=1e-5,
    )
    assert "train_test_split" in exported["generated_python_code"]
    assert "StandardScaler" in exported["generated_python_code"]
    shutil.rmtree(demo)
    print("artifact_exporter ok", list(train_df.columns))
