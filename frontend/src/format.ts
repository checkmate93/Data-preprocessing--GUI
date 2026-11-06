import type { Kind } from "./types";

const numberFormat = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 4 });

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return numberFormat.format(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  // Dates without a time of day come back from the API as ISO with T00:00:00.
  return /^\d{4}-\d{2}-\d{2}T00:00:00$/.test(text) ? text.slice(0, 10) : text;
}

export function formatInt(value: number): string {
  return new Intl.NumberFormat("el-GR").format(value);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export const KIND_LABEL: Record<Kind, string> = {
  numeric: "123",
  boolean: "0/1",
  datetime: "📅",
  text: "abc",
  categorical: "cat",
};

export const KIND_TITLE: Record<Kind, string> = {
  numeric: "Αριθμητική",
  boolean: "Boolean",
  datetime: "Ημερομηνία",
  text: "Κείμενο",
  categorical: "Κατηγορία",
};

export function isNumericDtype(dtype: string): boolean {
  return /int|float|uint/i.test(dtype);
}

export const DELIMITER_LABEL: Record<string, string> = { ",": "κόμμα ( , )", ";": "ερωτηματικό ( ; )", "\t": "TAB", "|": "pipe ( | )" };
