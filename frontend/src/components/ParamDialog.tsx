import { useMemo, useRef, useState } from "react";
import { KIND_LABEL, KIND_TITLE } from "../format";
import type { Attachment, ColumnMeta, Operation, SchemaProp } from "../types";
import { Modal } from "./Modal";

type Values = Record<string, unknown>;
type Columns = [string, ColumnMeta][];

interface Props {
  op: Operation;
  columns: Columns;
  attachments: Attachment[];
  onAttach: (file: File) => Promise<Attachment[]>;
  initial?: Values;
  onClose: () => void;
  onRun: (params: Values, preview: boolean) => void;
}

/** pydantic writes `X | None` as anyOf [X, null]; keep the non-null branch. */
function resolve(prop: SchemaProp): SchemaProp {
  if (Array.isArray(prop.anyOf)) {
    const real = prop.anyOf.find((p: SchemaProp) => p.type !== "null") ?? {};
    return { ...real, ...prop, anyOf: undefined };
  }
  return prop;
}

function defaultFor(prop: SchemaProp): unknown {
  if ("default" in prop) return structuredClone(prop.default);
  if (prop.type === "array") return [];
  if (prop.type === "object") return {};
  if (prop.type === "boolean") return false;
  return "";
}

export function hasParams(op: Operation): boolean {
  return Object.keys(op.schema.properties ?? {}).length > 0;
}

export function ParamDialog({ op, columns, attachments, onAttach, initial, onClose, onRun }: Props) {
  const props = useMemo(
    () => Object.entries(op.schema.properties ?? {}).map(([key, p]) => [key, resolve(p)] as [string, SchemaProp]),
    [op],
  );
  const required = new Set(op.schema.required ?? []);
  const [values, setValues] = useState<Values>(() => {
    const start: Values = {};
    for (const [key, prop] of props) start[key] = defaultFor(prop);
    return { ...start, ...(initial ?? {}) };
  });
  const [error, setError] = useState<string | null>(null);

  const set = (key: string, value: unknown) => setValues((v) => ({ ...v, [key]: value }));

  function validate(): string | null {
    for (const [key, prop] of props) {
      const value = values[key];
      const title = prop.title ?? key;
      if (prop.ui === "columns" && prop.required_choice && (value as string[]).length === 0)
        return `${title}: διάλεξε τουλάχιστον μία στήλη.`;
      if (prop.ui === "column" && required.has(key) && !value) return `${title}: διάλεξε στήλη.`;
      if (prop.ui === "attachment" && !value) return "Ανέβασε ή διάλεξε το δεύτερο αρχείο.";
      if (prop.ui === "conditions" && (value as unknown[]).length === 0) return "Πρόσθεσε τουλάχιστον μία συνθήκη.";
      if (prop.ui === "aggregations" && (value as unknown[]).length === 0) return "Πρόσθεσε τουλάχιστον μία συνάθροιση.";
      if (prop.ui === "json" && String(value).trim()) {
        try {
          JSON.parse(String(value));
        } catch {
          return `${title}: το JSON δεν είναι έγκυρο.`;
        }
      }
      if (prop.ui === "multienum" && (value as unknown[]).length === 0) return `${title}: διάλεξε τουλάχιστον ένα.`;
      if (required.has(key) && (value === "" || value === undefined)) return `${title}: υποχρεωτικό πεδίο.`;
    }
    return null;
  }

  function submit(preview: boolean) {
    const problem = validate();
    if (problem) return setError(problem);
    const params: Values = {};
    for (const [key, prop] of props) {
      let value = values[key];
      if (prop.type === "integer" || prop.type === "number") value = value === "" || value === null ? null : Number(value);
      if (prop.ui === "rename_map")
        value = Object.fromEntries(Object.entries(value as Record<string, string>).filter(([, v]) => v.trim()));
      params[key] = value;
    }
    onRun(params, preview);
  }

  const isTransform = op.kind === "transform";
  return (
    <Modal
      title={op.label}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Άκυρο</button>
          {isTransform && <button className="btn" onClick={() => submit(true)}>Προεπισκόπηση</button>}
          <button className="btn primary" onClick={() => submit(false)}>{isTransform ? "Εφαρμογή" : "Εκτέλεση"}</button>
        </>
      }
    >
      <p className="muted">{op.description}</p>
      <p className={`badge ${isTransform ? "warn" : "info"}`}>
        {isTransform ? "Δημιουργεί νέα έκδοση (υπάρχει αναίρεση)" : "Μόνο ανάγνωση — τα δεδομένα δεν αλλάζουν"}
      </p>
      <div className="form">
        {props.map(([key, prop]) => (
          <Field
            key={key}
            name={key}
            prop={prop}
            value={values[key]}
            required={required.has(key)}
            columns={columns}
            attachments={attachments}
            onAttach={onAttach}
            onChange={(v) => set(key, v)}
          />
        ))}
      </div>
      {error && <div className="alert error">{error}</div>}
    </Modal>
  );
}

interface FieldProps {
  name: string;
  prop: SchemaProp;
  value: unknown;
  required: boolean;
  columns: Columns;
  attachments: Attachment[];
  onAttach: (file: File) => Promise<Attachment[]>;
  onChange: (value: unknown) => void;
}

function Field({ name, prop, value, required, columns, attachments, onAttach, onChange }: FieldProps) {
  const title = prop.title ?? name;
  const help = prop.description ? <small className="muted">{prop.description}</small> : null;

  if (prop.ui === "attachment")
    return <AttachmentField title={title} value={value as string} attachments={attachments} onAttach={onAttach} onChange={onChange} help={help} />;

  if (prop.ui === "aggregations")
    return <AggregationsEditor title={title} labels={prop.agg_labels} columns={columns} value={value as Aggregation[]} onChange={onChange} />;

  if (prop.ui === "json")
    return (
      <label>
        <span>{title}</span>
        <textarea rows={8} className="mono" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} placeholder="{ }" />
        {help}
      </label>
    );

  if (prop.ui === "columns")
    return (
      <fieldset>
        <legend>{title}{prop.required_choice && " *"}</legend>
        <ColumnPicker columns={columns} selected={value as string[]} onChange={onChange} />
        {help}
      </fieldset>
    );

  if (prop.ui === "column")
    return (
      <label>
        <span>{title}{required && " *"}</span>
        <select value={value as string} onChange={(e) => onChange(e.target.value)}>
          <option value="">{required ? "— διάλεξε —" : "— καμία —"}</option>
          {columns.map(([name, meta]) => (
            <option key={name} value={name}>{name} ({KIND_TITLE[meta.kind]})</option>
          ))}
        </select>
        {help}
      </label>
    );

  if (prop.ui === "rename_map") {
    const mapping = value as Record<string, string>;
    return (
      <fieldset>
        <legend>{title}</legend>
        <div className="rename-grid">
          {columns.map(([column]) => (
            <label key={column} className="rename-row">
              <code title={column}>{column}</code>
              <span>→</span>
              <input
                placeholder="(ίδιο)"
                value={mapping[column] ?? ""}
                onChange={(e) => onChange({ ...mapping, [column]: e.target.value })}
              />
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (prop.ui === "conditions")
    return <ConditionsEditor title={title} labels={prop.operator_labels} columns={columns} value={value as Condition[]} onChange={onChange} />;

  if (prop.ui === "multienum") {
    const options: string[] = prop.items?.enum ?? [];
    const selected = value as string[];
    return (
      <fieldset>
        <legend>{title}</legend>
        <div className="checks">
          {options.map((option) => (
            <label key={option} className="check">
              <input
                type="checkbox"
                checked={selected.includes(option)}
                onChange={(e) => onChange(e.target.checked ? [...selected, option] : selected.filter((s) => s !== option))}
              />
              {prop.enum_labels?.[option] ?? option}
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (Array.isArray(prop.enum))
    return (
      <label>
        <span>{title}</span>
        <select value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {prop.enum.map((option: string) => (
            <option key={option} value={option}>{prop.enum_labels?.[option] ?? option}</option>
          ))}
        </select>
        {help}
      </label>
    );

  if (prop.type === "boolean")
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {title}
      </label>
    );

  if (prop.type === "integer" || prop.type === "number")
    return (
      <label>
        <span>{title}</span>
        <input
          type="number"
          step={prop.type === "integer" ? 1 : "any"}
          min={prop.minimum ?? prop.exclusiveMinimum}
          max={prop.maximum}
          value={value === null || value === undefined ? "" : (value as number)}
          onChange={(e) => onChange(e.target.value)}
        />
        {help}
      </label>
    );

  return (
    <label>
      <span>{title}</span>
      <input value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />
      {help}
    </label>
  );
}

function ColumnPicker({ columns, selected, onChange }: { columns: Columns; selected: string[]; onChange: (v: string[]) => void }) {
  const [filter, setFilter] = useState("");
  const shown = columns.filter(([name]) => name.toLowerCase().includes(filter.toLowerCase()));
  const toggle = (name: string, on: boolean) =>
    onChange(on ? columns.map(([c]) => c).filter((c) => c === name || selected.includes(c)) : selected.filter((c) => c !== name));
  return (
    <div className="picker">
      <div className="picker-tools">
        {columns.length > 8 && <input placeholder="Αναζήτηση στήλης…" value={filter} onChange={(e) => setFilter(e.target.value)} />}
        <button type="button" className="link" onClick={() => onChange(columns.map(([c]) => c))}>Όλες</button>
        <button type="button" className="link" onClick={() => onChange([])}>Καμία</button>
        <span className="muted">{selected.length} επιλεγμένες</span>
      </div>
      <div className="picker-list">
        {shown.map(([name, meta]) => (
          <label key={name} className="check">
            <input type="checkbox" checked={selected.includes(name)} onChange={(e) => toggle(name, e.target.checked)} />
            <span className={`kind kind-${meta.kind}`} title={KIND_TITLE[meta.kind]}>{KIND_LABEL[meta.kind]}</span>
            <span className="picker-name">{name}</span>
            {meta.null_count > 0 && <span className="muted small">{meta.null_pct}% κενά</span>}
          </label>
        ))}
      </div>
    </div>
  );
}

function AttachmentField(props: {
  title: string;
  value: string;
  attachments: Attachment[];
  onAttach: (file: File) => Promise<Attachment[]>;
  onChange: (v: string) => void;
  help: React.ReactNode;
}) {
  const { title, value, attachments, onAttach, onChange, help } = props;
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = attachments.find((a) => a.name === value);
  return (
    <fieldset>
      <legend>{title} *</legend>
      <div className="attach-row">
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          <option value="">— διάλεξε —</option>
          {attachments.map((a) => <option key={a.name} value={a.name}>{a.filename} ({a.shape[0]} × {a.shape[1]})</option>)}
        </select>
        <button type="button" className="btn small" disabled={busy} onClick={() => input.current?.click()}>
          {busy ? "Ανάγνωση…" : "Ανέβασμα…"}
        </button>
        <input
          ref={input}
          type="file"
          hidden
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            setBusy(true);
            setError(null);
            try {
              await onAttach(file);
              onChange(file.name);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        />
      </div>
      {selected && <small className="muted">Στήλες: {selected.columns.slice(0, 15).join(", ")}{selected.columns.length > 15 ? "…" : ""}</small>}
      {error && <div className="alert error">{error}</div>}
      {help}
    </fieldset>
  );
}

interface Aggregation {
  column: string;
  func: string;
}

function AggregationsEditor(props: {
  title: string;
  labels: Record<string, string>;
  columns: Columns;
  value: Aggregation[];
  onChange: (v: Aggregation[]) => void;
}) {
  const { title, labels, columns, value, onChange } = props;
  const update = (i: number, patch: Partial<Aggregation>) => onChange(value.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  return (
    <fieldset>
      <legend>{title} *</legend>
      {value.map((agg, i) => (
        <div className="condition agg" key={i}>
          <select value={agg.column} onChange={(e) => update(i, { column: e.target.value })}>
            {columns.map(([name]) => <option key={name}>{name}</option>)}
          </select>
          <select value={agg.func} onChange={(e) => update(i, { func: e.target.value })}>
            {Object.entries(labels).map(([func, label]) => <option key={func} value={func}>{label}</option>)}
          </select>
          <button type="button" className="icon-btn" title="Αφαίρεση" onClick={() => onChange(value.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button
        type="button"
        className="btn small"
        onClick={() => {
          const numeric = columns.find(([, meta]) => meta.kind === "numeric")?.[0] ?? columns[0]?.[0] ?? "";
          onChange([...value, { column: numeric, func: "sum" }]);
        }}
      >
        + Συνάθροιση
      </button>
    </fieldset>
  );
}

interface Condition {
  column: string;
  op: string;
  value: string;
}

function ConditionsEditor(props: {
  title: string;
  labels: Record<string, string>;
  columns: Columns;
  value: Condition[];
  onChange: (v: Condition[]) => void;
}) {
  const { title, labels, columns, value, onChange } = props;
  const update = (i: number, patch: Partial<Condition>) => onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <fieldset>
      <legend>{title}</legend>
      {value.map((condition, i) => (
        <div className="condition" key={i}>
          <select value={condition.column} onChange={(e) => update(i, { column: e.target.value })}>
            {columns.map(([name]) => <option key={name}>{name}</option>)}
          </select>
          <select value={condition.op} onChange={(e) => update(i, { op: e.target.value })}>
            {Object.entries(labels).map(([op, label]) => <option key={op} value={op}>{label}</option>)}
          </select>
          {!["isna", "notna"].includes(condition.op) && (
            <input placeholder="τιμή" value={condition.value} onChange={(e) => update(i, { value: e.target.value })} />
          )}
          <button type="button" className="icon-btn" title="Αφαίρεση" onClick={() => onChange(value.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button
        type="button"
        className="btn small"
        onClick={() => onChange([...value, { column: columns[0]?.[0] ?? "", op: "==", value: "" }])}
      >
        + Συνθήκη
      </button>
    </fieldset>
  );
}
