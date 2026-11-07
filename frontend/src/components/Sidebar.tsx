import { useState } from "react";
import type { Catalog, Operation, Suggestion } from "../types";

interface Props {
  catalog: Catalog;
  suggestions: Suggestion[];
  onPick: (op: Operation, initial?: Record<string, unknown>) => void;
}

export function Sidebar({ catalog, suggestions, onPick }: Props) {
  const [query, setQuery] = useState("");
  // Categories start closed; a click opens one. While searching, matching categories open by themselves.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const byId = Object.fromEntries(catalog.operations.map((op) => [op.id, op]));
  const q = query.trim().toLowerCase();
  const matches = (op: Operation) =>
    !q || op.label.toLowerCase().includes(q) || op.description.toLowerCase().includes(q) || op.id.includes(q);

  return (
    <aside className="sidebar">
      {suggestions.length > 0 && !q && (
        <div className="suggestions">
          <h3>Προτάσεις για αυτό το αρχείο</h3>
          {suggestions.map((s, i) => {
            const op = byId[s.op];
            if (!op) return null;
            return (
              <button key={i} className="suggestion" onClick={() => onPick(op, s.params)} title="Άνοιγμα με προσυμπληρωμένες επιλογές">
                <b>{op.label}</b>
                <span>{s.reason}</span>
              </button>
            );
          })}
        </div>
      )}
      <input className="search" placeholder="Αναζήτηση λειτουργίας…" value={query} onChange={(e) => setQuery(e.target.value)} />
      {catalog.categories.filter((category) => !category.hidden).map((category) => {
        const ops = catalog.operations.filter((op) => op.category === category.id && matches(op));
        if (!ops.length) return null;
        const isClosed = !open[category.id] && !q;
        return (
          <div key={category.id} className="category">
            <button className="category-head" aria-expanded={!isClosed}
              onClick={() => setOpen((o) => ({ ...o, [category.id]: !o[category.id] }))}>
              <span>{isClosed ? "▸" : "▾"} {category.label}</span>
              <span className="muted small">{ops.length}</span>
            </button>
            {!isClosed && (
              <div className="ops">
                {ops.map((op) => (
                  <button key={op.id} className={`op op-${op.kind}`} title={op.description} onClick={() => onPick(op)}>
                    <span className="op-icon" aria-hidden>{op.kind === "inspect" ? "◎" : "✎"}</span>
                    {op.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
      <p className="legend muted small">◎ μόνο ανάγνωση · ✎ αλλάζει τα δεδομένα (με αναίρεση)</p>
    </aside>
  );
}
