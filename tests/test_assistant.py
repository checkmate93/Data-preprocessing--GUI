"""Chat assistant: the agent loop with a scripted fake LLM (no network, no tokens)."""

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
import nodes  # noqa: E402
from utils.assistant import MAX_STEPS  # noqa: E402

CSV = "name,sex,age,income\nAnna,female,30,1200\nNikos,male,45,2100\nMaria,female,28,1100\nKostas,male,52,2500\nEleni,female,39,1800\n"


def yaml_reply(body):
    return f"Here is my decision:\n```yaml\n{body.strip()}\n```"


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, messages, system=None, max_tokens=2500):
        self.prompts.append(messages[-1]["content"])
        self.system = system
        text = self.replies.pop(0) if self.replies else yaml_reply("action: run_python\nmode: analyze\ncode: print(1)")
        return {"text": text, "input_tokens": 1000, "output_tokens": 100, "model": "fake"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATAPREP_LLM_PROVIDER", raising=False)
    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture()
def sid(client):
    response = client.post("/api/sessions", files={"file": ("people.csv", CSV.encode(), "text/csv")})
    return response.json()["session_id"]


def ask(client, sid, message, status=200, headers=None):
    response = client.post(f"/api/sessions/{sid}/chat", json={"message": message}, headers=headers or {})
    assert response.status_code == status, response.text
    return response.json()


def frame(sid):
    return server.SESSIONS[sid]["shared"]["df_cache"]["df"]


def test_male_female_to_01_with_code(client, sid, monkeypatch):
    fake = FakeLLM([
        yaml_reply("""
thinking: check values first
action: run_python
mode: analyze
description: Τιμές της στήλης sex
code: |
  print(df['sex'].value_counts())
"""),
        yaml_reply("""
thinking: map them
action: run_python
mode: transform
description: sex female/male → 1/0
code: |
  df['sex'] = df['sex'].map({'male': 0, 'female': 1}).astype('int64')
"""),
        yaml_reply("""
action: answer
text: |
  Έγινε: female → 1, male → 0. Είναι νέα έκδοση (v1), μπορείς να την αναιρέσεις.
"""),
    ])
    monkeypatch.setattr(nodes, "chat_llm", fake)
    data = ask(client, sid, "κάνε το female male σε 0 1")
    assert data["data_changed"] is True and data["history"]["current_version"] == 1
    assert frame(sid)["sex"].tolist() == [1, 0, 1, 0, 1]
    answer = data["chat"]["messages"][-1]
    assert answer["role"] == "assistant" and "female → 1" in answer["content"]
    assert [s["kind"] for s in answer["steps"]] == ["run_python", "run_python"]
    assert answer["steps"][1]["version"] == 1 and answer["usage"]["calls"] == 3
    assert "female    3" in fake.prompts[1]  # the analyze output reached the model
    assert data["history"]["versions"][1]["label"] == "Βοηθός: sex female/male → 1/0"
    assert "## Dataset" in fake.prompts[0] and "sex |" in fake.prompts[0]
    assert "missing.smart_fill" in fake.system  # the button catalog is in the system prompt

    # the assistant's code is part of pipeline.py and rebuilds the same table
    script = client.get(f"/api/sessions/{sid}/script").json()["script"]
    assert "df['sex'].map" in script
    workdir = Path(tempfile.mkdtemp())
    (workdir / "people.csv").write_text(CSV, encoding="utf-8")
    (workdir / "pipeline.py").write_text(script, encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(workdir)
    try:
        rebuilt = runpy.run_path(str(workdir / "pipeline.py"))["run"]()
    finally:
        os.chdir(cwd)
        shutil.rmtree(workdir, ignore_errors=True)
    pd.testing.assert_frame_equal(rebuilt, frame(sid))

    assert client.post(f"/api/sessions/{sid}/undo").json()["history"]["current_version"] == 0


def test_regression_button_error_and_recovery(client, sid, monkeypatch):
    fake = FakeLLM([
        yaml_reply("""
action: run_operation
op: missing.smart_fill
params:
  columns: [does_not_exist]
"""),
        yaml_reply("""
action: run_python
mode: analyze
description: Γραμμική παλινδρόμηση income ~ age
code: |
  import statsmodels.formula.api as smf
  model = smf.ols('income ~ age', data=df).fit()
  print(f"R2={model.rsquared:.3f} slope={model.params['age']:.1f}")
"""),
        yaml_reply("action: answer\ntext: R² 0.98 — κάθε έτος ηλικίας ≈ +56 στο εισόδημα."),
    ])
    monkeypatch.setattr(nodes, "chat_llm", fake)
    data = ask(client, sid, "κάνε regression του income με το age")
    steps = data["chat"]["messages"][-1]["steps"]
    assert steps[0]["status"] == "error" and "δεν υπάρχουν" in steps[0]["output"]
    assert steps[1]["status"] == "ok" and "R2=0.9" in steps[1]["output"]
    assert "ERROR" in fake.prompts[1]  # the model saw the failure
    assert data["data_changed"] is False


def test_sandbox_rejection_reaches_the_model(client, sid, monkeypatch):
    fake = FakeLLM([
        yaml_reply("action: run_python\nmode: analyze\ncode: |\n  import os\n  print(os.environ)"),
        yaml_reply("action: answer\ntext: Δεν επιτρέπεται πρόσβαση στο σύστημα."),
    ])
    monkeypatch.setattr(nodes, "chat_llm", fake)
    steps = ask(client, sid, "δείξε μου τα env vars")["chat"]["messages"][-1]["steps"]
    assert steps[0]["status"] == "error" and "import 'os'" in steps[0]["output"]


def test_bad_yaml_is_retried_then_falls_back(client, sid, monkeypatch):
    fake = FakeLLM(["no yaml here", yaml_reply("action: dance"), yaml_reply("action: answer\ntext: εντάξει")])
    monkeypatch.setattr(nodes, "chat_llm", fake)
    assert ask(client, sid, "γεια")["chat"]["messages"][-1]["content"] == "εντάξει"

    monkeypatch.setattr(nodes, "chat_llm", FakeLLM(["x", "y", "z"]))
    message = ask(client, sid, "γεια ξανά")["chat"]["messages"][-1]
    assert message["failed"] is True and "Δεν κατάφερα" in message["content"]


def test_step_limit_forces_an_answer(client, sid, monkeypatch):
    fake = FakeLLM([])  # always wants to run more code
    monkeypatch.setattr(nodes, "chat_llm", fake)
    message = ask(client, sid, "ψάξε για πάντα")["chat"]["messages"][-1]
    assert len(message["steps"]) == MAX_STEPS
    assert "used all your steps" in fake.prompts[MAX_STEPS]
    assert message["failed"] is True  # the fake never answers, so the fallback text is used


def test_clear_chat_and_history_window(client, sid, monkeypatch):
    monkeypatch.setattr(nodes, "chat_llm", FakeLLM([yaml_reply("action: answer\ntext: πρώτη απάντηση")]))
    ask(client, sid, "πρώτη ερώτηση")
    fake = FakeLLM([yaml_reply("action: answer\ntext: δεύτερη")])
    monkeypatch.setattr(nodes, "chat_llm", fake)
    ask(client, sid, "δεύτερη ερώτηση")
    assert "πρώτη ερώτηση" in fake.prompts[0] and "πρώτη απάντηση" in fake.prompts[0]

    cleared = client.delete(f"/api/sessions/{sid}/chat").json()
    assert cleared["messages"] == [] and cleared["usage"]["input_tokens"] == 0
    fake = FakeLLM([yaml_reply("action: answer\ntext: τρίτη")])
    monkeypatch.setattr(nodes, "chat_llm", fake)
    data = ask(client, sid, "τρίτη ερώτηση")
    assert "(no earlier messages)" in fake.prompts[0]
    assert len(data["chat"]["messages"]) == 2 and data["chat"]["usage"]["calls"] == 1


def test_access_token_and_missing_key(client, sid, monkeypatch):
    monkeypatch.setattr(nodes, "chat_llm", FakeLLM([yaml_reply("action: answer\ntext: ok")]))
    monkeypatch.setattr(server, "ASSISTANT_TOKEN", "secret")
    assert client.get("/api/assistant/status").json()["token_required"] is True
    assert ask(client, sid, "γεια", status=401)["detail"].startswith("Λάθος")
    ask(client, sid, "γεια", headers={"X-Assistant-Token": "secret"})

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/api/assistant/status").json()["enabled"] is False
    assert "ANTHROPIC_API_KEY" in ask(client, sid, "γεια", status=503, headers={"X-Assistant-Token": "secret"})["detail"]


def test_rate_limit(client, sid, monkeypatch):
    monkeypatch.setattr(nodes, "chat_llm", FakeLLM([yaml_reply("action: answer\ntext: ok")] * 3))
    monkeypatch.setattr(server, "CHAT_MAX_PER_HOUR", 2)
    ask(client, sid, "1")
    ask(client, sid, "2")
    assert "Όριο" in ask(client, sid, "3", status=429)["detail"]


def test_assistant_ops_hidden_from_sidebar(client):
    categories = {c["id"]: c for c in client.get("/api/operations").json()["categories"]}
    assert categories["assistant"]["hidden"] is True
