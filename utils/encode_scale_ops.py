"""Encode categories and scale numeric columns. Scaler statistics come from train only."""

import logging

import pandas as pd
from sklearn.preprocessing import StandardScaler

from utils.structural_ops import normalize_cleaning_config

logger = logging.getLogger(__name__)


def fit_apply_encoding_and_scaling(train_df, test_df, config):
    """Binary-map, one-hot encode, align test columns, then standard-scale.

    Input: train_df, test_df (or None), config
    Output: (train_df, test_df, fitted_scaler_info)
    Necessity: EncodeAndScaleNode. The test split is reindexed onto the train columns.
    """
    cfg = normalize_cleaning_config(config)
    train = train_df.copy()
    test = None if test_df is None else test_df.copy()
    target = cfg.get("target_column")
    binary_map = cfg["encoding"].get("binary_map") or {}
    one_hot = [column for column in cfg["encoding"].get("one_hot") or [] if column not in binary_map]

    for column in list(binary_map) + one_hot:
        if column == target:
            raise ValueError(f"Refusing to encode the target column '{target}'")

    _apply_binary(train, binary_map)
    if test is not None:
        _apply_binary(test, binary_map)

    dummy_columns = []
    if one_hot:
        train, test, dummy_columns = _one_hot(train, test, one_hot)

    if test is not None:
        test = test.reindex(columns=train.columns, fill_value=0)

    scale_columns = []
    scaler_info = {"method": cfg["scaling"].get("method", "standard"), "columns": [], "mean": [], "scale": []}
    requested = cfg["scaling"].get("columns") or []
    if requested:
        if scaler_info["method"] != "standard":
            raise ValueError(f"Unsupported scaling method '{scaler_info['method']}'")
        scale_columns = [column for column in requested if column != target]
        missing = [column for column in scale_columns if column not in train.columns]
        if missing:
            raise ValueError(f"scaling columns are missing: {missing}")
        float_columns = {column: "float64" for column in scale_columns}
        train = train.astype(float_columns)
        if test is not None:
            test = test.astype(float_columns)
        scaler = StandardScaler()
        train.loc[:, scale_columns] = scaler.fit_transform(train[scale_columns])
        if test is not None:
            test.loc[:, scale_columns] = scaler.transform(test[scale_columns])
        scaler_info = {
            "method": "standard",
            "columns": scale_columns,
            "mean": [float(value) for value in scaler.mean_],
            "scale": [float(value) for value in scaler.scale_],
        }

    info = {
        "binary_map": binary_map,
        "one_hot_columns": dummy_columns,
        "output_columns": list(train.columns),
        "scaler": scaler_info,
    }
    logger.info("Encoded columns=%s scaled=%s", len(train.columns), scale_columns)
    return train, test, info


def _apply_binary(frame, binary_map):
    for column, mapping in binary_map.items():
        if column not in frame.columns:
            raise ValueError(f"binary_map column is missing: {column}")
        frame[column] = frame[column].map(mapping)


def _one_hot(train, test, columns):
    missing = [column for column in columns if column not in train.columns]
    if missing:
        raise ValueError(f"one_hot columns are missing: {missing}")
    train_dummies = pd.get_dummies(train[columns], drop_first=True, dtype="int64")
    train = pd.concat([train.drop(columns=columns), train_dummies], axis=1)
    if test is not None:
        test_missing = [column for column in columns if column not in test.columns]
        if test_missing:
            raise ValueError(f"one_hot columns are missing from test: {test_missing}")
        test_dummies = pd.get_dummies(test[columns], dtype="int64")
        test_dummies = test_dummies.reindex(columns=train_dummies.columns, fill_value=0)
        test = pd.concat([test.drop(columns=columns), test_dummies], axis=1)
    return train, test, list(train_dummies.columns)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    train = pd.DataFrame(
        {
            "survived": [0, 1, 0, 1],
            "sex": ["male", "female", "female", "male"],
            "embarked": ["S", "C", "S", "Q"],
            "age": [22.0, 38.0, 26.0, 35.0],
        }
    )
    test = pd.DataFrame(
        {
            "survived": [1, 0],
            "sex": ["female", "male"],
            "embarked": ["S", "Z"],
            "age": [40.0, 28.0],
        }
    )
    config = {
        "target_column": "survived",
        "encoding": {
            "binary_map": {"sex": {"male": 0, "female": 1}},
            "one_hot": ["embarked"],
        },
        "scaling": {"method": "standard", "columns": ["age"]},
    }
    train_out, test_out, info = fit_apply_encoding_and_scaling(train, test, config)
    assert list(train_out.columns) == list(test_out.columns)
    assert "embarked" not in train_out.columns
    assert train_out["sex"].tolist() == [0, 1, 1, 0]
    assert abs(float(train_out["age"].mean())) < 1e-6
    assert "embarked_Z" not in test_out.columns
    assert info["scaler"]["columns"] == ["age"]
    print("encode_scale_ops ok", list(train_out.columns))
