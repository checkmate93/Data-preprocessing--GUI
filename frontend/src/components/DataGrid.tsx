import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { KIND_LABEL, KIND_TITLE, formatInt, formatValue, isNumericDtype } from "../format";
import type { ColumnMeta, Page, Profile } from "../types";
import { Cell } from "./DataTable";

export interface Search {
  q: string;
  scope: string | null; // null = all columns
}

interface Props {
  page: Page;
  profile: Profile;
  sort: string | null;
  desc: boolean;
  search: Search;
  hidden: string[];
  onSort: (column: string) => void;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
  onSearch: (search: Search) => void;
  onHidden: (hidden: string[]) => void;
  /** Turn the current search into a «Φίλτρο γραμμών» step (new version). */
  onKeepMatches: () => void;
}

const NUMERIC_QUERY = /^\s*(>=|<=|>|<|=|!=)\s*-?[\d.,]+\s*$|^\s*-?[\d.,]+\s*\.\.\s*-?[\d.,]+\s*$/;

/** Same normalisation as the server: lower case, no accents. Keeps one output char per input char. */
function fold(text: string) {
  return Array.from(text, (ch) => ch.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().slice(0, 1) || ch).join("");
}

function highlight(text: string, needle: string): ReactNode {
  if (!needle) return text;
  const at = fold(text).indexOf(needle);
  if (at < 0) return text;
  return <>{text.slice(0, at)}<mark>{text.slice(at, at + needle.length)}</mark>{text.slice(at + needle.length)}</>;
}

export function DataGrid(props: Props) {
  const { page, profile, sort, desc, search, hidden, onSort, onPage, onSize } = props;
  const from = page.total_rows === 0 ? 0 : (page.page - 1) * page.size + 1;
  const to = Math.min(page.page * page.size, page.total_rows);
  const filtered = !!search.q.trim() && page.all_rows !== undefined && page.all_rows !== page.total_rows;
  const needle = search.q.trim() && !NUMERIC_QUERY.test(search.q) ? fold(search.q.trim()) : "";
  return (
    <section className="grid-panel">
      <GridToolbar {...props} />
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
                {row.map((cell, j) => {
                  const column = page.columns[j];
                  const searchable = needle && cell !== null && (!search.scope || search.scope === column.name);
                  if (!searchable) return <Cell key={j} value={cell} numeric={isNumericDtype(column.dtype)} />;
                  return <td key={j} className={isNumericDtype(column.dtype) ? "num" : undefined}>{highlight(formatValue(cell), needle)}</td>;
                })}
              </tr>
            ))}
            {page.rows.length === 0 && (
              <tr><td className="empty-row" colSpan={page.columns.length + 1}>Καμία γραμμή δεν ταιριάζει.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <footer className="pager">
        <span className="muted">
          {formatInt(from)}–{formatInt(to)} από {formatInt(page.total_rows)} γραμμές
          {filtered && <> (από {formatInt(page.all_rows ?? 0)})</>}
          {hidden.length > 0 && <> · {hidden.length} κρυφές στήλες</>}
          {sort && <> · ταξινόμηση προβολής: <b>{sort}</b> <button className="link" onClick={() => onSort("")}>καθαρισμός</button></>}
        </span>
        <div className="pager-controls">
          <select value={page.size} onChange={(e) => onSize(Number(e.target.value))} aria-label="Γραμμές ανά σελίδα">
            {[25, 50, 100, 250, 500].map((n) => <option key={n} value={n}>{n} / σελίδα</option>)}
          </select>
          <button className="btn small" disabled={page.page <= 1} onClick={() => onPage(1)} aria-label="Πρώτη σελίδα">«</button>
          <button className="btn small" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)} aria-label="Προηγούμενη σελίδα">‹</button>
          <PageInput page={page.page} total={page.total_pages} onPage={onPage} />
          <button className="btn small" disabled={page.page >= page.total_pages} onClick={() => onPage(page.page + 1)} aria-label="Επόμενη σελίδα">›</button>
          <button className="btn small" disabled={page.page >= page.total_pages} onClick={() => onPage(page.total_pages)} aria-label="Τελευταία σελίδα">»</button>
        </div>
      </footer>
    </section>
  );
}

function PageInput({ page, total, onPage }: { page: number; total: number; onPage: (n: number) => void }) {
  const [value, setValue] = useState(String(page));
  useEffect(() => setValue(String(page)), [page]);
  const go = () => {
    const n = Math.min(Math.max(1, Math.round(Number(value)) || 1), total);
    setValue(String(n));
    if (n !== page) onPage(n);
  };
  return (
    <span className="page-input">
      <input value={value} inputMode="numeric" aria-label="Σελίδα" onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && go()} onBlur={go} />
      / {formatInt(total)}
    </span>
  );
}

function GridToolbar({ profile, search, hidden, onSearch, onHidden, onKeepMatches, page }: Props) {
  const [text, setText] = useState(search.q);
  const columns = Object.entries(profile.columns);
  const scopeMeta = search.scope ? profile.columns[search.scope] : null;

  useEffect(() => setText(search.q), [search.q]);
  // Debounce: search 300 ms after the last keystroke, not on every key.
  useEffect(() => {
    if (text === search.q) return;
    const timer = setTimeout(() => onSearch({ ...search, q: text }), 300);
    return () => clearTimeout(timer);
  }, [text, search, onSearch]);

  const placeholder = scopeMeta?.kind === "numeric"
    ? "π.χ. 120, >100, <=50, 10..20"
    : "Αναζήτηση… (χωρίς διάκριση πεζών/τόνων)";
  return (
    <div className="grid-toolbar">
      <div className="search-box">
        <span aria-hidden>🔍</span>
        <input value={text} placeholder={placeholder} aria-label="Αναζήτηση στον πίνακα"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSearch({ ...search, q: text });
            if (e.key === "Escape") { setText(""); onSearch({ ...search, q: "" }); }
          }} />
        {text && <button className="icon-btn" onClick={() => { setText(""); onSearch({ ...search, q: "" }); }} aria-label="Καθαρισμός αναζήτησης">✕</button>}
      </div>
      <label className="scope">
        <span className="muted small">σε</span>
        <select value={search.scope ?? ""} onChange={(e) => onSearch({ ...search, scope: e.target.value || null })} aria-label="Πού να ψάξει">
          <option value="">όλες τις στήλες</option>
          {columns.map(([name, meta]) => <option key={name} value={name}>{name} ({KIND_TITLE[meta.kind]})</option>)}
        </select>
      </label>
      {search.q.trim() && page.total_rows > 0 && page.total_rows !== page.all_rows && (
        <button className="btn small" onClick={onKeepMatches} title="Δημιουργεί βήμα «Φίλτρο γραμμών» (νέα έκδοση, με αναίρεση)">
          Κράτα μόνο αυτές ({formatInt(page.total_rows)})
        </button>
      )}
      <ColumnPicker columns={columns} hidden={hidden} onHidden={onHidden} />
    </div>
  );
}

function ColumnPicker({ columns, hidden, onHidden }: { columns: [string, ColumnMeta][]; hidden: string[]; onHidden: (h: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const shown = useMemo(() => columns.filter(([n]) => fold(n).includes(fold(filter))), [columns, filter]);
  const visible = columns.length - hidden.length;
  const toggle = (name: string) => {
    const next = hidden.includes(name) ? hidden.filter((h) => h !== name) : [...hidden, name];
    if (next.length < columns.length) onHidden(next); // at least one column stays visible
  };
  return (
    <div className="col-picker" ref={box}>
      <button className={`btn small ${hidden.length ? "active" : ""}`} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        Στήλες {visible}/{columns.length} ▾
      </button>
      {open && (
        <div className="col-picker-menu" role="dialog" aria-label="Ορατές στήλες">
          <input autoFocus placeholder="Αναζήτηση στήλης…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div className="col-picker-tools">
            <button className="link" onClick={() => onHidden([])}>Όλες</button>
            <button className="link" onClick={() => onHidden(columns.slice(1).map(([n]) => n))}>Μόνο η πρώτη</button>
            <button className="link" onClick={() => onHidden(columns.filter(([, m]) => m.null_count === 0).map(([n]) => n).slice(0, columns.length - 1))}>Μόνο με κενά</button>
          </div>
          <div className="col-picker-list">
            {shown.map(([name, meta]) => (
              <label key={name} className="check">
                <input type="checkbox" checked={!hidden.includes(name)} onChange={() => toggle(name)} />
                <span className={`kind kind-${meta.kind}`}>{KIND_LABEL[meta.kind]}</span>
                <span className="picker-name">{name}</span>
                {meta.null_count > 0 && <span className="muted small">{meta.null_pct}%</span>}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
