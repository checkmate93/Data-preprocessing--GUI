"""Heuristic cleaning_config from a dataframe profile. No network call."""

import logging
import re

import yaml

from utils.structural_ops import to_snake

logger = logging.getLogger(__name__)

CLEANING_CONFIG_SCHEMA = {
    "target_column": "string or null. Label column, for example survived.",
    "test_size": "float. Fraction held out after structural cleaning.",
    "random_state": "int.",
    "rename_map": "mapping of snake_case source column to new name.",
    "drop_columns": "list of snake_case columns to drop.",
    "type_casting": "mapping of column to numeric.",
    "string_cleaning": "mapping of column to lower_strip, upper_strip, or strip.",
    "feature_engineering": "extract_title_from_name, create_family_size, create_is_alone booleans.",
    "imputation": "column to {strategy: mode|median|grouped_median, group_by: [cols]}.",
    "outliers": "column to {strategy: log1p|iqr_clip, new_col, factor}.",
    "encoding": "binary_map and one_hot lists. Do not encode the target.",
    "scaling": "{method: standard, columns: [numeric columns to scale]}.",
}

_TARGET_NAMES = ("survived", "target", "label")
_GROUP_PREFERENCE = ("pclass", "sex", "embarked", "title")


def suggest_cleaning_config(profile, target_column=None):
    """Propose a leakage-safe cleaning_config from column statistics.

    Input: profile dict from profile_dataframe, optional target column name
    Output: cleaning_config dict
    Necessity: SchemaAdvisorNode when the user wants a suggestion before editing rules.
    """
    columns = profile.get("columns") or {}
    if not columns:
        raise ValueError("profile.columns is empty")
    n_rows = int(profile.get("shape", [0, 0])[0])
    metas = {}
    for original, meta in columns.items():
        name = to_snake(original)
        if name in metas:
            raise ValueError(f"Column names collide after normalization: {name}")
        metas[name] = meta

    target = _resolve_target(metas, target_column)
    drops = set()
    for name, meta in metas.items():
        if name == target:
            continue
        if _is_identifier(name, meta, n_rows) or _is_high_null(meta) or _is_high_cardinality(name, meta, n_rows):
            drops.add(name)
        if int(meta.get("unique") or 0) <= 1:
            drops.add(name)

    extract_title = "name" in metas
    if extract_title:
        drops.add("name")
    create_family = _has_any(metas, ("sibsp", "siblings_spouses")) and _has_any(
        metas, ("parch", "parents_children")
    )

    string_cleaning = {}
    type_casting = {}
    imputation = {}
    outliers = {}
    binary_map = {}
    one_hot = []
    log_sources = set()
    log_columns = []

    for name, meta in metas.items():
        if name in drops or name == target:
            continue
        kind = _kind(meta)
        if kind == "categorical" and _looks_like_numeric_text(meta):
            type_casting[name] = "numeric"
            kind = "numeric"
        null_pct = float(meta.get("null_pct") or 0)
        unique = int(meta.get("unique") or 0)
        if kind == "categorical":
            string_cleaning[name] = "lower_strip"
            categories = [str(value).strip().lower() for value in (meta.get("categories") or [])]
            if unique == 2 and len(categories) == 2:
                binary_map[name] = _binary_mapping(categories)
            elif unique <= 12:
                one_hot.append(name)
            if null_pct > 0:
                imputation[name] = {"strategy": "mode"}
        elif kind == "numeric":
            if null_pct > 0:
                group_by = _group_columns(metas, drops | {name, target})
                if group_by:
                    imputation[name] = {"strategy": "grouped_median", "group_by": group_by}
                else:
                    imputation[name] = {"strategy": "median"}
            skew = meta.get("skew")
            if skew is not None and abs(float(skew)) >= 1:
                new_col = f"{name}_log"
                outliers[name] = {"strategy": "log1p", "new_col": new_col}
                log_sources.add(name)
                log_columns.append(new_col)
            elif skew is not None and abs(float(skew)) >= 0.5:
                outliers[name] = {"strategy": "iqr_clip", "factor": 1.5}

    if extract_title:
        one_hot.append("title")
        imputation["title"] = {"strategy": "mode"}

    scale_columns = []
    for name, meta in metas.items():
        if name in drops or name == target or name in log_sources or name in binary_map:
            continue
        if _kind(meta) == "numeric" and int(meta.get("unique") or 0) > 2:
            scale_columns.append(name)
    if create_family:
        scale_columns.append("family_size")
    scale_columns.extend(log_columns)

    config = {
        "target_column": target,
        "test_size": 0.2,
        "random_state": 42,
        "rename_map": {},
        "drop_columns": sorted(drops),
        "type_casting": type_casting,
        "string_cleaning": string_cleaning,
        "feature_engineering": {
            "extract_title_from_name": extract_title,
            "create_family_size": create_family,
            "create_is_alone": create_family,
        },
        "imputation": imputation,
        "outliers": outliers,
        "encoding": {"binary_map": binary_map, "one_hot": sorted(set(one_hot))},
        "scaling": {"method": "standard", "columns": sorted(set(scale_columns))},
    }
    logger.info("Suggested drops=%s impute=%s", config["drop_columns"], list(imputation))
    return config


def build_advisor_prompt(profile):
    """Prompt for SchemaAdvisorNode. Pair it with call_llm(..., CLEANING_CONFIG_SCHEMA)."""
    compact = {
        "shape": profile.get("shape"),
        "duplicates_count": profile.get("duplicates_count"),
        "columns": profile.get("columns"),
    }
    profile_text = yaml.safe_dump(compact, sort_keys=False)
    example = yaml.safe_dump(
        {
            "target_column": "survived",
            "test_size": 0.2,
            "random_state": 42,
            "rename_map": {},
            "drop_columns": ["cabin", "passengerid"],
            "type_casting": {},
            "string_cleaning": {"sex": "lower_strip"},
            "feature_engineering": {
                "extract_title_from_name": True,
                "create_family_size": True,
                "create_is_alone": True,
            },
            "imputation": {"age": {"strategy": "median"}},
            "outliers": {},
            "encoding": {"binary_map": {"sex": {"male": 0, "female": 1}}, "one_hot": ["embarked"]},
            "scaling": {"method": "standard", "columns": ["age"]},
        },
        sort_keys=False,
    )
    return (
        "You are configuring a CSV preprocessing pipeline. "
        "Statistics such as medians and scaler means must later be fit on the train split only.\n"
        "Use snake_case column names produced by lowercasing and replacing spaces with underscores. "
        "Do not insert underscores inside PassengerId; passengerid is correct.\n"
        "Drop identifiers and columns with about 70 percent or more missing values. "
        "Do not encode or scale the target column.\n\n"
        f"Column profile:\n{profile_text}\n"
        f"Example shape:\n{example}"
    )


def _resolve_target(metas, target_column):
    if target_column:
        name = to_snake(target_column)
        if name not in metas:
            raise ValueError(f"target_column '{target_column}' is not in the profile")
        return name
    for candidate in _TARGET_NAMES:
        if candidate in metas:
            return candidate
    return None


def _is_identifier(name, meta, n_rows):
    unique = int(meta.get("unique") or 0)
    if name in {"id", "passengerid", "rowid", "row_id"} or name.endswith("_id"):
        return True
    return name.endswith("id") and unique == n_rows and _kind(meta) == "numeric"


def _is_high_null(meta):
    return float(meta.get("null_pct") or 0) >= 70


def _is_high_cardinality(name, meta, n_rows):
    if name == "name" or n_rows == 0 or _kind(meta) != "categorical":
        return False
    return int(meta.get("unique") or 0) / n_rows >= 0.5


def _has_any(metas, names):
    return any(name in metas for name in names)


def _kind(meta):
    dtype = str(meta.get("dtype") or "").lower()
    if any(token in dtype for token in ("int", "float", "double", "decimal")):
        return "numeric"
    return "categorical"


def _looks_like_numeric_text(meta):
    dtype = str(meta.get("dtype") or "").lower()
    if "object" not in dtype and "string" not in dtype:
        return False
    categories = meta.get("categories") or []
    if not categories:
        return False
    numeric = 0
    for value in categories:
        text = str(value).strip()
        if not text or re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", text) is None:
            return False
        numeric += 1
    return numeric > 0


def _group_columns(metas, skip):
    candidates = []
    for name, meta in metas.items():
        if name in skip:
            continue
        unique = int(meta.get("unique") or 0)
        if 2 <= unique <= 8:
            candidates.append(name)
    candidates.sort(key=lambda name: (_GROUP_PREFERENCE.index(name) if name in _GROUP_PREFERENCE else 99, name))
    return candidates[:2]


def _binary_mapping(categories):
    labels = set(categories)
    if labels == {"male", "female"}:
        return {"male": 0, "female": 1}
    ordered = sorted(categories)
    return {ordered[0]: 0, ordered[1]: 1}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    profile = {
        "shape": [8, 6],
        "duplicates_count": 0,
        "columns": {
            "PassengerId": {"dtype": "int64", "null_pct": 0.0, "unique": 8},
            "Survived": {"dtype": "int64", "null_pct": 0.0, "unique": 2, "skew": 0.0, "median": 0.5},
            "Age": {"dtype": "float64", "null_pct": 25.0, "unique": 5, "skew": 0.8, "median": 28.0},
            "Sex": {"dtype": "object", "null_pct": 0.0, "unique": 2, "categories": ["male", "female"]},
            "Cabin": {"dtype": "object", "null_pct": 75.0, "unique": 2, "categories": ["C85"]},
            "Name": {"dtype": "object", "null_pct": 0.0, "unique": 8, "categories": ["Braund, Mr. Owen"]},
            "SibSp": {"dtype": "int64", "null_pct": 0.0, "unique": 3, "skew": 1.2, "median": 0},
            "Parch": {"dtype": "int64", "null_pct": 0.0, "unique": 2, "skew": 0.1, "median": 0},
            "Pclass": {"dtype": "int64", "null_pct": 0.0, "unique": 3, "skew": 0.2, "median": 3},
        },
    }
    config = suggest_cleaning_config(profile)
    assert config["target_column"] == "survived"
    assert "passengerid" in config["drop_columns"]
    assert "cabin" in config["drop_columns"]
    assert "name" in config["drop_columns"]
    assert config["imputation"]["age"]["strategy"] == "grouped_median"
    assert config["encoding"]["binary_map"]["sex"] == {"male": 0, "female": 1}
    assert config["feature_engineering"]["create_family_size"] is True
    assert "survived" not in config["scaling"]["columns"]
    prompt = build_advisor_prompt(profile)
    assert "passengerid" in prompt
    print("schema_advisor ok", config["drop_columns"])
