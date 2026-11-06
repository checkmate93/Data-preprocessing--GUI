import { KIND_LABEL, KIND_TITLE, formatInt, isNumericDtype } from "../format";
import type { Page, Profile } from "../types";
import { Cell } from "./DataTable";

interface Props {
  page: Page;
  profile: Profile;
  sort: string | null;
  desc: boolean;
  onSort: (column: string) => void;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
}

export function DataGrid({ page, profile, sort, desc, onSort, onPage, onSize }: Props) {
  const from = page.total_rows === 0 ? 0 : (page.page - 1) * page.size + 1;
  const to = Math.min(page.page * page.size, page.total_rows);
  return (
    <section className="grid-panel">
      <div className="table-wrap grid">
        <table className="table">
          <thead>
            <tr>
              <th className="idx">#</th>
              {page.columns.map((c) => {
                const meta = profile.columns[c.name];
                return (
                  <th key={c.name} onClick={() => onSort(c.name)} className="sortable" title={`${c.dtype} — κλικ για ταξινόμηση (μόνο προβολή)`}>
                    <div className="th-top">
                      {meta && <span className={`kind kind-${meta.kind}`} title={KIND_TITLE[meta.kind]}>{KIND_LABEL[meta.kind]}</span>}
                      <span className="th-name">{c.name}</span>
                      {sort === c.name && <span>{desc ? "▼" : "▲"}</span>}
                    </div>
                    {meta && (
                      <div className="th-meta">
                        <span>{c.dtype}</span>
                        {meta.null_count > 0 && <span className="missing">{meta.null_pct}% κενά</span>}
                      </div>
                    )}
                    {meta && meta.null_count > 0 && (
                      <div className="nullbar"><div style={{ width: `${Math.max(meta.null_pct, 2)}%` }} /></div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row, i) => (
              <tr key={i}>
                <td className="idx">{String(page.index[i])}</td>
                {row.map((cell, j) => <Cell key={j} value={cell} numeric={isNumericDtype(page.columns[j].dtype)} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <footer className="pager">
        <span className="muted">
          {formatInt(from)}–{formatInt(to)} από {formatInt(page.total_rows)} γραμμές
          {sort && <> · ταξινόμηση προβολής: <b>{sort}</b> <button className="link" onClick={() => onSort("")}>καθαρισμός</button></>}
        </span>
        <div className="pager-controls">
          <select value={page.size} onChange={(e) => onSize(Number(e.target.value))} aria-label="Γραμμές ανά σελίδα">
            {[25, 50, 100, 250, 500].map((n) => <option key={n} value={n}>{n} / σελίδα</option>)}
          </select>
          <button className="btn small" disabled={page.page <= 1} onClick={() => onPage(1)}>«</button>
          <button className="btn small" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>‹</button>
          <span>{page.page} / {page.total_pages}</span>
          <button className="btn small" disabled={page.page >= page.total_pages} onClick={() => onPage(page.page + 1)}>›</button>
          <button className="btn small" disabled={page.page >= page.total_pages} onClick={() => onPage(page.total_pages)}>»</button>
        </div>
      </footer>
    </section>
  );
}
