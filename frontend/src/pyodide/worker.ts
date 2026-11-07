/**
 * Web Worker that runs Python (Pyodide) in the user's browser. The server is not involved after the
 * data download. Messages: init → load(csv) → run(code)… ; the main thread terminates the worker to stop.
 */
import { PYODIDE_VERSION, type WorkerIn, type WorkerOut } from "./protocol";

const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pyodide: any = null;

const post = (message: WorkerOut) => (self as unknown as Worker).postMessage(message);

const HARNESS = `
import os
os.environ["MPLBACKEND"] = "Agg"  # no DOM in a worker: render figures to PNG
import ast, base64, io, json, sys, time, traceback
import numpy as np
import pandas as pd

__ns = {"pd": pd, "np": np}

def __load(csv_text, hints_json):
    hints = json.loads(hints_json)
    df = pd.read_csv(io.StringIO(csv_text), dtype={c: "string" for c in hints["text"]},
                     parse_dates=hints["dates"], low_memory=False)
    for c in hints["category"]:
        if c in df.columns:
            df[c] = df[c].astype("category")
    __ns["df"] = df
    __ns["df_original"] = df.copy()
    return json.dumps({"shape": list(df.shape)})

def __show(value):
    if isinstance(value, pd.Series):
        value = value.to_frame()
    if isinstance(value, pd.DataFrame):
        shown = value.head(200)
        if not isinstance(shown.index, pd.RangeIndex):
            shown = shown.reset_index()
        data = json.loads(shown.to_json(orient="split", date_format="iso", default_handler=str))
        return {"kind": "table", "shape": list(value.shape),
                "columns": [{"name": str(c), "dtype": str(t)} for c, t in shown.dtypes.items()],
                "rows": data["data"]}
    summary = getattr(value, "summary", None)
    if callable(summary):
        return {"kind": "text", "text": str(summary())}
    if isinstance(value, np.generic):
        value = value.item()
    return {"kind": "text", "text": repr(value)}

def __figures():
    if "matplotlib.pyplot" not in sys.modules:
        return []
    plt = sys.modules["matplotlib.pyplot"]
    images = []
    for number in plt.get_fignums():
        buffer = io.BytesIO()
        plt.figure(number).savefig(buffer, format="png", dpi=110, bbox_inches="tight")
        images.append(base64.b64encode(buffer.getvalue()).decode())
    plt.close("all")
    return images

def __run(code):
    stdout = io.StringIO()
    out = {"stdout": "", "display": None, "error": None, "images": []}
    started = time.perf_counter()
    previous = sys.stdout
    sys.stdout = stdout
    try:
        tree = ast.parse(code, "<cell>")
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last = ast.Expression(tree.body.pop().value)
        __ns.pop("result", None)
        exec(compile(tree, "<cell>", "exec"), __ns)
        value = eval(compile(last, "<cell>", "eval"), __ns) if last is not None else None
        if value is None and "result" in __ns:
            value = __ns["result"]
        if value is not None:
            out["display"] = __show(value)
    except BaseException as error:
        # The user's own lines + the message; pandas internals are noise here.
        frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == "<cell>"]
        where = f"Γραμμή {frames[-1].lineno}: " if frames else ""
        lines = code.splitlines()
        source = f"\\n    {lines[frames[-1].lineno - 1].strip()}" if frames and 0 < frames[-1].lineno <= len(lines) else ""
        out["error"] = where + "".join(traceback.format_exception_only(error)).strip() + source
    finally:
        sys.stdout = previous
    out["stdout"] = stdout.getvalue()[-20000:]
    out["images"] = __figures()
    if out["images"] and out["display"] and type(value).__module__.startswith("matplotlib"):
        out["display"] = None  # e.g. Text(0.5, 1.0, '...') from plt.title(): the figure is the output
    df = __ns.get("df")
    out["df_shape"] = list(df.shape) if isinstance(df, pd.DataFrame) else None
    out["seconds"] = round(time.perf_counter() - started, 3)
    return json.dumps(out, default=str)

def __export(name):
    value = __ns.get(name)
    if not isinstance(value, pd.DataFrame):
        raise ValueError(f"Η μεταβλητή '{name}' δεν είναι DataFrame.")
    value = value.copy()
    value.columns = [str(c) for c in value.columns]
    original = __ns.get("df_original")
    return json.dumps({
        "csv": value.to_csv(index=False),
        "dtypes": {c: str(t) for c, t in value.dtypes.items()},
        "changed": not (isinstance(original, pd.DataFrame) and value.equals(original)),
        "shape": list(value.shape),
    })

def __csv(name):
    value = __ns.get(name)
    if isinstance(value, pd.Series):
        value = value.to_frame()
    if not isinstance(value, pd.DataFrame):
        raise ValueError(f"Η μεταβλητή '{name}' δεν είναι DataFrame.")
    return value.to_csv(index=False)
`;

async function init() {
  post({ type: "status", text: "Φόρτωση Python (Pyodide)…" });
  const { loadPyodide } = await import(/* @vite-ignore */ `${INDEX_URL}pyodide.mjs`);
  pyodide = await loadPyodide({ indexURL: INDEX_URL });
  post({ type: "status", text: "Φόρτωση pandas…" });
  await pyodide.loadPackage(["pandas"]);
  pyodide.runPython(HARNESS);
  post({ type: "ready", version: pyodide.version });
}

self.onmessage = async (event: MessageEvent<WorkerIn>) => {
  const message = event.data;
  try {
    if (message.type === "init") {
      await init();
    } else if (message.type === "load") {
      const info = JSON.parse(pyodide.globals.get("__load")(message.csv, JSON.stringify(message.hints)));
      post({ type: "loaded", id: message.id, shape: info.shape });
    } else if (message.type === "run") {
      post({ type: "status", text: "Φόρτωση βιβλιοθηκών…" });
      await pyodide.loadPackagesFromImports(message.code);
      post({ type: "status", text: "Εκτέλεση…" });
      const result = JSON.parse(pyodide.globals.get("__run")(message.code));
      post({ type: "result", id: message.id, ...result });
    } else if (message.type === "csv") {
      post({ type: "csv", id: message.id, csv: pyodide.globals.get("__csv")(message.name) });
    } else if (message.type === "export") {
      post({ type: "export", id: message.id, ...JSON.parse(pyodide.globals.get("__export")(message.name)) });
    }
  } catch (error) {
    post({ type: "error", id: "id" in message ? message.id : undefined, error: String((error as Error)?.message ?? error) });
  }
};
