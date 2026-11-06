"""Turn pandas / numpy values into plain JSON values for the React client."""

import datetime as dt
import decimal
import math

import numpy as np
import pandas as pd


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return frame_rows(value)
    if isinstance(value, pd.Series):
        return [to_jsonable(v) for v in value.tolist()]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return round(value, 6)
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def frame_rows(df, with_index=False):
    """{"columns": [{"name", "dtype"}], "rows": [[...]], "index": [...]} — compact for the grid."""
    payload = {
        "columns": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
        "rows": [[to_jsonable(v) for v in row] for row in df.itertuples(index=False, name=None)],
    }
    if with_index:
        payload["index"] = [to_jsonable(v) for v in df.index.tolist()]
    return payload


def df_page(df, page=1, size=50, sort_by=None, descending=False):
    total = len(df)
    size = max(1, min(int(size), 500))
    pages = max(1, math.ceil(total / size))
    page = max(1, min(int(page), pages))
    frame = df
    if sort_by and sort_by in df.columns:
        frame = df.sort_values(sort_by, ascending=not descending, na_position="last", kind="stable")
    chunk = frame.iloc[(page - 1) * size: page * size]
    payload = frame_rows(chunk, with_index=True)
    payload.update({"page": page, "size": size, "total_rows": total, "total_pages": pages})
    return payload


if __name__ == "__main__":
    frame = pd.DataFrame({"a": [1.0, np.nan], "b": [pd.Timestamp("2024-01-01"), pd.NaT]})
    page = df_page(frame)
    assert page["rows"] == [[1.0, "2024-01-01T00:00:00"], [None, None]]
    print("json_safe ok")
