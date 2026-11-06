import { useRef } from "react";
import { formatInt } from "../format";
import type { History } from "../types";

interface Props {
  history: History;
  onUndo: () => void;
  onRedo: () => void;
  onCheckout: (version: number) => void;
  onScript: () => void;
  onRecipe: () => void;
  onApplyRecipe: (file: File) => void;
}

export function HistoryPanel({ history, onUndo, onRedo, onCheckout, onScript, onRecipe, onApplyRecipe }: Props) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <aside className="history">
      <div className="history-head">
        <h3>Ιστορικό</h3>
        <div>
          <button className="btn small" disabled={!history.can_undo} onClick={onUndo} title="Αναίρεση">↶</button>
          <button className="btn small" disabled={!history.can_redo} onClick={onRedo} title="Επανάληψη">↷</button>
        </div>
      </div>
      <ol className="steps">
        {history.versions.map((v) => {
          const state = v.version === history.current_version ? "current" : v.version > history.current_version ? "future" : "past";
          return (
            <li key={v.version} className={`step ${state}`}>
              <button onClick={() => onCheckout(v.version)} disabled={state === "current"} title="Μετάβαση σε αυτή την έκδοση">
                <span className="step-version">v{v.version}</span>
                <span className="step-body">
                  <b>{v.label}</b>
                  {v.summary && <span>{v.summary}</span>}
                  <span className="muted small">{formatInt(v.shape[0])} × {v.shape[1]}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="history-actions">
        <button className="btn small" onClick={onScript}>pipeline.py</button>
        <button className="btn small" onClick={onRecipe}>recipe.json</button>
        <button className="btn small" onClick={() => input.current?.click()} title="Ξανατρέξε αποθηκευμένα βήματα σε αυτό το αρχείο">
          Εφαρμογή recipe…
        </button>
        <input
          ref={input}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) onApplyRecipe(file);
          }}
        />
      </div>
    </aside>
  );
}
