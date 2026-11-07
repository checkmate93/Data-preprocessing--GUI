import { useState } from "react";
import type { ReloadOptions } from "../api";
import { DELIMITER_LABEL } from "../format";
import type { Source } from "../types";
import { Modal } from "./Modal";

export interface ExportOptions {
  format: string;
  encoding: string;
  delimiter: string;
  onlyView: boolean; // only the rows/columns the grid shows (search, hidden columns, sort)
}

interface ExportProps {
  viewActive: boolean;
  viewSummary: string;
  onClose: () => void;
  onExport: (o: ExportOptions) => void;
}

export function ExportDialog({ viewActive, viewSummary, onClose, onExport }: ExportProps) {
  const [options, setOptions] = useState<ExportOptions>({ format: "csv", encoding: "utf-8-sig", delimiter: ",", onlyView: false });
  const set = (patch: Partial<ExportOptions>) => setOptions((o) => ({ ...o, ...patch }));
  return (
    <Modal
      title="Εξαγωγή δεδομένων"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Άκυρο</button>
          <button className="btn primary" onClick={() => onExport(options)}>Λήψη</button>
        </>
      }
    >
      <div className="form">
        {viewActive && (
          <fieldset>
            <legend>Τι να εξαχθεί</legend>
            <label className="check">
              <input type="radio" checked={!options.onlyView} onChange={() => set({ onlyView: false })} />
              Ολόκληρος ο πίνακας (τρέχουσα έκδοση)
            </label>
            <label className="check">
              <input type="radio" checked={options.onlyView} onChange={() => set({ onlyView: true })} />
              Μόνο ό,τι φαίνεται: {viewSummary} (αναζήτηση, ορατές στήλες, ταξινόμηση)
            </label>
          </fieldset>
        )}
        <label>
          <span>Μορφή</span>
          <select value={options.format} onChange={(e) => set({ format: e.target.value })}>
            <option value="csv">CSV</option>
            <option value="excel">Excel (.xlsx)</option>
            <option value="json">JSON</option>
            <option value="parquet">Parquet</option>
          </select>
        </label>
        {options.format === "csv" && (
          <>
            <label>
              <span>Encoding</span>
              <select value={options.encoding} onChange={(e) => set({ encoding: e.target.value })}>
                <option value="utf-8-sig">UTF-8 με BOM (σωστά ελληνικά στο Excel)</option>
                <option value="utf-8">UTF-8</option>
                <option value="cp1253">Windows-1253 (ελληνικά, παλιά συστήματα)</option>
              </select>
            </label>
            <label>
              <span>Διαχωριστικό</span>
              <select value={options.delimiter} onChange={(e) => set({ delimiter: e.target.value })}>
                {Object.entries(DELIMITER_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </>
        )}
      </div>
    </Modal>
  );
}

export function ReloadDialog({ source, onClose, onReload }: { source: Source; onClose: () => void; onReload: (o: ReloadOptions) => void }) {
  const encodings = Array.from(new Set([source.encoding, ...(source.encoding_alternatives ?? []), "utf-8", "cp1253", "iso8859-7", "cp1252"].filter(Boolean))) as string[];
  const [options, setOptions] = useState<ReloadOptions>({
    encoding: source.encoding,
    delimiter: source.delimiter,
    decimal: source.decimal,
    sheet: source.sheet ?? undefined,
  });
  const set = (patch: Partial<ReloadOptions>) => setOptions((o) => ({ ...o, ...patch }));
  const isText = source.format === "csv";
  return (
    <Modal
      title="Ξαναδιάβασε το αρχείο"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Άκυρο</button>
          <button className="btn primary" onClick={() => onReload(options)}>Ανάγνωση</button>
        </>
      }
    >
      <div className="alert warn">Το ιστορικό αλλαγών θα μηδενιστεί.</div>
      <div className="form">
        {(isText || source.format === "json" || source.format === "jsonl") && (
          <label>
            <span>Encoding</span>
            <select value={options.encoding} onChange={(e) => set({ encoding: e.target.value })}>
              {encodings.map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
        )}
        {isText && (
          <>
            <label>
              <span>Διαχωριστικό</span>
              <select value={options.delimiter} onChange={(e) => set({ delimiter: e.target.value })}>
                {Object.entries(DELIMITER_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>
              <span>Δεκαδικό σύμβολο</span>
              <select value={options.decimal} onChange={(e) => set({ decimal: e.target.value })}>
                <option value=".">Τελεία (1234.56)</option>
                <option value=",">Κόμμα (1234,56)</option>
              </select>
            </label>
          </>
        )}
        {source.sheets && source.sheets.length > 0 && (
          <label>
            <span>Sheet</span>
            <select value={options.sheet} onChange={(e) => set({ sheet: e.target.value })}>
              {source.sheets.map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
        )}
      </div>
    </Modal>
  );
}

export function ScriptDialog({ script, onClose, onDownload }: { script: string; onClose: () => void; onDownload: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Modal
      wide
      title="pipeline.py"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn"
            onClick={async () => {
              await navigator.clipboard.writeText(script);
              setCopied(true);
            }}
          >
            {copied ? "Αντιγράφηκε ✓" : "Αντιγραφή"}
          </button>
          <button className="btn primary" onClick={onDownload}>Λήψη</button>
        </>
      }
    >
      <p className="muted">Ο κώδικας ξανατρέχει όλα τα ενεργά βήματα πάνω στο αρχικό αρχείο. Χρειάζεται pandas και unidecode.</p>
      <pre className="code tall">{script}</pre>
    </Modal>
  );
}
