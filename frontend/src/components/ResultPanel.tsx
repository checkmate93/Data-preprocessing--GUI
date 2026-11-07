import { useState } from "react";
import { api } from "../api";
import { formatBytes, formatInt, formatValue } from "../format";
import type { Diff, OpResult, Section } from "../types";
import { BarChart, BoxChart, HeatmapChart, HistogramChart, LineChart, ScatterChart } from "./Charts";
import { DataTable } from "./DataTable";

interface Props {
  result: OpResult;
  sessionId: string;
  onClose: () => void;
  onApply: () => void;
}

export function ResultPanel({ result, sessionId, onClose, onApply }: Props) {
  const [showCode, setShowCode] = useState(false);
  return (
    <section className={`result ${result.preview ? "is-preview" : ""}`}>
      <header>
        <div>
          <h2>{result.label}</h2>
          {result.message && <p className="result-message">{result.message}</p>}
        </div>
        <div className="result-actions">
          {result.preview && <button className="btn primary" onClick={onApply}>Εφαρμογή</button>}
          <button className="icon-btn" onClick={onClose} aria-label="Κλείσιμο">✕</button>
        </div>
      </header>
      {result.preview && <div className="alert info">Προεπισκόπηση — τα δεδομένα δεν έχουν αλλάξει ακόμα.</div>}
      {result.warnings.map((w, i) => <div key={i} className="alert warn">{w}</div>)}
      {result.diff && <DiffChips diff={result.diff} />}
      {result.sections.map((section, i) => <SectionView key={i} section={section} sessionId={sessionId} />)}
      {result.preview_rows && (
        <div className="section">
          <h3>Αποτέλεσμα (πρώτες {result.preview_rows.rows.length} γραμμές)</h3>
          <DataTable data={result.preview_rows} index={result.preview_rows.index} />
        </div>
      )}
      {result.code && (
        <div className="section">
          <button className="link" onClick={() => setShowCode((v) => !v)}>
            {showCode ? "▾" : "▸"} Κώδικας pandas
          </button>
          {showCode && <pre className="code">{result.code}</pre>}
        </div>
      )}
    </section>
  );
}

function DiffChips({ diff }: { diff: Diff }) {
  const chips: string[] = [];
  const [r0, c0] = diff.shape_before;
  const [r1, c1] = diff.shape_after;
  if (r0 !== r1) chips.push(`Γραμμές: ${formatInt(r0)} → ${formatInt(r1)}`);
  if (c0 !== c1) chips.push(`Στήλες: ${c0} → ${c1}`);
  if (diff.changed_cells) chips.push(`${formatInt(diff.changed_cells)} κελιά άλλαξαν`);
  if (diff.missing_before !== diff.missing_after)
    chips.push(`Κενά: ${formatInt(diff.missing_before)} → ${formatInt(diff.missing_after)}`);
  if (diff.added_columns.length) chips.push(`+ ${diff.added_columns.slice(0, 6).join(", ")}${diff.added_columns.length > 6 ? "…" : ""}`);
  if (diff.removed_columns.length) chips.push(`− ${diff.removed_columns.slice(0, 6).join(", ")}${diff.removed_columns.length > 6 ? "…" : ""}`);
  for (const change of diff.dtype_changes.slice(0, 6)) chips.push(`${change.column}: ${change.from} → ${change.to}`);
  if (!chips.length) chips.push("Καμία αλλαγή στα δεδομένα");
  return <div className="chips">{chips.map((chip) => <span key={chip} className="chip">{chip}</span>)}</div>;
}

export function SectionView({ section, sessionId }: { section: Section; sessionId: string }) {
  const title = section.title ? <h3>{section.title}</h3> : null;
  switch (section.type) {
    case "cards":
      return (
        <div className="section">
          {title}
          <div className="cards">
            {section.items.map((item) => (
              <div className="card" key={item.label}>
                <div className="card-label">{item.label}</div>
                <div className="card-value">{formatValue(item.value)}</div>
              </div>
            ))}
          </div>
        </div>
      );
    case "table":
      return (
        <div className="section">
          {title}
          <DataTable data={section.data} />
        </div>
      );
    case "text":
      return (
        <div className="section">
          {title}
          <pre className="code">{section.content}</pre>
        </div>
      );
    case "bar":
      return <BarChart section={section} />;
    case "histogram":
      return <HistogramChart section={section} />;
    case "box":
      return <BoxChart section={section} />;
    case "scatter":
      return <ScatterChart section={section} />;
    case "line":
      return <LineChart section={section} />;
    case "heatmap":
      return <HeatmapChart section={section} />;
    case "downloads":
      return (
        <div className="section">
          {title}
          <div className="downloads">
            {section.files.map((file) => (
              <a key={file.name} className="btn" href={api.fileUrl(sessionId, file.name)} download={file.name}>
                ⬇ {file.label} <span className="muted small">{file.name} · {formatBytes(file.size)}</span>
              </a>
            ))}
          </div>
        </div>
      );
  }
}
