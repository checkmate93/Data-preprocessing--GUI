import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "../api";
import { PYODIDE_VERSION, type LoadHints, type RunResult } from "../pyodide/protocol";
import { PythonRuntime } from "../pyodide/runtime";
import type { Profile } from "../types";
import { DataTable } from "./DataTable";

interface Props {
  sessionId: string;
  version: number;
  profile: Profile;
  filename: string;
  open: boolean;
  onClose: () => void;
}

interface Cell {
  code: string;
  result?: RunResult;
  error?: string;
}

const EXAMPLES: { label: string; code: string }[] = [
  { label: "Στατιστικά", code: "df.describe(include='all').T" },
  { label: "Συσχετίσεις", code: "df.select_dtypes('number').corr().round(3)" },
  { label: "Group-by", code: "col = df.select_dtypes(exclude='number').columns[0]\ndf.groupby(col).agg(['count', 'mean'], numeric_only=True)" },
  { label: "Regression", code: "import statsmodels.formula.api as smf\nnum = df.select_dtypes('number').columns\nmodel = smf.ols(f'{num[0]} ~ {num[1]}', data=df).fit()\nmodel.summary()" },
  { label: "Histogram", code: "import matplotlib.pyplot as plt\ndf.select_dtypes('number').hist(figsize=(9, 5), bins=20)\nplt.tight_layout()" },
  { label: "Αλλαγή τιμών", code: "# π.χ. female/male → 1/0\n# df['sex'] = df['sex'].map({'female': 1, 'male': 0})\ndf.head()" },
];

const CODE_KEY = "dataprep.pythonCode";

function readCode() {
  try {
    return localStorage.getItem(CODE_KEY) ?? "df.head()";
  } catch {
    return "df.head()";
  }
}

function hintsFrom(profile: Profile): LoadHints {
  const columns = Object.entries(profile.columns);
  return {
    text: columns.filter(([, m]) => (m.kind === "text" || m.kind === "categorical") && m.dtype !== "category").map(([n]) => n),
    dates: columns.filter(([, m]) => m.kind === "datetime").map(([n]) => n),
    category: columns.filter(([, m]) => m.dtype === "category").map(([n]) => n),
  };
}

export function PythonPanel({ sessionId, version, profile, filename, open, onClose }: Props) {
  const [status, setStatus] = useState("");
  const runtime = useRef<PythonRuntime | null>(null);
  if (!runtime.current) runtime.current = new PythonRuntime(setStatus);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [localShape, setLocalShape] = useState<[number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState(readCode);
  const [cells, setCells] = useState<Cell[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const output = useRef<HTMLDivElement>(null);
  const key = `${sessionId}:${version}`;

  useEffect(() => () => runtime.current?.stop(), []);

  useEffect(() => {
    try {
      localStorage.setItem(CODE_KEY, code);
    } catch {
      /* storage blocked: the code just isn't remembered */
    }
  }, [code]);

  useEffect(() => {
    output.current?.scrollTo({ top: output.current.scrollHeight, behavior: "smooth" });
  }, [cells.length]);

  /** Returns true when the current server version is loaded into the worker as `df`. */
  async function loadData(): Promise<boolean> {
    setBusy(true);
    setProblem(null);
    try {
      setStatus("Λήψη δεδομένων από τον server (μία φορά)…");
      const response = await fetch(api.exportUrl(sessionId, "csv", "utf-8", ","));
      if (!response.ok) throw new Error(`Τα δεδομένα δεν κατέβηκαν (${response.status}).`);
      const csv = await response.text();
      const shape = await runtime.current!.load(csv, hintsFrom(profile));
      setLocalShape(shape);
      setLoadedKey(key);
      return true;
    } catch (error) {
      setProblem((error as Error).message);
      return false;
    } finally {
      setStatus("");
      setBusy(false);
    }
  }

  // Load on first open, and when the server version changes while open.
  useEffect(() => {
    if (open && loadedKey !== key && !busy) loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key]);

  async function run() {
    if (busy || !code.trim()) return;
    if (loadedKey === null && !(await loadData())) return; // e.g. after «Διακοπή»: reload, then run
    setBusy(true);
    const cell: Cell = { code };
    setCells((c) => [...c.slice(-19), cell]);
    try {
      cell.result = await runtime.current!.run(code);
      if (cell.result.df_shape) setLocalShape(cell.result.df_shape);
    } catch (error) {
      cell.error = (error as Error).message;
    } finally {
      setCells((c) => [...c]);
      setStatus("");
      setBusy(false);
    }
  }

  function stop() {
    runtime.current!.stop();
    setBusy(false);
    setStatus("");
    setLoadedKey(null);
    setLocalShape(null);
    setProblem("Η Python σταμάτησε· οι μεταβλητές χάθηκαν. Πάτα «Εκτέλεση» για να ξαναφορτωθούν τα δεδομένα.");
  }

  async function downloadDf() {
    try {
      const csv = await runtime.current!.csv("df");
      const stem = filename.replace(/\.[^.]+$/, "");
      saveBlob(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }), `${stem}_local.csv`);
    } catch (error) {
      setProblem((error as Error).message);
    }
  }

  const stale = loadedKey !== null && loadedKey !== key;
  return (
    <aside className={`py-panel ${open ? "" : "hidden"}`} aria-label="Python στον browser" aria-hidden={!open}>
      <header className="chat-head">
        <div>
          <h2>Python στον browser</h2>
          <span className="muted small">
            Pyodide {PYODIDE_VERSION} · τρέχει στον υπολογιστή σου, όχι στον server
            {localShape && ` · df ${localShape[0]} × ${localShape[1]}`}
          </span>
        </div>
        <div className="chat-head-actions">
          <button className="btn small" disabled={busy} onClick={loadData} title={`Ξαναφόρτωσε την έκδοση v${version} από τον server· το τοπικό df αντικαθίσταται`}>
            Επαναφόρτωση v{version}
          </button>
          <button className="btn small" disabled={busy || !loadedKey} onClick={downloadDf}>Λήψη df (CSV)</button>
          <button className="icon-btn" onClick={onClose} aria-label="Κλείσιμο">✕</button>
        </div>
      </header>

      {stale && <div className="alert warn py-note">Τα δεδομένα στον server άλλαξαν σε v{version}. Το τοπικό df είναι από παλαιότερη έκδοση.</div>}
      <div className="py-note muted small">
        Οι αλλαγές στο <code>df</code> μένουν στον browser· για να τις κρατήσεις κατέβασε το CSV. Διαθέσιμα: pandas, numpy,
        statsmodels, scikit-learn, scipy, matplotlib (φορτώνονται όταν τα κάνεις import). <code>df_original</code> = όπως ήρθε από τον server.
      </div>

      <div className="py-output" ref={output}>
        {cells.length === 0 && !busy && <p className="muted small">Η τελευταία έκφραση εμφανίζεται αυτόματα, όπως στο Jupyter. Ή όρισε <code>result = …</code></p>}
        {cells.map((cell, i) => <CellView key={i} cell={cell} />)}
        {(busy || status) && <div className="py-status"><span className="spinner small" /> {status || "Εκτέλεση…"}</div>}
        {problem && <div className="alert error">{problem}</div>}
      </div>

      <div className="py-editor">
        <div className="py-examples">
          {EXAMPLES.map((example) => (
            <button key={example.label} className="chip" onClick={() => setCode(example.code)}>{example.label}</button>
          ))}
        </div>
        <textarea
          className="mono"
          spellCheck={false}
          rows={8}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              run();
            } else if (e.key === "Tab") {
              e.preventDefault();
              const target = e.currentTarget;
              const { selectionStart: start, selectionEnd: end } = target;
              setCode(code.slice(0, start) + "    " + code.slice(end));
              requestAnimationFrame(() => target.setSelectionRange(start + 4, start + 4));
            }
          }}
        />
        <div className="py-actions">
          <span className="muted small">Ctrl+Enter για εκτέλεση</span>
          <button className="btn" onClick={() => setCells([])} disabled={!cells.length}>Καθαρισμός εξόδου</button>
          {busy ? (
            <button className="btn danger" onClick={stop}>Διακοπή</button>
          ) : (
            <button className="btn primary" onClick={run} disabled={!code.trim()}>Εκτέλεση</button>
          )}
        </div>
      </div>
    </aside>
  );
}

function CellView({ cell }: { cell: Cell }) {
  const result = cell.result;
  return (
    <div className="py-cell">
      <pre className="code py-code">{cell.code}</pre>
      {result?.stdout && <pre className="code output">{result.stdout}</pre>}
      {result?.display?.kind === "text" && <pre className="code output">{result.display.text}</pre>}
      {result?.display?.kind === "table" && result.display.columns && result.display.rows && (
        <>
          <DataTable data={{ columns: result.display.columns, rows: result.display.rows }} maxRows={200} />
          {result.display.shape && result.display.shape[0] > 200 && (
            <p className="muted small">Εμφανίζονται 200 από {result.display.shape[0]} γραμμές.</p>
          )}
        </>
      )}
      {result?.images.map((image, i) => <img key={i} className="py-figure" alt="Γράφημα matplotlib" src={`data:image/png;base64,${image}`} />)}
      {(result?.error || cell.error) && <pre className="code py-error">{result?.error || cell.error}</pre>}
      {result && <div className="msg-usage">{result.seconds}s</div>}
    </div>
  );
}
