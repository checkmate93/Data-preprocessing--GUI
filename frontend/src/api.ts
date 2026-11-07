import type { AssistantStatus, Catalog, ChatState, OpResult, Page, SessionState } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json() as Promise<T>;
}

async function errorMessage(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch {
    return text || `${response.status} ${response.statusText}`;
  }
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export type StateWithPage = SessionState & { page: Page };
export type StateWithResult = SessionState & { result: OpResult };

export interface ReloadOptions {
  encoding?: string;
  delimiter?: string;
  decimal?: string;
  sheet?: string;
}

const base = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;

export const api = {
  catalog: () => request<Catalog>("/api/operations"),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<StateWithPage>("/api/sessions", { method: "POST", body: form });
  },

  session: async (id: string): Promise<SessionState | null> => {
    const response = await fetch(base(id));
    if (response.status === 404) return null; // expired or deleted
    if (!response.ok) throw new Error(await errorMessage(response));
    return response.json();
  },

  reload: (id: string, options: ReloadOptions) => request<StateWithPage>(`${base(id)}/reload`, json(options)),

  data: (id: string, page: number, size: number, sort: string | null, desc: boolean) => {
    const query = new URLSearchParams({ page: String(page), size: String(size), desc: String(desc) });
    if (sort) query.set("sort", sort);
    return request<Page>(`${base(id)}/data?${query}`);
  },

  op: (id: string, op: string, params: Record<string, unknown>, preview: boolean) =>
    request<StateWithResult>(`${base(id)}/ops`, json({ op, params, preview })),

  undo: (id: string) => request<StateWithResult>(`${base(id)}/undo`, { method: "POST" }),
  redo: (id: string) => request<StateWithResult>(`${base(id)}/redo`, { method: "POST" }),
  checkout: (id: string, version: number) => request<StateWithResult>(`${base(id)}/checkout/${version}`, { method: "POST" }),

  script: (id: string) => request<{ filename: string; script: string }>(`${base(id)}/script`),
  recipe: (id: string) => request<unknown>(`${base(id)}/recipe`),
  applyRecipe: (id: string, recipe: unknown) => request<StateWithResult>(`${base(id)}/recipe/apply`, json(recipe)),

  attach: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<SessionState>(`${base(id)}/attachments`, { method: "POST", body: form });
  },

  fileUrl: (id: string, name: string) => `${base(id)}/files/${encodeURIComponent(name)}`,

  saveBrowserVersion: (id: string, payload: { csv: string; dtypes: Record<string, string>; code: string; description: string; baseVersion: number }) => {
    const form = new FormData();
    form.append("file", new Blob([payload.csv], { type: "text/csv" }), "df.csv");
    form.append("base_version", String(payload.baseVersion));
    form.append("code", payload.code);
    form.append("description", payload.description);
    form.append("dtypes", JSON.stringify(payload.dtypes));
    return request<StateWithResult>(`${base(id)}/browser-version`, { method: "POST", body: form });
  },

  assistantStatus: () => request<AssistantStatus>("/api/assistant/status"),
  chat: (id: string) => request<ChatState>(`${base(id)}/chat`),
  sendChat: (id: string, message: string, token: string) =>
    request<SessionState & { chat: ChatState; data_changed: boolean }>(`${base(id)}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { "X-Assistant-Token": token } : {}) },
      body: JSON.stringify({ message }),
    }),
  clearChat: (id: string) => request<ChatState>(`${base(id)}/chat`, { method: "DELETE" }),

  exportUrl: (id: string, format: string, encoding: string, delimiter: string) =>
    `${base(id)}/export?${new URLSearchParams({ format, encoding, delimiter })}`,

  deleteSession: (id: string) => request<unknown>(base(id), { method: "DELETE" }),
};

/** Fetch a file and save it, so API errors show as a message instead of a JSON page. */
export async function download(url: string, fallbackName: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await errorMessage(response));
  const blob = await response.blob();
  saveBlob(blob, filenameFrom(response.headers.get("Content-Disposition")) ?? fallbackName);
}

export function saveBlob(blob: Blob, name: string) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function filenameFrom(header: string | null): string | null {
  if (!header) return null;
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(header);
  if (encoded) return decodeURIComponent(encoded[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}
