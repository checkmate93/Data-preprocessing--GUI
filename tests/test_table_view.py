"""Grid view: search, numeric filters, visible columns, cached paging, export of the view."""

import io
import os
import tempfile

import pandas as pd
import pytest

os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="dataprep_test_"))

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
from utils import table_view  # noqa: E402

ROWS = ["Αθήνα", "ΑΘΗΝΑ", "Πάτρα", "Θεσσαλονίκη", "αθηνα"] * 40  # 200 rows
CSV = "id,city,amount\n" + "\n".join(f"{i},{c},{i * 10}" for i, c in enumerate(ROWS)) + "\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def sid(client):
    return client.post("/api/sessions", files={"file": ("cities.csv", CSV.encode(), "text/csv")}).json()["session_id"]


def data(client, sid, **params):
    response = client.get(f"/api/sessions/{sid}/data", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_search_ignores_case_and_accents(client, sid):
    page = data(client, sid, q="αθηνα", size=50)
    assert page["total_rows"] == 120 and page["all_rows"] == 200
    assert {row[1] for row in page["rows"]} == {"Αθήνα", "ΑΘΗΝΑ", "αθηνα"}


def test_numeric_query_in_a_column(client, sid):
    assert data(client, sid, q=">=1900", scope="amount")["total_rows"] == 10
    assert data(client, sid, q="100..140", scope="amount")["total_rows"] == 5
    assert client.get(f"/api/sessions/{sid}/data", params={"q": "x", "scope": "nope"}).status_code == 400


def test_visible_columns_and_sorted_pages(client, sid):
    page = data(client, sid, hide=["id", "amount"], sort="amount", desc=True, size=25, page=2)
    assert [c["name"] for c in page["columns"]] == ["city"]
    assert page["index"][0] == 174  # 200 rows sorted by amount desc, page 2 starts at the 26th
    assert page["total_pages"] == 8


def test_paging_reuses_the_cached_view(client, sid, monkeypatch):
    calls = []
    original = table_view.view_positions
    monkeypatch.setattr(table_view, "view_positions", lambda *a, **k: calls.append(1) or original(*a, **k))
    for number in (1, 2, 3):
        data(client, sid, q="πατρα", page=number, size=10)
    assert len(calls) == 1
    data(client, sid, q="πατρα", sort="amount", size=10)
    assert len(calls) == 2


def test_export_only_the_view(client, sid):
    full = client.get(f"/api/sessions/{sid}/export", params={"format": "csv"})
    assert len(pd.read_csv(io.BytesIO(full.content))) == 200
    view = client.get(f"/api/sessions/{sid}/export", params={"format": "csv", "q": "πατρα", "hide": ["amount"], "sort": "id", "desc": True})
    frame = pd.read_csv(io.BytesIO(view.content), encoding="utf-8-sig")
    assert list(frame.columns) == ["id", "city"] and len(frame) == 40 and frame["id"].iloc[0] == 197
    assert "_view" in view.headers["content-disposition"]
