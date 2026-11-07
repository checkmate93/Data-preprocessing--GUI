"""Prompt building and decision checking for the chat assistant (an agent over the operation flow).

What the model sees (and therefore what leaves the server):
- column names, types, missing %, unique counts, min/max/mean, and up to 5 frequent values of
  low-cardinality text columns;
- the last few chat turns (question + final answer), not earlier tool output;
- the output of the code/buttons it ran in the current turn, truncated.
Raw rows are never sent unless the model's own code prints them.
"""

import os

import pandas as pd
import yaml

from utils.op_registry import HIDDEN_CATEGORIES, catalog
from utils.ops.helpers import column_kind

HISTORY_TURNS = int(os.environ.get("DATAPREP_CHAT_HISTORY_TURNS", "6"))
MAX_STEPS = int(os.environ.get("DATAPREP_CHAT_MAX_STEPS", "6"))
MAX_TOOL_OUTPUT = 3500
MAX_COLUMNS = 80

ACTIONS = {"run_python", "run_operation", "answer"}

SYSTEM_PROMPT = """You are the data assistant of DataPrep Studio, a web app where a user cleans and analyses one table (a pandas DataFrame called `df`).
Answer in the user's language (usually Greek). Be concise and concrete: numbers rounded, what changed, how to undo.

You work in steps. In each step you choose ONE action:

1. run_python — run pandas code in a sandbox.
   - `df` is the current table; `pd` and `np` are already imported. You may import: pandas, numpy, sklearn, scipy, statsmodels, math, statistics, re, datetime, json, collections, itertools.
   - mode: analyze → read-only. print() what you need or assign `result` (DataFrames are shown truncated). Use for statistics, regression, tests, questions.
   - mode: transform → change the table: assign the new table to `df`. Creates a new version (the user can undo). Use random_state for anything random.
   - Not allowed: files, network, os/sys, open, eval/exec, df.query/df.eval, private attributes (._x), pd.read_*, df.to_csv/to_excel/to_pickle.
   - For regression prefer statsmodels (print(model.summary()) or key numbers) or sklearn with a train/test split.
2. run_operation — run one of the app's buttons (listed below) with params. Prefer a button when one does exactly the job (cleaner pipeline code); otherwise use run_python.
3. answer — reply to the user and stop. Explain what you did; if you changed the table, say it is a new version and can be undone (↶).

Rules:
- Look before you change: if unsure about values or types, run a quick analyze step first.
- Only transform when the user asks for a change. Questions → analyze + answer.
- If a step fails, read the error, fix it and retry once; then explain the problem instead of looping.
- Never invent results: every number in your answer must come from a step output in this turn or from the dataset summary.

Reply with exactly one YAML block:
```yaml
thinking: one or two short sentences
action: run_python | run_operation | answer
# run_python:
mode: analyze | transform
description: short description in the user's language (shown in the history)
code: |
  ...
# run_operation:
op: <button id>
params: {}
# answer:
text: |
  ...
```

Buttons (id(params) — description; * = required):
{catalog}
"""


def _param_signature(name, prop, required):
    prop = next((p for p in prop.get("anyOf", []) if p.get("type") != "null"), prop) | {k: v for k, v in prop.items() if k != "anyOf"}
    ui = prop.get("ui")
    if ui == "columns":
        kind = "[cols]"
    elif ui == "column":
        kind = "col"
    elif ui == "conditions":
        kind = "[{column,op,value}]"
    elif ui == "aggregations":
        kind = "[{column,func}]"
    elif ui == "rename_map":
        kind = "{old: new}"
    elif "enum" in prop:
        kind = "|".join(map(str, prop["enum"]))
    elif prop.get("type") == "array" and "enum" in prop.get("items", {}):
        kind = "[" + "|".join(prop["items"]["enum"]) + "]"
    else:
        kind = prop.get("type", "str")
    star = "*" if required or prop.get("required_choice") else ""
    return f"{name}{star}:{kind}"


def compact_catalog():
    lines = []
    for op in catalog()["operations"]:
        if op["category"] in HIDDEN_CATEGORIES:
            continue
        schema = op["schema"]
        required = set(schema.get("required", []))
        params = ", ".join(_param_signature(n, p, n in required) for n, p in (schema.get("properties") or {}).items())
        description = op["description"] if len(op["description"]) <= 70 else op["description"][:69] + "…"
        lines.append(f"- {op['id']}({params}) — {description}")
    return "\n".join(lines)


def system_prompt():
    return SYSTEM_PROMPT.replace("{catalog}", compact_catalog())


def dataset_context(df, profile, version):
    rows, cols = df.shape
    lines = [f"Table v{version}: {rows} rows × {cols} columns. Columns (name | dtype | missing% | unique | details):"]
    for name in list(df.columns)[:MAX_COLUMNS]:
        meta = profile["columns"].get(str(name), {})
        series = df[name]
        detail = ""
        kind = column_kind(series)
        if kind == "numeric" and series.notna().any():
            detail = f"min {_short(series.min())}, max {_short(series.max())}, mean {_short(series.mean())}"
        elif kind == "datetime" and series.notna().any():
            detail = f"{series.min():%Y-%m-%d} → {series.max():%Y-%m-%d}"
        elif meta.get("unique", 0) <= 50:
            top = series.value_counts().head(5)
            detail = "values: " + ", ".join(f"{_short(v)} ({c})" for v, c in top.items())
        lines.append(f"- {name} | {series.dtype} | {meta.get('null_pct', 0)}% | {meta.get('unique', '?')} | {detail}")
    if cols > MAX_COLUMNS:
        lines.append(f"- … and {cols - MAX_COLUMNS} more: {', '.join(map(str, list(df.columns)[MAX_COLUMNS:]))}")
    return "\n".join(lines)


def _short(value, limit=30):
    if isinstance(value, float):
        return f"{value:.4g}"
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def history_text(messages):
    """The last HISTORY_TURNS turns: question, a one-line list of actions, final answer."""
    turns = []
    for message in messages[-HISTORY_TURNS * 2:]:
        if message["role"] == "user":
            turns.append(f"User: {message['content']}")
        else:
            actions = "; ".join(f"{s['kind']}: {s.get('description') or s.get('op')} [{s['status']}]" for s in message.get("steps", []))
            turns.append((f"(actions: {actions})\n" if actions else "") + f"Assistant: {message['content']}")
    return "\n\n".join(turns) if turns else "(no earlier messages)"


def steps_text(steps):
    if not steps:
        return "(none yet)"
    blocks = []
    for number, step in enumerate(steps, start=1):
        head = f"Step {number} — {step['kind']}"
        if step["kind"] == "run_python":
            head += f" ({step['mode']}): {step.get('description', '')}\n```python\n{step['code']}\n```"
        else:
            head += f": {step['op']} {step.get('params')}"
        blocks.append(f"{head}\nStatus: {step['status']}\nOutput:\n{step['output'] or '(empty)'}")
    return "\n\n".join(blocks)


def decision_prompt(context, history, question, steps, force_answer):
    tail = ("You have used all your steps: choose action `answer` now and summarise what you found or did."
            if force_answer else "Choose the next action.")
    return (
        f"## Dataset\n{context}\n\n## Earlier conversation\n{history}\n\n"
        f"## Current question\n{question}\n\n## Steps taken for this question\n{steps_text(steps)}\n\n{tail}"
    )


def validate_decision(decision, force_answer):
    """Raise ValueError (so the node retries) when the YAML does not describe one valid action."""
    action = decision.get("action")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if force_answer and action != "answer":
        raise ValueError("an answer is required now")
    if action == "run_python":
        if decision.get("mode") not in ("analyze", "transform"):
            raise ValueError("run_python needs mode analyze or transform")
        if not str(decision.get("code") or "").strip():
            raise ValueError("run_python needs code")
    elif action == "run_operation":
        if not decision.get("op"):
            raise ValueError("run_operation needs op")
        if not isinstance(decision.get("params") or {}, dict):
            raise ValueError("params must be a mapping")
    elif not str(decision.get("text") or "").strip():
        raise ValueError("answer needs text")
    return decision


def result_text(result):
    """What the model reads back from a button / code run (truncated)."""
    if result.get("status") != "ok":
        return f"ERROR: {result.get('message')}"
    parts = [result.get("message") or ""]
    parts += [f"warning: {w}" for w in result.get("warnings", [])]
    for section in result.get("sections", []):
        kind = section.get("type")
        title = f"[{section.get('title')}] " if section.get("title") else ""
        if kind == "text":
            parts.append(title + section["content"])
        elif kind == "cards":
            parts.append(title + "; ".join(f"{i['label']}: {i['value']}" for i in section["items"]))
        elif kind == "table":
            data = section["data"]
            frame = pd.DataFrame(data["rows"][:15], columns=[c["name"] for c in data["columns"]])
            more = f"\n… {len(data['rows'])} rows" if len(data["rows"]) > 15 else ""
            parts.append(title + frame.to_string(index=False, max_colwidth=30) + more)
        elif kind == "bar":
            parts.append(title + ", ".join(f"{l}: {v}" for l, v in list(zip(section["labels"], section["values"]))[:20]))
        else:
            parts.append(f"{title}(chart '{kind}' shown to the user)")
    if result.get("diff"):
        d = result["diff"]
        parts.append(f"table changed: shape {d['shape_before']} → {d['shape_after']}, added {d['added_columns']}, "
                     f"removed {d['removed_columns']}, changed cells {d['changed_cells']}")
    text = "\n".join(p for p in parts if p)
    return text if len(text) <= MAX_TOOL_OUTPUT else text[:MAX_TOOL_OUTPUT] + "\n… (truncated)"


if __name__ == "__main__":
    prompt = system_prompt()
    print(f"system prompt: {len(prompt)} chars ≈ {len(prompt) // 4} tokens")
    print(compact_catalog().splitlines()[0])
    assert validate_decision(yaml.safe_load("action: answer\ntext: ok"), False)
