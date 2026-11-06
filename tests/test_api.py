"""End-to-end test of the API: upload -> every button -> undo/redo -> export -> generated script."""

import os
import runpy
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="dataprep_test_")

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
from utils.ops.helpers import snake_case_name  # noqa: E402

RAW = (
    "Κωδικός Πελάτη;Όνομα Πελάτη;Πόλη;Ποσό Παραγγελίας;Ημερομηνία;Κατάσταση\n"
    "1;  Γιάννης  Παπαδόπουλος;Αθήνα;1.234,50;05/01/2024;Ενεργός\n"
    "2;Μαρία;αθήνα ;12,00;06/01/2024;N/A\n"
    "3;Νίκος;Πάτρα;;07/01/2024;Ανενεργός\n"
    "4;Ελένη;Θεσσαλονίκη;7;;Ενεργός\n"
    "5;Κώστας;-;99999;09/01/2024;Ενεργός\n"
    "5;Κώστας;-;99999;09/01/2024;Ενεργός\n"
    "6;Άννα;Πάτρα;15,5;10/01/2024;?\n"
)
FILENAME = "πελάτες.csv"
S = {name: snake_case_name(name) for name in RAW.splitlines()[0].split(";")}


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def session(client):
    response = client.post("/api/sessions", files={"file": (FILENAME, RAW.encode("cp1253"), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def op(client, sid, name, params=None, preview=False, status=200):
    response = client.post(f"/api/sessions/{sid}/ops", json={"op": name, "params": params or {}, "preview": preview})
    assert response.status_code == status, f"{name}: {response.text}"
    return response.json()


def test_upload_detects_greek_csv(session):
    source = session["source"]
    assert source["encoding"] in ("cp1253", "iso8859-7")
    assert source["delimiter"] == ";"
    assert source["decimal"] == ","
    assert session["profile"]["shape"] == [7, 6]
    assert session["page"]["rows"][0][1] == "  Γιάννης  Παπαδόπουλος"
    suggested = {s["op"] for s in session["suggestions"]}
    assert {"columns.snake_case", "missing.standardize", "text.strip", "duplicates.drop"} <= suggested


def test_catalog(client):
    data = client.get("/api/operations").json()
    assert len(data["operations"]) >= 80
    assert {c["id"] for c in data["categories"]} >= {"reshape", "charts", "ml"}
    assert all("schema" in o for o in data["operations"])


def test_inspect_buttons_do_not_create_versions(client, session):
    sid = session["session_id"]
    for name, params in [
        ("inspect.info", {}),
        ("inspect.describe", {"include": "all"}),
        ("inspect.head_tail_sample", {"mode": "sample", "n": 3}),
        ("inspect.missing", {}),
        ("inspect.value_counts", {"column": "Πόλη"}),
        ("inspect.duplicates", {}),
        ("inspect.file_encoding", {}),
    ]:
        data = op(client, sid, name, params)
        assert data["result"]["sections"], name
        assert data["history"]["current_version"] == 0, name
    dup = op(client, sid, "inspect.duplicates")["result"]["sections"][0]["items"][0]["value"]
    assert dup == 1


def test_errors_are_friendly(client, session):
    sid = session["session_id"]
    assert "Άγνωστη" in op(client, sid, "nope", status=400)["detail"]
    assert "Στήλη" in op(client, sid, "inspect.value_counts", {}, status=400)["detail"]
    assert "δεν υπάρχουν" in op(client, sid, "columns.drop", {"columns": ["xxx"]}, status=400)["detail"]


def test_preview_does_not_save(client, session):
    sid = session["session_id"]
    data = op(client, sid, "columns.snake_case", preview=True)
    assert data["result"]["preview"] is True
    assert data["result"]["preview_rows"]["columns"][0]["name"] == S["Κωδικός Πελάτη"]
    assert data["history"]["current_version"] == 0
    # Filling before type inference would fill numbers stored as text with a text mode: warn.
    warnings = op(client, sid, "missing.smart_fill", preview=True)["result"]["warnings"]
    assert any("Αυτόματοι τύποι" in w and "Ποσό Παραγγελίας" in w for w in warnings), warnings


def test_full_cleaning_pipeline_and_script(client, session):
    sid = session["session_id"]
    poso, poli, onoma = S["Ποσό Παραγγελίας"], S["Πόλη"], S["Όνομα Πελάτη"]
    date, status_col, code = S["Ημερομηνία"], S["Κατάσταση"], S["Κωδικός Πελάτη"]
    steps = [
        ("columns.snake_case", {}),
        ("missing.standardize", {}),
        ("text.strip", {}),
        ("types.auto_infer", {}),
        ("duplicates.drop", {}),
        ("text.case", {"columns": [poli], "mode": "title"}),
        ("missing.smart_fill", {}),
        ("missing.fill_value", {"columns": [status_col], "value": "Άγνωστη"}),
        ("datetime.extract_parts", {"column": date, "parts": ["year", "month", "weekday"]}),
        ("numeric.outliers_clip", {"columns": [poso], "method": "percentile", "lower_pct": 0, "upper_pct": 90}),
        ("categorical.label", {"columns": [status_col]}),
        ("categorical.one_hot", {"columns": [poli]}),
        ("rows.filter", {"conditions": [{"column": poso, "op": ">", "value": "10"}]}),
        ("rows.sort", {"columns": [poso], "ascending": False}),
        ("columns.rename", {"mapping": {onoma: "customer"}}),
        ("types.to_numeric", {"columns": [code]}),
        ("columns.drop", {"columns": [code]}),
        ("missing.drop_rows", {"how": "all"}),
    ]
    for name, params in steps:
        data = op(client, sid, name, params)
        assert data["result"]["status"] == "ok", name
    assert data["history"]["current_version"] == len(steps)

    frame = client.get(f"/api/sessions/{sid}/data?size=100").json()
    names = [c["name"] for c in frame["columns"]]
    assert "customer" in names and code not in names
    assert f"{poli}_Αθήνα" in names
    customers = [row[names.index("customer")] for row in frame["rows"]]
    assert "Γιάννης Παπαδόπουλος" in customers  # strip + collapse_spaces worked
    amounts = [row[names.index(poso)] for row in frame["rows"]]
    assert amounts == sorted(amounts, reverse=True) and min(amounts) > 10
    profile = client.get(f"/api/sessions/{sid}").json()["profile"]
    assert profile["total_missing"] == 0

    # The generated script must rebuild exactly the same table from the raw file.
    script = client.get(f"/api/sessions/{sid}/script").json()["script"]
    workdir = Path(tempfile.mkdtemp())
    (workdir / FILENAME).write_bytes(RAW.encode("cp1253"))
    (workdir / "pipeline.py").write_text(script, encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(workdir)
    try:
        rebuilt = runpy.run_path(str(workdir / "pipeline.py"))["run"]()
    finally:
        os.chdir(cwd)
        shutil.rmtree(workdir, ignore_errors=True)
    current = server.SESSIONS[sid]["shared"]["df_cache"]["df"]
    pd.testing.assert_frame_equal(rebuilt.reset_index(drop=True), current.reset_index(drop=True))


def test_undo_redo_checkout_and_branching(client, session):
    sid = session["session_id"]
    last = client.get(f"/api/sessions/{sid}").json()["history"]["current_version"]
    data = client.post(f"/api/sessions/{sid}/undo").json()
    assert data["history"]["current_version"] == last - 1 and data["history"]["can_redo"]
    data = client.post(f"/api/sessions/{sid}/redo").json()
    assert data["history"]["current_version"] == last
    assert client.post(f"/api/sessions/{sid}/redo").status_code == 400

    data = client.post(f"/api/sessions/{sid}/checkout/1").json()
    assert data["profile"]["shape"] == [7, 6]
    page = client.get(f"/api/sessions/{sid}/data").json()
    assert page["columns"][0]["name"] == S["Κωδικός Πελάτη"]

    data = op(client, sid, "duplicates.drop")
    history = data["history"]
    assert history["current_version"] == 2 and not history["can_redo"]
    assert len(history["versions"]) == 3
    recipe = client.get(f"/api/sessions/{sid}/recipe").json()
    assert [s["op"] for s in recipe["steps"]] == ["columns.snake_case", "duplicates.drop"]


def test_export_formats(client, session):
    sid = session["session_id"]
    response = client.get(f"/api/sessions/{sid}/export?format=csv")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "Αθήνα" in response.content.decode("utf-8-sig")
    for fmt in ("excel", "json", "parquet"):
        assert client.get(f"/api/sessions/{sid}/export?format={fmt}").status_code == 200, fmt


def test_reload_with_other_encoding(client, session):
    sid = session["session_id"]
    data = client.post(f"/api/sessions/{sid}/reload", json={"encoding": "latin-1"}).json()
    assert data["source"]["encoding"] == "iso8859-1"
    assert data["history"]["current_version"] == 0
    data = client.post(f"/api/sessions/{sid}/reload", json={"encoding": "cp1253"}).json()
    assert "Πόλη" in [c["name"] for c in data["page"]["columns"]]
    bad = client.post(f"/api/sessions/{sid}/reload", json={"encoding": "klingon"})
    assert bad.status_code == 400 and "klingon" in bad.json()["detail"]
    assert client.get(f"/api/sessions/{sid}").json()["source"]["encoding"] == "cp1253"


def test_frontend_cache_headers(client):
    if not server.FRONTEND_DIST.is_dir():
        pytest.skip("frontend not built")
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_other_formats(client):
    frame = pd.DataFrame({"Α": [1, None], "B": ["x", "y"]})
    folder = Path(tempfile.mkdtemp())
    frame.to_excel(folder / "a.xlsx", index=False)
    frame.to_parquet(folder / "a.parquet")
    (folder / "a.json").write_text('[{"a": 1, "b": {"c": 2}}, {"a": 2, "b": {"c": 3}}]', encoding="utf-8")
    for name in ("a.xlsx", "a.parquet", "a.json"):
        response = client.post("/api/sessions", files={"file": (name, (folder / name).read_bytes())})
        assert response.status_code == 200, f"{name}: {response.text}"
    assert client.post("/api/sessions", files={"file": ("x.exe", b"MZ")}).status_code == 400
    assert client.post("/api/sessions", files={"file": ("x.csv", b"")}).status_code == 400
