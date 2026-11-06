"""Phase 2: every new button runs, the script still rebuilds the table, join, recipe replay, ML Prep."""

import io
import os
import runpy
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="dataprep_test_"))

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
from utils.op_registry import catalog  # noqa: E402
from utils.ops import helpers  # noqa: E402

CSV = (
    "customer_id,name,city,amount,qty,order_date,status,email,afm,segment\n"
    "1,  Γιάννης Παπαδόπουλος ,Αθήνα,120.5,2,2025-01-05,Ενεργός,giannis@example.gr,094014201,high\n"
    "2,Μαρία Κ.,ΑΘΗΝΑ,80,1,2025-01-20,Ανενεργός,maria@,123456789,low\n"
    "3,Νίκος,Πάτρα,,3,2025-02-11,Ενεργός,nikos@example.gr,094014201,medium\n"
    "4,Ελένη,Θεσσαλονίκη,950,,2025-02-28,Ενεργός,eleni@example.gr,,high\n"
    "5,Κώστας,αθηνα,45.2,5,2025-03-03,Ανενεργός,kostas@example.gr,094014201,low\n"
    "6,Άννα,Πάτρα,60,1,,Ενεργός,anna@example.gr,094014201,medium\n"
    "7,Δημήτρης,Ηράκλειο,15000,2,2025-03-30,Ενεργός,dim@example.gr,094014201,high\n"
    "8,Σοφία,Πάτρα,75.5,4,2025-04-02,Ανενεργός,sofia@example.gr,094014201,low\n"
)
CUSTOMERS = "customer_id;vip\n1;ναι\n2;όχι\n3;ναι\n9;όχι\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as test_client:
        yield test_client


def new_session(client, text=CSV, name="orders.csv"):
    response = client.post("/api/sessions", files={"file": (name, text.encode("utf-8"), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def op(client, sid, name, params=None, status=200):
    response = client.post(f"/api/sessions/{sid}/ops", json={"op": name, "params": params or {}})
    assert response.status_code == status, f"{name}: {response.text}"
    return response.json()


def frame(sid):
    return server.SESSIONS[sid]["shared"]["df_cache"]["df"]


INSPECT_CASES = [
    ("inspect.unique", {}),
    ("inspect.dtypes_check", {}),
    ("inspect.correlation", {"method": "spearman"}),
    ("inspect.outliers", {}),
    ("inspect.memory", {}),
    ("inspect.quality_score", {}),
    ("inspect.column_profile", {"column": "amount"}),
    ("inspect.column_profile", {"column": "city"}),
    ("inspect.groupby", {"by": ["city"], "aggregations": [{"column": "amount", "func": "sum"}]}),
    ("inspect.crosstab", {"rows": "city", "cols": "status", "normalize": "index"}),
    ("duplicates.fuzzy_report", {"column": "city"}),
    ("charts.histogram", {"column": "amount", "bins": 5}),
    ("charts.boxplot", {"columns": ["amount"], "by": "status"}),
    ("charts.bar", {"column": "city", "value": "amount", "agg": "sum"}),
    ("charts.scatter", {"x": "amount", "y": "qty"}),
    ("ml.suggest_config", {}),
]


@pytest.mark.parametrize("name,params", INSPECT_CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(INSPECT_CASES)])
def test_inspect_buttons(client, name, params):
    sid = new_session(client)
    data = op(client, sid, name, params)
    assert data["result"]["sections"], name
    assert data["history"]["current_version"] == 0


def test_chart_section_shapes(client):
    sid = new_session(client)
    sections = op(client, sid, "inspect.correlation")["result"]["sections"]
    assert sections[0]["type"] == "heatmap" and sections[0]["diverging"]
    hist = op(client, sid, "charts.histogram", {"column": "amount", "bins": 4})["result"]["sections"][0]
    assert hist["type"] == "histogram" and len(hist["edges"]) == 5 and sum(hist["counts"]) == 7
    box = op(client, sid, "inspect.outliers", {"columns": ["amount"]})["result"]["sections"][0]
    assert box["items"][0]["outlier_count"] == 1  # the 15000 order
    fuzzy = op(client, sid, "duplicates.fuzzy_report", {"column": "city"})["result"]["sections"][0]
    assert any("ΑΘΗΝΑ" in row[1] for row in fuzzy["data"]["rows"])
    sid2 = new_session(client)
    op(client, sid2, "types.to_datetime", {"columns": ["order_date"], "dayfirst": False})
    line = op(client, sid2, "charts.line", {"x": "order_date", "y": ["amount"], "freq": "M", "agg": "sum"})["result"]["sections"][0]
    assert line["type"] == "line" and line["x"][0] == "2025-01-01" and line["series"][0]["values"][0] == 200.5


TRANSFORMS = [
    ("text.strip", {}),
    ("categorical.standardize_labels", {"columns": ["city"]}),
    ("missing.indicator", {"columns": ["amount"]}),
    ("missing.group_fill", {"columns": ["amount"], "group_by": ["status"], "strategy": "median"}),
    ("missing.ffill_bfill", {"columns": ["qty"], "direction": "both"}),
    ("types.to_datetime", {"columns": ["order_date"], "dayfirst": False}),
    ("missing.interpolate", {"columns": ["qty"], "order_by": "order_date"}),
    ("datetime.floor", {"column": "order_date", "freq": "M", "name": "order_month"}),
    ("datetime.diff", {"start": "order_date", "end": "order_month", "unit": "days", "name": "day_in_month"}),
    ("numeric.outliers_remove", {"columns": ["amount"], "method": "iqr"}),
    ("numeric.transform", {"columns": ["amount"], "method": "log1p", "suffix": "_log"}),
    ("numeric.binning", {"column": "amount", "method": "custom", "edges": "0, 50, 100, 1000", "labels": "μικρή, μεσαία, μεγάλη"}),
    ("numeric.formula", {"left": "amount", "operator": "*", "right": "qty", "name": "total"}),
    ("numeric.round", {"columns": ["total"], "decimals": 0}),
    ("numeric.scale", {"columns": ["amount_log"], "method": "minmax"}),
    ("text.validate_pattern", {"column": "email", "kind": "email"}),
    ("text.validate_pattern", {"column": "afm", "kind": "afm"}),
    ("text.transliterate", {"columns": ["name"]}),
    ("text.remove_accents", {"columns": ["city"]}),
    ("text.replace", {"columns": ["status"], "find": "Ανενεργός", "replace": "Ανενεργ", "whole_value": True}),
    ("text.split", {"column": "name", "separator": " ", "max_parts": 2, "names": "first, last"}),
    ("text.concat", {"columns": ["first", "city"], "separator": " - ", "name": "label"}),
    ("text.length", {"column": "label"}),
    ("text.extract", {"column": "email", "pattern": r"@(.+)$", "name": "domain"}),
    ("text.fix_mojibake", {"columns": ["status"]}),
    ("categorical.ordinal", {"column": "segment", "order": "low, medium, high", "name": "segment_rank"}),
    ("categorical.binary_map", {"column": "status", "positive": "Ενεργός"}),
    ("categorical.frequency", {"columns": ["city"]}),
    ("categorical.rare_group", {"columns": ["city"], "min_pct": 20}),
    ("types.to_category", {"columns": ["segment"]}),
    ("duplicates.flag", {"columns": ["city"]}),
    ("columns.duplicate", {"column": "qty"}),
    ("columns.prefix_suffix", {"columns": ["qty_copy"], "prefix": "x_"}),
    ("columns.reorder", {"columns": ["customer_id", "total"], "position": "first"}),
    ("types.downcast", {}),
    ("columns.drop_by_rule", {"max_missing_pct": 50, "drop_constant": True}),
    ("missing.knn_impute", {"columns": ["qty", "customer_id"], "n_neighbors": 2}),
    ("rows.top_n", {"column": "total", "n": 4, "largest": True}),
]


def test_transform_chain_and_script(client):
    """38 transforms in a row, then the generated pipeline.py must rebuild exactly the same table."""
    sid = new_session(client)
    for name, params in TRANSFORMS:
        data = op(client, sid, name, params)
        assert data["result"]["status"] == "ok", name
    result = frame(sid)
    assert len(result) == 4 and result.columns[0] == "customer_id"
    assert set(result["status"].dropna()) <= {0, 1}
    assert result["afm_valid"].all()  # the 4 top orders all have a valid ΑΦΜ with its leading zero

    script = client.get(f"/api/sessions/{sid}/script").json()["script"]
    workdir = Path(tempfile.mkdtemp())
    (workdir / "orders.csv").write_text(CSV, encoding="utf-8")
    (workdir / "pipeline.py").write_text(script, encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(workdir)
    try:
        rebuilt = runpy.run_path(str(workdir / "pipeline.py"))["run"]()
    finally:
        os.chdir(cwd)
        shutil.rmtree(workdir, ignore_errors=True)
    pd.testing.assert_frame_equal(rebuilt.reset_index(drop=True), result.reset_index(drop=True))


def test_reshape_buttons(client):
    sid = new_session(client)
    data = op(client, sid, "reshape.groupby_agg", {"by": ["status"], "aggregations": [
        {"column": "amount", "func": "sum"}, {"column": "customer_id", "func": "count"}]})
    assert data["profile"]["shape"] == [2, 3]
    client.post(f"/api/sessions/{sid}/undo")
    op(client, sid, "reshape.pivot", {"index": ["city"], "columns": "status", "values": "amount", "aggfunc": "sum", "fill_zero": True})
    assert "Ενεργός" in frame(sid).columns
    client.post(f"/api/sessions/{sid}/undo")
    op(client, sid, "reshape.melt", {"id_vars": ["customer_id"], "value_vars": ["amount", "qty"], "var_name": "metric"})
    assert len(frame(sid)) == 16
    client.post(f"/api/sessions/{sid}/undo")
    op(client, sid, "rows.sample", {"mode": "fraction", "percent": 50, "stratify": "status"})
    assert len(frame(sid)) == 4
    client.post(f"/api/sessions/{sid}/undo")
    small = new_session(client, "metric,q1,q2\nsales,10,20\ncost,5,7\n", "kpi.csv")
    op(client, small, "reshape.transpose", {"header_column": "metric"})
    assert list(frame(small).columns) == ["field", "sales", "cost"]
    op(client, small, "columns.promote_header", {"row": 0})


def test_join_with_attachment_and_script(client):
    sid = new_session(client)
    response = client.post(f"/api/sessions/{sid}/attachments",
                           files={"file": ("vip.csv", CUSTOMERS.encode("cp1253"), "text/csv")})
    assert response.status_code == 200, response.text
    attachment = response.json()["attachments"][0]
    assert attachment["shape"] == [4, 2] and attachment["encoding"] == "cp1253"
    data = op(client, sid, "reshape.merge", {"attachment": "vip.csv", "left_on": ["customer_id"], "right_on": "customer_id", "how": "left"})
    assert data["result"]["sections"][0]["items"][0]["value"] == 3  # ids 1,2,3 matched
    assert frame(sid)["vip"].tolist()[:3] == ["ναι", "όχι", "ναι"]
    op(client, sid, "types.to_bool", {"columns": ["vip"]})

    script = client.get(f"/api/sessions/{sid}/script").json()["script"]
    assert "pd.read_csv('vip.csv', encoding='cp1253'" in script
    workdir = Path(tempfile.mkdtemp())
    (workdir / "orders.csv").write_text(CSV, encoding="utf-8")
    (workdir / "vip.csv").write_bytes(CUSTOMERS.encode("cp1253"))
    (workdir / "pipeline.py").write_text(script, encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(workdir)
    try:
        rebuilt = runpy.run_path(str(workdir / "pipeline.py"))["run"]()
    finally:
        os.chdir(cwd)
        shutil.rmtree(workdir, ignore_errors=True)
    pd.testing.assert_frame_equal(rebuilt, frame(sid))

    bad = op(client, sid, "reshape.merge", {"attachment": "nope.csv", "left_on": ["customer_id"], "right_on": "x"}, status=400)
    assert "δεύτερο αρχείο" in bad["detail"]


def test_recipe_replay_on_new_file(client):
    first = new_session(client)
    for name, params in [("text.strip", {}), ("categorical.standardize_labels", {"columns": ["city"]}),
                         ("missing.smart_fill", {}), ("numeric.formula", {"left": "amount", "operator": "*", "right": "qty", "name": "total"})]:
        op(client, first, name, params)
    recipe = client.get(f"/api/sessions/{first}/recipe").json()

    next_month = CSV.replace("Γιάννης", "Γιώργος").replace("120.5", "130")
    second = new_session(client, next_month, "orders_feb.csv")
    data = client.post(f"/api/sessions/{second}/recipe/apply", json=recipe).json()
    assert data["result"]["message"] == "Εφαρμόστηκαν και τα 4 βήματα"
    assert data["history"]["current_version"] == 4
    assert frame(second)["total"].iloc[0] == 260
    assert frame(second).isna().sum().sum() == 0

    # A step that cannot run on the new file stops the replay and rolls back.
    broken = {"steps": recipe["steps"] + [{"op": "columns.drop", "params": {"columns": ["does_not_exist"]}}]}
    third = new_session(client)
    data = client.post(f"/api/sessions/{third}/recipe/apply", json=broken).json()
    assert data["result"]["replay_failed"] is True and data["history"]["current_version"] == 0
    assert data["history"]["can_redo"] is True

    invalid = client.post(f"/api/sessions/{third}/recipe/apply", json={"steps": [{"op": "inspect.info", "params": {}}, {"op": "x"}]})
    assert invalid.status_code == 400 and "Βήμα 1" in invalid.json()["detail"] and "Βήμα 2" in invalid.json()["detail"]


def test_ml_prep(client):
    sid = new_session(client)
    op(client, sid, "missing.smart_fill")
    data = op(client, sid, "ml.leakage_free_prep", {"target": "status", "test_size": 0.25, "config_json": '{"drop_columns": ["name", "email", "afm", "order_date", "customer_id"]}'})
    result = data["result"]
    files = {f["name"] for f in next(s for s in result["sections"] if s["type"] == "downloads")["files"]}
    assert {"train_clean.csv", "test_clean.csv", "preprocess.py", "config.json"} <= files
    assert data["history"]["current_version"] == 1  # the dataset itself did not change
    train = pd.read_csv(io.BytesIO(client.get(f"/api/sessions/{sid}/files/train_clean.csv").content))
    assert len(train) == 6 and train.isna().sum().sum() == 0
    assert client.get(f"/api/sessions/{sid}/files/..%2Fsource.csv").status_code == 404

    greek = new_session(client, "Πόλη,Ποσό\nΑθήνα,1\nΠάτρα,2\n", "g.csv")
    assert "snake_case" in op(client, greek, "ml.leakage_free_prep", status=400)["detail"]


def test_leading_zeros_are_kept(client):
    sid = new_session(client)
    data = client.get(f"/api/sessions/{sid}").json()
    assert any("afm" in w for w in data["source"]["read_warnings"])
    assert frame(sid)["afm"].iloc[0] == "094014201"
    assert str(frame(sid)["customer_id"].dtype) == "int64"  # normal numbers stay numbers
    op(client, sid, "text.validate_pattern", {"column": "afm", "kind": "afm"})
    assert frame(sid)["afm_valid"].tolist()[:3] == [True, False, True]


def test_helpers_greek_validators_and_mojibake():
    assert helpers.is_valid_afm("094014201") and not helpers.is_valid_afm("123456789")
    assert helpers.is_valid_iban("GR16 0110 1250 0000 0001 2300 695") and not helpers.is_valid_iban("GR00 0000")
    assert helpers.fix_mojibake_text("Αθήνα".encode("utf-8").decode("cp1253")) == "Αθήνα"
    assert helpers.fix_mojibake_text("Café".encode("utf-8").decode("cp1252")) == "Café"
    assert helpers.fix_mojibake_text("Οδός Ερμού") == "Οδός Ερμού"
    assert helpers.transliterate_text("Θεσσαλονίκη ΘΕΣΗ Ουρανός") == "Thessaloniki THESI Ouranos"


def test_every_operation_has_valid_schema_and_code():
    for spec in catalog()["operations"]:
        assert spec["label"] and spec["description"], spec["id"]
        assert spec["kind"] in ("inspect", "transform")
