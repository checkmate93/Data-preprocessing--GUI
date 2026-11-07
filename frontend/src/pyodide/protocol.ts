/** Messages between the main thread and the Pyodide worker. */

export const PYODIDE_VERSION = "0.27.7";

export interface LoadHints {
  text: string[]; // keep as text (leading zeros: ΑΦΜ, ΤΚ, codes)
  dates: string[]; // parse as dates
  category: string[];
}

export interface Display {
  kind: "table" | "text";
  text?: string;
  shape?: [number, number];
  columns?: { name: string; dtype: string }[];
  rows?: unknown[][];
}

export interface RunResult {
  stdout: string;
  display: Display | null;
  error: string | null;
  images: string[];
  df_shape: [number, number] | null;
  seconds: number;
}

export type WorkerIn =
  | { type: "init" }
  | { type: "load"; id: number; csv: string; hints: LoadHints }
  | { type: "run"; id: number; code: string }
  | { type: "csv"; id: number; name: string };

export type WorkerOut =
  | { type: "status"; text: string }
  | { type: "ready"; version: string }
  | { type: "loaded"; id: number; shape: [number, number] }
  | ({ type: "result"; id: number } & RunResult)
  | { type: "csv"; id: number; csv: string }
  | { type: "error"; id?: number; error: string };
