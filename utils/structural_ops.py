"""Column-level cleaning that does not look at train/test statistics."""

import copy
import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

SIBLING_COLUMNS = ("siblings_spouses", "sibsp")
PARENT_COLUMNS = ("parents_children", "parch")


def to_snake(name):
    """Match the cleaning_config contract: lower case, spaces become underscores.

    PassengerId -> passengerid, so rename_map keys in the design stay valid.
    """
    text = str(name).strip()
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"[^0-9A-Za-z_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text.lower()


def normalize_cleaning_config(config):
    """Return a copy whose column names use the same spelling as to_snake."""
    cfg = copy.deepcopy(config or {})
    if cfg.get("target_column"):
        cfg["target_column"] = to_snake(cfg["target_column"])

    cfg["rename_map"] = {
        to_snake(source): to_snake(target)
        for source, target in (cfg.get("rename_map") or {}).items()
    }
    cfg["drop_columns"] = [to_snake(column) for column in (cfg.get("drop_columns") or [])]
    cfg["type_casting"] = {
        to_snake(column): kind for column, kind in (cfg.get("type_casting") or {}).items()
    }
    cfg["string_cleaning"] = {
        to_snake(column): how for column, how in (cfg.get("string_cleaning") or {}).items()
    }
    cfg["feature_engineering"] = dict(cfg.get("feature_engineering") or {})

    imputation = {}
    for column, spec in (cfg.get("imputation") or {}).items():
        updated = dict(spec)
        if "group_by" in updated:
            updated["group_by"] = [to_snake(name) for name in updated["group_by"]]
        imputation[to_snake(column)] = updated
    cfg["imputation"] = imputation

    outliers = {}
    for column, spec in (cfg.get("outliers") or {}).items():
        updated = dict(spec)
        if updated.get("new_col"):
            updated["new_col"] = to_snake(updated["new_col"])
        outliers[to_snake(column)] = updated
    cfg["outliers"] = outliers

    encoding = dict(cfg.get("encoding") or {})
    encoding["binary_map"] = {
        to_snake(column): dict(mapping)
        for column, mapping in (encoding.get("binary_map") or {}).items()
    }
    encoding["one_hot"] = [to_snake(column) for column in (encoding.get("one_hot") or [])]
    cfg["encoding"] = encoding

    scaling = dict(cfg.get("scaling") or {})
    scaling.setdefault("method", "standard")
    scaling["columns"] = [to_snake(column) for column in (scaling.get("columns") or [])]
    cfg["scaling"] = scaling
    cfg.setdefault("test_size", 0.2)
    cfg.setdefault("random_state", 42)
    return cfg


def apply_structural_cleaning(df, config):
    """Apply rename, drops, string cleanup, casts, and feature engineering.

    Input: df (pd.DataFrame), config (dict)
    Output: transformed_df (pd.DataFrame)
    Necessity: StructuralCleanNode. Statistics are not computed here.
    """
    cfg = normalize_cleaning_config(config)
    logger.info("Structural cleaning columns=%s", list(df.columns))
    frame = df.copy()
    frame.columns = _unique_snake(frame.columns)
    renamed = frame.columns.tolist()
    if len(renamed) != len(set(renamed)):
        raise ValueError(f"Column names collide after normalization: {renamed}")

    missing_renames = [name for name in cfg["rename_map"] if name not in frame.columns]
    if missing_renames:
        raise ValueError(f"rename_map columns are not in the dataframe: {missing_renames}")
    frame = frame.rename(columns=cfg["rename_map"])
    frame = frame.drop_duplicates().reset_index(drop=True)
    _clean_strings(frame, cfg["string_cleaning"])
    _cast_types(frame, cfg["type_casting"])
    _add_features(frame, cfg["feature_engineering"])

    drop_columns = [column for column in cfg["drop_columns"] if column in frame.columns]
    if drop_columns:
        frame = frame.drop(columns=drop_columns)
    logger.info("Structural cleaning done columns=%s", list(frame.columns))
    return frame


def _unique_snake(columns):
    return [to_snake(column) for column in columns]


def _clean_strings(frame, string_cleaning):
    for column, how in string_cleaning.items():
        if column not in frame.columns:
            raise ValueError(f"string_cleaning column is missing: {column}")
        if how not in {"lower_strip", "upper_strip", "strip"}:
            raise ValueError(f"Unsupported string cleaning '{how}' for {column}")
        cleaned = frame[column].astype("string").str.strip()
        if how == "lower_strip":
            cleaned = cleaned.str.lower()
        elif how == "upper_strip":
            cleaned = cleaned.str.upper()
        frame[column] = cleaned.mask(cleaned.str.len() == 0, pd.NA)


def _cast_types(frame, type_casting):
    for column, kind in type_casting.items():
        if column not in frame.columns:
            raise ValueError(f"type_casting column is missing: {column}")
        if kind != "numeric":
            raise ValueError(f"Unsupported type cast '{kind}' for {column}")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")


def _add_features(frame, feature_engineering):
    if feature_engineering.get("extract_title_from_name"):
        if "name" not in frame.columns:
            raise ValueError("extract_title_from_name requires a name column")
        if "title" in frame.columns:
            raise ValueError("title already exists; refusing to overwrite it")
        frame["title"] = (
            frame["name"]
            .astype("string")
            .str.extract(r",\s*([^.]+)\.", expand=False)
            .str.strip()
            .str.title()
        )
        del frame["name"]  # in place on purpose (callers pass the frame); inplace= is deprecated in pandas 3

    needs_family = feature_engineering.get("create_family_size") or feature_engineering.get(
        "create_is_alone"
    )
    if needs_family:
        sibling = _first_present(frame, SIBLING_COLUMNS, "sibling count")
        parent = _first_present(frame, PARENT_COLUMNS, "parent count")
        family_size = frame[sibling] + frame[parent] + 1
        if feature_engineering.get("create_family_size"):
            if "family_size" in frame.columns:
                raise ValueError("family_size already exists")
            frame["family_size"] = family_size
        if feature_engineering.get("create_is_alone"):
            if "is_alone" in frame.columns:
                raise ValueError("is_alone already exists")
            frame["is_alone"] = (family_size == 1).astype(int)


def _first_present(frame, options, label):
    for name in options:
        if name in frame.columns:
            return name
    raise ValueError(f"Cannot build {label}; looked for {list(options)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raw = pd.DataFrame(
        {
            "PassengerId": [1, 1],
            "Name": ["Braund, Mr. Owen", "Braund, Mr. Owen"],
            "Sex": [" male ", " male "],
            "SibSp": [1, 1],
            "Parch": [0, 0],
            "Cabin": ["C85", "C85"],
            "Fare": ["7.25", "7.25"],
        }
    )
    cleaned = apply_structural_cleaning(
        raw,
        {
            "rename_map": {"passengerid": "id"},
            "drop_columns": ["id", "cabin"],
            "string_cleaning": {"sex": "lower_strip"},
            "type_casting": {"fare": "numeric"},
            "feature_engineering": {
                "extract_title_from_name": True,
                "create_family_size": True,
                "create_is_alone": True,
            },
        },
    )
    assert list(cleaned.columns) == ["sex", "sibsp", "parch", "fare", "title", "family_size", "is_alone"]
    assert len(cleaned) == 1
    assert cleaned.loc[0, "title"] == "Mr"
    assert cleaned.loc[0, "family_size"] == 2
    assert int(cleaned.loc[0, "is_alone"]) == 0
    assert cleaned.loc[0, "sex"] == "male"
    assert cleaned.loc[0, "fare"] == 7.25
    print("structural_ops ok", cleaned.to_dict(orient="records"))
