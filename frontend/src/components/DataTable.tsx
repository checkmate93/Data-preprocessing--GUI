import { formatValue, isNumericDtype } from "../format";
import type { FrameData } from "../types";

/** Plain table used inside result sections and previews. */
export function DataTable({ data, index, maxRows = 300 }: { data: FrameData; index?: unknown[]; maxRows?: number }) {
  const rows = data.rows.slice(0, maxRows);
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {index && <th className="idx">#</th>}
            {data.columns.map((c) => <th key={c.name} title={c.dtype}>{c.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {index && <td className="idx">{formatValue(index[i])}</td>}
              {row.map((cell, j) => (
                <Cell key={j} value={cell} numeric={isNumericDtype(data.columns[j].dtype)} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.rows.length > maxRows && <p className="muted small">Εμφανίζονται {maxRows} από {data.rows.length} γραμμές.</p>}
    </div>
  );
}

export function Cell({ value, numeric }: { value: unknown; numeric: boolean }) {
  if (value === null || value === undefined) return <td className="null">∅</td>;
  const text = formatValue(value);
  return (
    <td className={numeric || typeof value === "number" ? "num" : undefined} title={text.length > 40 ? text : undefined}>
      {text}
    </td>
  );
}
