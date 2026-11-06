"""Detect file format, character encoding and CSV dialect before reading."""

import codecs
import logging
import re
from pathlib import Path

from charset_normalizer import from_bytes

logger = logging.getLogger(__name__)

EXTENSIONS = {
    ".csv": "csv", ".tsv": "csv", ".txt": "csv", ".dat": "csv",
    ".xlsx": "excel", ".xlsm": "excel",
    ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl",
    ".parquet": "parquet", ".feather": "feather",
}
SUPPORTED_FORMATS = {"csv", "excel", "json", "jsonl", "parquet", "feather"}
FALLBACK_ENCODINGS = ["utf-8", "cp1253", "iso8859-7", "cp1252", "latin-1"]
DELIMITERS = [",", ";", "\t", "|"]


def detect_format(path, filename):
    """Input: saved path + original filename. Output: one of SUPPORTED_FORMATS or 'unknown'."""
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"ARROW1"):
        return "feather"
    extension = Path(filename).suffix.lower()
    if head.startswith(b"PK"):
        return "excel" if extension in ("", ".xlsx", ".xlsm") else "unknown"
    if extension in EXTENSIONS:
        return EXTENSIONS[extension]
    if b"\x00" not in head and head.strip():
        stripped = head.lstrip()
        if stripped[:1] in (b"[", b"{"):
            return "jsonl" if b"\n{" in head else "json"
        return "csv"
    return "unknown"


def _canonical(name):
    return codecs.lookup(name).name


def _decodes_as_utf8(sample):
    # Detection logic, not error handling: a strict utf-8 decode is the cheapest test.
    # The sample may end in the middle of a multi-byte character, so allow 3 trailing bytes.
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError as error:
        return error.start >= len(sample) - 3


def _greek_codepage(sample, min_ratio=0.3):
    """charset-normalizer confuses short Greek text with cp1251/cp1252. Test the Greek codepages
    directly: the bytes must decode cleanly and at least 30% of the letters must be Greek.
    Western text (é, ü) fails, because accented letters are a small share of its letters.
    Output: (encoding, confidence) or None.
    """
    # The two codepages differ mainly on accented capitals: 'Ά' is 0xA2 in cp1253 but 0xB6 in
    # iso8859-7, and the other codepage turns that byte into a symbol (’ or ¶). So the right one
    # yields MORE Greek letters. Ties go to cp1253 (Windows, the common case).
    best = None
    for encoding in ("cp1253", "iso8859-7"):
        try:  # detection, not error handling: an undefined byte rules the codepage out
            decoded = sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        letters = [ch for ch in decoded if ch.isalpha()]
        greek = sum(1 for ch in letters if "Ͱ" <= ch <= "Ͽ")
        if not letters or greek / len(letters) < min_ratio:
            continue
        if best is None or greek > best[1]:
            best = (encoding, greek, greek / len(letters))
    if best is None:
        return None
    return best[0], round(min(1.0, 0.7 + best[2] * 0.3), 2)


def detect_encoding(path, sample_bytes=200_000):
    """Output: {"encoding", "confidence", "alternatives"}."""
    with open(path, "rb") as handle:
        sample = handle.read(sample_bytes)
    if sample.startswith(codecs.BOM_UTF8):
        best, confidence = "utf-8-sig", 1.0
    elif sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        best, confidence = "utf-16", 1.0
    elif _decodes_as_utf8(sample):
        best, confidence = "utf-8", 1.0
    elif greek := _greek_codepage(sample):
        best, confidence = greek
    else:
        result = from_bytes(sample).best()
        best = result.encoding if result else "cp1252"
        confidence = round(1.0 - (result.chaos if result else 1.0), 2)
    alternatives = []
    for name in [best, *FALLBACK_ENCODINGS]:
        canonical = _canonical(name)
        if canonical not in alternatives:
            alternatives.append(canonical)
    logger.info("Encoding %s (confidence %s)", alternatives[0], confidence)
    return {"encoding": alternatives[0], "confidence": confidence, "alternatives": alternatives[1:]}


def sniff_csv(path, encoding, sample_chars=64_000):
    """Output: {"delimiter", "decimal"}. Picks the delimiter with the most consistent count per line."""
    with open(path, "r", encoding=encoding, errors="replace", newline="") as handle:
        text = handle.read(sample_chars)
    lines = [line for line in text.splitlines() if line.strip()][:30]
    if len(lines) > 1:
        lines = lines[:-1]  # the last line may be cut by the sample size
    best, best_score = ",", -1.0
    for delimiter in DELIMITERS:
        counts = [line.count(delimiter) for line in lines]
        if not counts or max(counts) == 0:
            continue
        mode = max(set(counts), key=counts.count)
        if mode == 0:
            continue
        consistency = counts.count(mode) / len(counts)
        score = consistency * 10 + min(mode, 50) / 50
        if score > best_score:
            best, best_score = delimiter, score
    decimal = "."
    if best != "," and re.search(r"(?<![\d,])\d+,\d+(?![\d,])", text):
        decimal = ","
    return {"delimiter": best, "decimal": decimal}


def list_sheets(path):
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True)
    names = list(workbook.sheetnames)
    workbook.close()
    return names


if __name__ == "__main__":
    import tempfile

    folder = Path(tempfile.mkdtemp())
    greek = folder / "greek.csv"
    greek.write_bytes("όνομα;ποσό\nΓιάννης;1,5\nΜαρία;2,75\n".encode("cp1253"))
    print(detect_format(greek, "greek.csv"))
    encoding = detect_encoding(greek)
    print(encoding)
    print(sniff_csv(greek, encoding["encoding"]))
    assert encoding["encoding"] in ("cp1253", "iso8859-7")
    assert sniff_csv(greek, encoding["encoding"]) == {"delimiter": ";", "decimal": ","}
    long_text = "Όνομα;Πόλη\n" + "Γιάννης;Αθήνα\n" * 200 + "Άννα;Ηράκλειο\nΆρης;Άργος\n"
    for codepage in ("cp1253", "iso8859-7"):  # they differ on 'Ά'
        path = folder / f"{codepage}.csv"
        path.write_bytes(long_text.encode(codepage))
        assert detect_encoding(path)["encoding"] == codepage, (codepage, detect_encoding(path))
    french = folder / "french.csv"
    french.write_bytes("ville;nom\nMontréal;Hélène Dubois\nZürich;Jürgen Müller\n".encode("cp1252"))
    assert detect_encoding(french)["encoding"] != "cp1253", detect_encoding(french)
    print("file_detect ok")
