"""Write the current dataset in the format the user picked."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EXPORT_FORMATS = {
    "csv": (".csv", "text/csv"),
    "excel": (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "json": (".json", "application/json"),
    "parquet": (".parquet", "application/octet-stream"),
}


def write_any(df, fmt, folder, stem, encoding="utf-8-sig", delimiter=","):
    """Output: {"path", "filename", "media_type"}. utf-8-sig keeps Greek readable in Excel."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"Μη υποστηριζόμενο format εξαγωγής: {fmt}")
    extension, media_type = EXPORT_FORMATS[fmt]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{extension}"
    if fmt == "csv":
        df.to_csv(path, index=False, encoding=encoding, sep=delimiter)
    elif fmt == "excel":
        df.to_excel(path, index=False, engine="openpyxl")
    elif fmt == "json":
        df.to_json(path, orient="records", force_ascii=False, date_format="iso", indent=2)
    else:
        df.to_parquet(path, index=False)
    logger.info("Exported %s rows to %s", len(df), path)
    return {"path": str(path), "filename": path.name, "media_type": media_type}


if __name__ == "__main__":
    import tempfile

    import pandas as pd

    out = write_any(pd.DataFrame({"πόλη": ["Αθήνα"]}), "csv", tempfile.mkdtemp(), "test")
    assert Path(out["path"]).read_bytes().startswith(b"\xef\xbb\xbf")
    print("file_writer ok", out)
