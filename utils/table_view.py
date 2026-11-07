"""What the grid shows: search + sort + visible columns + one page. View only — it never changes the data.

Used by GET /data (one page) and by the export of "only what I see". The row order for a view
(search + sort) is computed once and cached per session, so paging through 1M rows does not re-sort
or re-search on every click.
"""

import math
import re

import numpy as np
import pandas as pd

from utils.json_safe import frame_rows

NUMERIC_QUERY = re.compile(r"^\s*(>=|<=|>|<|=|!=)\s*(-?[\d.,]+)\s*$")
RANGE_QUERY = re.compile(r"^\s*(-?[\d.,]+)\s*\.\.\s*(-?[\d.,]+)\s*$")


def normalize_text(series):
    """Lower case, no Greek/Latin accents: 'Αθήνα' and 'αθηνα' compare equal."""
    text = series.astype("string").str.lower().str.normalize("NFKD")
    return text.str.replace(r"[̀-ͯ]", "", regex=True)


def _plain(value):
    return normalize_text(pd.Series([value])).iloc[0]


def _number(text):
    text = text.strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return float(text.replace(",", ""))


def search_mask(df, query, scope=None):
    """Boolean mask of matching rows.
    - text: contained in any column (or in `scope`), case/accent-insensitive
    - with a numeric `scope` column: '>100', '<=5', '=3', '!=0', '10..20' compare numbers
    """
    query = (query or "").strip()
    if not query:
        return pd.Series(True, index=df.index)
    if scope:
        if scope not in df.columns:
            raise ValueError(f"Η στήλη '{scope}' δεν υπάρχει.")
        series = df[scope]
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            compare, between = NUMERIC_QUERY.match(query), RANGE_QUERY.match(query)
            if compare:
                op, value = compare.group(1), _number(compare.group(2))
                return {">": series.gt, ">=": series.ge, "<": series.lt, "<=": series.le,
                        "=": series.eq, "!=": series.ne}[op](value).fillna(False).astype(bool)
            if between:
                low, high = sorted((_number(between.group(1)), _number(between.group(2))))
                return series.between(low, high).fillna(False).astype(bool)
        columns = [scope]
    else:
        columns = list(df.columns)
    needle = _plain(query)
    mask = pd.Series(False, index=df.index)
    for column in columns:
        mask |= normalize_text(df[column]).str.contains(needle, regex=False).fillna(False).astype(bool)
    return mask


def view_positions(df, query="", scope=None, sort_by=None, descending=False):
    """Row positions (0..n-1) of the view, in display order."""
    positions = np.arange(len(df))
    if query and query.strip():
        positions = positions[search_mask(df, query, scope).to_numpy()]
    if sort_by and sort_by in df.columns:
        order = df[sort_by].iloc[positions].reset_index(drop=True).sort_values(
            ascending=not descending, na_position="last", kind="stable").index.to_numpy()
        positions = positions[order]
    return positions


def visible(df, hidden):
    """Columns to show: all except `hidden` (at least one). Unknown names are ignored, new columns stay visible."""
    if not hidden:
        return None
    columns = [c for c in df.columns if c not in set(hidden)]
    return columns or list(df.columns[:1])


def apply_view(df, query="", scope=None, sort_by=None, descending=False, columns=None):
    """The full view as a DataFrame (for "export what I see")."""
    frame = df.iloc[view_positions(df, query, scope, sort_by, descending)]
    if columns:
        frame = frame[[c for c in columns if c in frame.columns]]
    return frame


def page_payload(df, positions, page=1, size=50, columns=None):
    total = len(positions)
    size = max(1, min(int(size), 500))
    pages = max(1, math.ceil(total / size))
    page = max(1, min(int(page), pages))
    chunk = df.iloc[positions[(page - 1) * size: page * size]]
    if columns:
        chunk = chunk[[c for c in columns if c in chunk.columns]]
    payload = frame_rows(chunk, with_index=True)
    payload.update({"page": page, "size": size, "total_rows": total, "total_pages": pages, "all_rows": int(len(df))})
    return payload


class ViewCache:
    """Remembers the positions of the last view of one session (a few MB at most: 8 bytes per row)."""

    def __init__(self):
        self.key = None
        self.positions = None

    def positions_for(self, df, version, query, scope, sort_by, descending):
        key = (version, query.strip(), scope or "", sort_by or "", bool(descending))
        if key != self.key:
            self.positions = view_positions(df, query, scope, sort_by, descending)
            self.key = key
        return self.positions


if __name__ == "__main__":
    frame = pd.DataFrame({"city": ["Αθήνα", "ΑΘΗΝΑ ", "Πάτρα", None], "amount": [120.5, 80, 15000, 7]})
    assert search_mask(frame, "αθηνα").tolist() == [True, True, False, False]
    assert search_mask(frame, ">100", "amount").tolist() == [True, False, True, False]
    assert search_mask(frame, "50..200", "amount").tolist() == [True, True, False, False]
    assert search_mask(frame, "15000").tolist() == [False, False, True, False]
    assert view_positions(frame, "", None, "amount", True).tolist() == [2, 0, 1, 3]
    page = page_payload(frame, view_positions(frame, "α"), 1, 2, ["city"])
    assert page["total_rows"] == 3 and page["all_rows"] == 4 and [c["name"] for c in page["columns"]] == ["city"]
    print("table_view ok")
