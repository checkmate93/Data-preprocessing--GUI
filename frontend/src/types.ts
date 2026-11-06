export type Kind = "numeric" | "boolean" | "datetime" | "text" | "categorical";

export interface ColumnMeta {
  dtype: string;
  kind: Kind;
  null_count: number;
  null_pct: number;
  unique: number;
  flags: string[];
  top?: unknown;
  min?: number;
  max?: number;
  mean?: number;
  median?: number;
  skew?: number | null;
}

export interface Profile {
  version: number;
  shape: [number, number];
  memory_mb: number;
  duplicates_count: number;
  total_missing: number;
  rows_with_missing: number;
  names_not_snake: string[];
  quality: { total: number; completeness: number; uniqueness: number; validity: number; consistency: number };
  columns: Record<string, ColumnMeta>;
}

export interface Source {
  filename: string;
  size_bytes: number;
  format: string;
  encoding?: string;
  encoding_confidence?: number;
  encoding_alternatives?: string[];
  delimiter?: string;
  decimal?: string;
  sheet?: string | null;
  sheets?: string[];
  read_warnings?: string[];
}

export interface VersionInfo {
  version: number;
  shape: [number, number];
  label: string;
  op: string | null;
  summary: string | null;
  params: Record<string, unknown> | null;
  at: string | null;
}

export interface History {
  current_version: number;
  versions: VersionInfo[];
  can_undo: boolean;
  can_redo: boolean;
}

export interface Suggestion {
  op: string;
  params: Record<string, unknown>;
  reason: string;
}

export interface SessionState {
  session_id: string;
  source: Source;
  profile: Profile;
  history: History;
  suggestions: Suggestion[];
  attachments: Attachment[];
}

export interface FrameData {
  columns: { name: string; dtype: string }[];
  rows: unknown[][];
}

export interface Page extends FrameData {
  index: unknown[];
  page: number;
  size: number;
  total_rows: number;
  total_pages: number;
}

export type Section =
  | { type: "cards"; title?: string | null; items: { label: string; value: unknown }[] }
  | { type: "table"; title?: string | null; data: FrameData }
  | { type: "text"; title?: string | null; content: string }
  | { type: "bar"; title?: string | null; labels: string[]; values: number[]; unit: string }
  | { type: "histogram"; title?: string | null; column: string; edges: number[]; counts: number[] }
  | {
      type: "box";
      title?: string | null;
      items: {
        label: string; count: number; q1: number; median: number; q3: number; whisker_low: number;
        whisker_high: number; min: number; max: number; outliers: number[]; outlier_count: number;
      }[];
    }
  | { type: "scatter"; title?: string | null; x_label: string; y_label: string; points: number[][]; total: number; sampled: boolean }
  | { type: "line"; title?: string | null; x_label: string; x: (string | number)[]; series: { name: string; values: (number | null)[] }[] }
  | { type: "heatmap"; title?: string | null; x_labels: string[]; y_labels: string[]; values: (number | null)[][]; diverging: boolean }
  | { type: "downloads"; title?: string | null; files: { label: string; name: string; size: number }[] };

export interface Attachment {
  name: string;
  filename: string;
  format: string;
  encoding?: string | null;
  shape: [number, number];
  columns: string[];
}

export interface Diff {
  shape_before: [number, number];
  shape_after: [number, number];
  rows_removed: number;
  added_columns: string[];
  removed_columns: string[];
  dtype_changes: { column: string; from: string; to: string }[];
  changed_cells: number | null;
  changed_columns: string[];
  missing_before: number;
  missing_after: number;
}

export interface OpResult {
  status: "ok";
  op?: string;
  label?: string;
  kind?: "inspect" | "transform";
  preview?: boolean;
  message: string;
  warnings: string[];
  sections: Section[];
  code?: string | null;
  diff?: Diff | null;
  params?: Record<string, unknown>;
  preview_rows?: Page;
  replay_failed?: boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type SchemaProp = Record<string, any>;

export interface Operation {
  id: string;
  label: string;
  description: string;
  category: string;
  kind: "inspect" | "transform";
  schema: { properties?: Record<string, SchemaProp>; required?: string[]; $defs?: Record<string, SchemaProp> };
}

export interface Catalog {
  categories: { id: string; label: string }[];
  operations: Operation[];
}
