"""Saving a df computed in the browser (Pyodide) as a new server version."""

import json
import os
import tempfile

import pytest

os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="dataprep_test_"))

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402

CSV = "afm,sex,age,joined\n094014201,female,30,2024-01-05\n123456789,male,45,2024-02-11\n"
CODE = "df['sex'] = df['sex'].map({'female': 1, 'male': 0})\ndf['age_plus'] = df['age'] + 1"
# what the browser sends back after running CODE
BROWSER_CSV = "afm,sex,age,joined,age_plus\n094014201,1,30,2024-01-05,31\n123456789,0,45,2024-02-11,46\n"
DTYPES = {"afm": "string", "sex": "int64", "age": "int64", "joined": "datetime64[ns]", "age_plus": "int64"}


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as test_client:
        yield test_client


def new_session(client):
    return client.post("/api/sessions", files={"file": ("people.csv", CSV.encode(), "text/csv")}).json()["session_id"]


def save(client, sid, base_version, csv=BROWSER_CSV, code=CODE):
    return client.post(
        f"/api/sessions/{sid}/browser-version",
        files={"file": ("df.csv", csv.encode(), "text/csv")},
        data={"base_version": str(base_version), "code": code, "description": "female/male → 1/0", "dtypes": json.dumps(DTYPES)},
    )


def test_browser_df_becomes_a_version_with_types(client):
    sid = new_session(client)
    data = save(client, sid, 0).json()
    assert data["history"]["current_version"] == 1
    assert data["history"]["versions"][1]["label"] == "Python: female/male → 1/0"
    df = server.SESSIONS[sid]["shared"]["df_cache"]["df"]
    assert df["afm"].iloc[0] == "094014201"  # leading zero kept
    assert str(df["joined"].dtype).startswith("datetime64")
    assert df["age_plus"].tolist() == [31, 46]
    staged = os.path.join(server.SESSIONS[sid]["shared"]["session"]["storage_dir"], "staged")
    assert not os.listdir(staged)  # staged upload cleaned up
    script = client.get(f"/api/sessions/{sid}/script").json()["script"]
    assert "έτρεξε στον browser" in script and "df['age'] + 1" in script
    assert client.post(f"/api/sessions/{sid}/undo").json()["history"]["current_version"] == 0


def test_stale_base_version_is_rejected(client):
    sid = new_session(client)
    client.post(f"/api/sessions/{sid}/ops", json={"op": "columns.snake_case", "params": {}})
    response = save(client, sid, 0)
    assert response.status_code == 409 and "v1" in response.json()["detail"]
    assert server.SESSIONS[sid]["shared"]["current_version"] == 1


def test_recipe_replay_reruns_browser_code_in_sandbox(client):
    first = new_session(client)
    save(client, first, 0)
    recipe = client.get(f"/api/sessions/{first}/recipe").json()
    assert recipe["steps"][0]["op"] == "browser.python_version"

    second = new_session(client)
    data = client.post(f"/api/sessions/{second}/recipe/apply", json=recipe).json()
    assert data["result"]["message"] == "Εφαρμόστηκαν και τα 1 βήματα"
    df = server.SESSIONS[second]["shared"]["df_cache"]["df"]
    assert df["sex"].tolist() == [1, 0] and df["age_plus"].tolist() == [31, 46]
