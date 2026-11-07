"""Sessions survive a server restart, only recent sessions keep their table in RAM, old ones are deleted."""

import os
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="dataprep_test_"))

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
from utils import session_store  # noqa: E402

CSV = "Name,City\nAnna, Athens\nNikos,Patra\nAnna, Athens\n"


@pytest.fixture()
def client():
    with TestClient(server.app) as test_client:
        yield test_client


def upload(client, name="people.csv"):
    return client.post("/api/sessions", files={"file": (name, CSV.encode(), "text/csv")}).json()["session_id"]


def test_session_survives_restart(client):
    sid = upload(client)
    client.post(f"/api/sessions/{sid}/ops", json={"op": "columns.snake_case", "params": {}})
    client.post(f"/api/sessions/{sid}/ops", json={"op": "duplicates.drop", "params": {}})
    server.SESSIONS[sid]["shared"]["chat"]["messages"].append({"role": "user", "content": "γεια", "at": "x"})
    session_store.save_state(server.SESSIONS[sid]["shared"])

    server.SESSIONS.clear()  # what a restart does to the in-memory dict

    state = client.get(f"/api/sessions/{sid}").json()
    assert state["history"]["current_version"] == 2 and len(state["history"]["versions"]) == 3
    assert client.get(f"/api/sessions/{sid}/chat").json()["messages"][0]["content"] == "γεια"
    page = client.get(f"/api/sessions/{sid}/data").json()
    assert [c["name"] for c in page["columns"]] == ["name", "city"] and page["total_rows"] == 2
    # undo still works on the restored session (older versions are read from disk)
    assert client.post(f"/api/sessions/{sid}/undo").json()["profile"]["shape"] == [3, 2]


def test_unknown_or_bad_ids_are_404(client):
    assert client.get("/api/sessions/00000000-0000-4000-8000-000000000000").status_code == 404
    assert client.get("/api/sessions/..%2F..%2Fetc").status_code == 404


def test_only_recent_sessions_keep_dataframes_in_memory(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_HOT_SESSIONS", 2)
    ids = [upload(client, f"f{i}.csv") for i in range(4)]
    in_memory = [sid for sid in ids if server.SESSIONS[sid]["shared"]["df_cache"]["df"] is not None]
    assert in_memory == ids[-2:]
    # an evicted session still works: its table is read back from disk on use
    page = client.get(f"/api/sessions/{ids[0]}/data").json()
    assert page["total_rows"] == 3
    assert server.SESSIONS[ids[0]]["shared"]["df_cache"]["df"] is not None
    hot = [sid for sid in ids if server.SESSIONS[sid]["shared"]["df_cache"]["df"] is not None]
    assert len(hot) == 2


def test_least_used_sessions_leave_memory_entirely_and_come_back(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_HOT_SESSIONS", 1)
    monkeypatch.setattr(server, "MAX_LOADED_SESSIONS", 2)
    server.SESSIONS.clear()
    ids = [upload(client, f"g{i}.csv") for i in range(3)]
    assert ids[0] not in server.SESSIONS and set(ids[1:]) <= set(server.SESSIONS)
    assert client.get(f"/api/sessions/{ids[0]}/data").json()["total_rows"] == 3  # reloaded from disk
    assert len(server.SESSIONS) == 2


def test_expired_sessions_are_deleted_on_cleanup(client):
    old, fresh = upload(client, "old.csv"), upload(client, "fresh.csv")
    state = Path(server.SESSIONS[old]["shared"]["session"]["storage_dir"]) / session_store.STATE_FILE
    two_days_ago = time.time() - 48 * 3600
    os.utime(state, (two_days_ago, two_days_ago))
    deleted = session_store.cleanup_expired(server.STORAGE_ROOT, 24 * 3600)
    assert old in deleted and fresh not in deleted
    server.SESSIONS.pop(old, None)
    assert client.get(f"/api/sessions/{old}").status_code == 404
    assert client.get(f"/api/sessions/{fresh}").status_code == 200


def test_delete_removes_files(client):
    sid = upload(client)
    folder = Path(server.SESSIONS[sid]["shared"]["session"]["storage_dir"])
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert not folder.exists()
    assert client.get(f"/api/sessions/{sid}").status_code == 404
