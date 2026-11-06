"""Read any supported file into a DataFrame."""

import json
import logging
import re
import warnings

import pandas as pd

logger = logging.getLogger(__name__)


def read_any(path, fmt, options):
    """Input: path, format from detect_format, options {encoding, delimiter, decimal, sheet}.
    Output: (df, warnings_list, read_info) where read_info = {"text_columns": [...]} (columns kept as
    text so pipeline.py can read them the same way). Raises on decode or parse errors so the node can
    retry with the next encoding.
    """
    notes = []
    keep_text = []
    if fmt == "csv":
        csv_options = {
            "encoding": options.get("encoding") or "utf-8",
            "sep": options.get("delimiter") or ",",
            "on_bad_lines": "skip",
        }
        keep_text = _leading_zero_columns(path, csv_options)
        if keep_text:
            notes.append(f"Οι στήλες {', '.join(keep_text)} κρατήθηκαν ως κείμενο: έχουν μηδενικά μπροστά (π.χ. ΑΦΜ, ΤΚ, κωδικοί)")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df = pd.read_csv(
                path,
                encoding=csv_options["encoding"],
                sep=csv_options["sep"],
                decimal=options.get("decimal") or ".",
                dtype={column: "string" for column in keep_text} or None,
                on_bad_lines="warn",
                low_memory=False,
            )
        skipped = sum(len(re.findall(r"Skipping line", str(w.message))) for w in caught)
        if skipped:
            notes.append(f"{skipped} γραμμές με λάθος αριθμό πεδίων παραλείφθηκαν")
    elif fmt == "excel":
        df = pd.read_excel(path, sheet_name=options.get("sheet") or 0, engine="openpyxl")
    elif fmt == "json":
        with open(path, "r", encoding=options.get("encoding") or "utf-8") as handle:
            data = json.load(handle)
        df = _json_to_frame(data)
    elif fmt == "jsonl":
        df = pd.read_json(path, lines=True, encoding=options.get("encoding") or "utf-8")
    elif fmt == "parquet":
        df = pd.read_parquet(path)
    elif fmt == "feather":
        df = pd.read_feather(path)
    else:
        raise ValueError(f"Μη υποστηριζόμενο format: {fmt}")

    df.columns = [str(column) for column in df.columns]
    unnamed = [c for c in df.columns if c.startswith("Unnamed:") and df[c].isna().all()]
    if unnamed:
        df = df.drop(columns=unnamed)
        notes.append(f"Αφαιρέθηκαν {len(unnamed)} κενές στήλες χωρίς όνομα")
    if df.shape[1] == 0 or df.shape[0] == 0:
        raise ValueError("Το αρχείο δεν περιέχει γραμμές ή στήλες δεδομένων.")
    logger.info("Read %s shape=%s", fmt, df.shape)
    return df, notes, {"text_columns": keep_text}


def _leading_zero_columns(path, csv_options, sample_rows=5000):
    """Columns like ΑΦΜ '094014201' or ΤΚ '01234' would lose the zero if pandas parses them as numbers."""
    sample = pd.read_csv(path, dtype=str, nrows=sample_rows, keep_default_na=False, **csv_options)
    return [
        str(column) for column in sample.columns
        if sample[column].str.strip().str.fullmatch(r"0\d+").any()
    ]


def _json_to_frame(data):
    """List of records, or a dict whose first list value holds the records."""
    if isinstance(data, dict):
        lists = [value for value in data.values() if isinstance(value, list)]
        data = lists[0] if lists else [data]
    if not isinstance(data, list):
        raise ValueError("Το JSON πρέπει να είναι λίστα από αντικείμενα.")
    return pd.json_normalize(data)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    csv_path = folder / "a.csv"
    csv_path.write_text("a;b\n1;2,5\n3;4\n", encoding="utf-8")
    frame, notes, _ = read_any(csv_path, "csv", {"delimiter": ";", "decimal": ","})
    assert frame["b"].tolist() == [2.5, 4.0]
    json_path = folder / "a.json"
    json_path.write_text('{"items": [{"x": 1, "y": {"z": 2}}]}', encoding="utf-8")
    frame, _, _ = read_any(json_path, "json", {})
    assert list(frame.columns) == ["x", "y.z"]
    print("file_reader ok")
