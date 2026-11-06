"""Summarize what an operation changed, for the before/after panel."""

import pandas as pd


def diff_summary(before, after):
    added = [c for c in after.columns if c not in before.columns]
    removed = [c for c in before.columns if c not in after.columns]
    common = [c for c in before.columns if c in after.columns]
    dtype_changes = [
        {"column": c, "from": str(before[c].dtype), "to": str(after[c].dtype)}
        for c in common
        if str(before[c].dtype) != str(after[c].dtype)
    ]
    changed_cells = None
    changed_columns = []
    if before.shape[0] == after.shape[0] and before.index.equals(after.index):
        changed_cells = 0
        for column in common:
            left, right = before[column], after[column]
            both_missing = left.isna() & right.isna()
            differs = (left.astype(object) != right.astype(object)) & ~both_missing
            count = int(differs.sum())
            if count:
                changed_cells += count
                changed_columns.append(column)
    return {
        "shape_before": [int(before.shape[0]), int(before.shape[1])],
        "shape_after": [int(after.shape[0]), int(after.shape[1])],
        "rows_removed": int(max(before.shape[0] - after.shape[0], 0)),
        "added_columns": added,
        "removed_columns": removed,
        "dtype_changes": dtype_changes,
        "changed_cells": changed_cells,
        "changed_columns": changed_columns,
        "missing_before": int(before.isna().sum().sum()),
        "missing_after": int(after.isna().sum().sum()),
    }


if __name__ == "__main__":
    a = pd.DataFrame({"x": [1, None], "y": ["a", "b"]})
    b = a.fillna(0).rename(columns={"y": "z"})
    summary = diff_summary(a, b)
    assert summary["changed_cells"] == 1 and summary["added_columns"] == ["z"]
    print("diff ok", summary)
