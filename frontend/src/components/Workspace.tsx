/**
 * Everything for ONE dataset (one tab): its server session, grid page, results, dialogs, chat and
 * Python panel. The tab manager keeps every Workspace mounted and only hides inactive ones, so all
 * of this state survives switching tabs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, download, saveBlob, type ReloadOptions } from "../api";
import { DELIMITER_LABEL, formatBytes } from "../format";
import type { AssistantStatus, Catalog, ChatState, OpResult, Operation, Page, SessionState } from "../types";
import { ChatPanel } from "./ChatPanel";
import { DataGrid, type Search } from "./DataGrid";
import { ExportDialog, ReloadDialog, ScriptDialog, type ExportOptions } from "./Dialogs";
import { HistoryPanel } from "./HistoryPanel";
import { ParamDialog, hasParams } from "./ParamDialog";
import { ProfileBar } from "./ProfileBar";
import { PythonPanel } from "./PythonPanel";
import { ResultPanel } from "./ResultPanel";
import { Sidebar } from "./Sidebar";
import { Upload } from "./Upload";

/** What the tab bar needs to know about a workspace. */
export interface TabMeta {
  title: string;
  sessionId: string | null;
  dirty: boolean; // closing would lose versions, chat or Python work
  busy: boolean;
}

interface Props {
  catalog: Catalog | null;
  assistant: AssistantStatus | null;
  active: boolean;
  onMeta: (meta: TabMeta) => void;
  /** Tab remembered from an earlier visit: restore this server session the first time the tab is shown. */
  restore?: { sessionId: string; title: string };
}

const EMPTY_CHAT: ChatState = { messages: [], usage: { input_tokens: 0, output_tokens: 0, calls: 0, last_input_tokens: 0 } };

/** What the grid shows. View only: none of this changes the data. */
interface View {
  page: number;
  size: number;
  sort: string | null;
  desc: boolean;
  q: string;
  scope: string | null;
}

type Modal = { kind: "export" } | { kind: "reload" } | { kind: "script"; script: string } | null;

const FIRST_VIEW: View = { page: 1, size: 50, sort: null, desc: false, q: "", scope: null };
const HIDDEN_KEY = (sessionId: string) => `dataprep.hidden.${sessionId}`;
const NUMERIC_QUERY = /^\s*(>=|<=|>|<|=|!=)\s*(-?[\d.,]+)\s*$/;
const RANGE_QUERY = /^\s*(-?[\d.,]+)\s*\.\.\s*(-?[\d.,]+)\s*$/;

function readHidden(sessionId: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(HIDDEN_KEY(sessionId)) ?? "[]");
  } catch {
    return [];
  }
}

/** The grid search as «Φίλτρο γραμμών» conditions (same matching rules as the server search). */
function searchToFilter(view: View, profile: SessionState["profile"]) {
  const q = view.q.trim();
  if (view.scope) {
    const numeric = profile.columns[view.scope]?.kind === "numeric";
    const compare = numeric ? NUMERIC_QUERY.exec(q) : null;
    const range = numeric ? RANGE_QUERY.exec(q) : null;
    const condition = compare
      ? { column: view.scope, op: compare[1] === "=" ? "==" : compare[1], value: compare[2] }
      : range
        ? { column: view.scope, op: "between", value: `${range[1]},${range[2]}` }
        : { column: view.scope, op: "contains", value: q };
    return { conditions: [condition], combine: "and", mode: "keep" };
  }
  const conditions = Object.keys(profile.columns).map((column) => ({ column, op: "contains", value: q }));
  return { conditions, combine: "or", mode: "keep" };
}

export function Workspace({ catalog, assistant, active, onMeta, restore }: Props) {
  // "pending" until the tab is first shown: inactive remembered tabs cost no memory and no requests.
  const [restoreState, setRestoreState] = useState<"none" | "pending" | "loading">(restore ? "pending" : "none");
  const [notice, setNotice] = useState<string | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [view, setView] = useState<View>(FIRST_VIEW);
  const [result, setResult] = useState<OpResult | null>(null);
  const [dialog, setDialog] = useState<{ op: Operation; initial?: Record<string, unknown> } | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ tone: "error" | "ok"; text: string } | null>(null);
  const [chat, setChat] = useState<ChatState>(EMPTY_CHAT);
  const [chatOpen, setChatOpen] = useState(false);
  const [pythonOpen, setPythonOpen] = useState(false);
  const [pythonMounted, setPythonMounted] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);

  const restoring = restoreState !== "none";
  const title = session?.source.filename ?? (restoring && restore ? restore.title : "Νέο αρχείο");
  const sessionId = session?.session_id ?? (restoring && restore ? restore.sessionId : null);
  // A not-yet-restored tab may hold work on the server: closing it asks first.
  const dirty = restoring || (!!session && ((session.history.current_version ?? 0) > 0 || chat.messages.length > 0 || pythonMounted));
  const working = busy !== null || chatBusy || restoreState === "loading";
  useEffect(() => {
    onMeta({ title, sessionId, dirty, busy: working });
  }, [title, sessionId, dirty, working, onMeta]);

  useEffect(() => {
    if (!active || restoreState !== "pending" || !restore) return;
    setRestoreState("loading");
    (async () => {
      try {
        const state = await api.session(restore.sessionId);
        if (!state) {
          setNotice(`Η συνεδρία «${restore.title}» δεν υπάρχει πια στον server (έληξε ή ο server ξεκίνησε από την αρχή). Ανέβασε ξανά το αρχείο.`);
          return;
        }
        const [firstPage, savedChat] = await Promise.all([
          api.data(restore.sessionId, 1, FIRST_VIEW.size, null, false, { hide: readHidden(restore.sessionId) }),
          api.chat(restore.sessionId),
        ]);
        setSession(state);
        setPage(firstPage);
        setChat(savedChat);
      } catch (e) {
        setNotice(`Η επαναφορά της «${restore.title}» απέτυχε: ${(e as Error).message}`);
      } finally {
        setRestoreState("none");
      }
    })();
  }, [active, restoreState, restore]);

  useEffect(() => {
    if (toast?.tone !== "ok") return;
    const timer = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  /** Run an async action with a busy indicator and error toast. */
  const act = useCallback(async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try {
      await fn();
    } catch (e) {
      setToast({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }, []);

  const viewRef = useRef(view);
  viewRef.current = view;

  // Hidden columns: per tab, remembered per file (localStorage). A ref so loadPage always sees the latest.
  const [hidden, setHiddenState] = useState<string[]>([]);
  const hiddenRef = useRef<string[]>([]);
  const currentSessionId = session?.session_id;
  useEffect(() => {
    if (!currentSessionId) return;
    hiddenRef.current = readHidden(currentSessionId);
    setHiddenState(hiddenRef.current);
  }, [currentSessionId]);

  // Responses can arrive out of order (fast typing in the search box): only the latest request may update the grid.
  const pageRequest = useRef(0);
  const loadPage = useCallback(async (id: string, next: View) => {
    const ticket = ++pageRequest.current;
    setView(next);
    const fetchPage = (v: View) => api.data(id, v.page, v.size, v.sort, v.desc, { q: v.q, scope: v.scope, hide: hiddenRef.current });
    let data: Page;
    try {
      data = await fetchPage(next);
    } catch (error) {
      if (!next.scope || ticket !== pageRequest.current) throw error;
      // The searched column no longer exists (e.g. renamed by a step): search all columns instead.
      const all = { ...next, scope: null, page: 1 };
      setView(all);
      data = await fetchPage(all);
    }
    if (ticket === pageRequest.current) setPage(data);
  }, []);

  const setHidden = (id: string, next: string[]) => {
    hiddenRef.current = next;
    setHiddenState(next);
    try {
      localStorage.setItem(HIDDEN_KEY(id), JSON.stringify(next));
    } catch {
      /* storage blocked: the choice lasts until the tab is closed */
    }
    act("Φόρτωση…", () => loadPage(id, view));
  };

  function applyState(next: SessionState & { result?: OpResult; page?: Page }) {
    const { result: _r, page: _p, ...state } = next;
    setSession(state);
  }

  const upload = (file: File) =>
    act("Ανάγνωση αρχείου…", async () => {
      const data = await api.upload(file);
      applyState(data);
      setPage(data.page);
      setView(FIRST_VIEW);
      setResult(null);
      setChat(EMPTY_CHAT);
    });

  const sendChat = async (message: string, token: string) => {
    if (!session) return;
    setChatBusy(true);
    try {
      const data = await api.sendChat(session.session_id, message, token);
      setChat(data.chat);
      const { chat: _c, data_changed, ...state } = data;
      applyState(state);
      if (data_changed) await loadPage(session.session_id, { ...view, page: 1, sort: null });
    } finally {
      setChatBusy(false);
    }
  };

  const clearChat = async () => {
    if (!session) return;
    setChat(await api.clearChat(session.session_id));
  };

  const runOp = (op: Operation, params: Record<string, unknown>, preview: boolean) =>
    act(`${op.label}…`, async () => {
      if (!session) return;
      const data = await api.op(session.session_id, op.id, params, preview);
      setDialog(null);
      applyState(data);
      setResult(data.result);
      if (op.kind === "transform" && !preview) {
        await loadPage(session.session_id, { ...view, page: 1, sort: null });
        setToast({ tone: "ok", text: data.result.message || "Έγινε" });
      }
    });

  const pickOp = (op: Operation, initial?: Record<string, unknown>) => {
    if (hasParams(op)) setDialog({ op, initial });
    else runOp(op, initial ?? {}, false);
  };

  const move = (label: string, fn: (id: string) => ReturnType<typeof api.undo>) =>
    act(label, async () => {
      if (!session) return;
      const data = await fn(session.session_id);
      applyState(data);
      setResult(null);
      await loadPage(session.session_id, { ...view, page: 1 });
      setToast({ tone: "ok", text: data.result.message });
    });

  const reload = (options: ReloadOptions) =>
    act("Ανάγνωση αρχείου…", async () => {
      if (!session) return;
      const data = await api.reload(session.session_id, options);
      applyState(data);
      setPage(data.page);
      setView(FIRST_VIEW);
      setResult(null);
      setModal(null);
    });

  const viewActive = !!view.q.trim() || hidden.length > 0 || !!view.sort;
  const searchState = useMemo(() => ({ q: view.q, scope: view.scope }), [view.q, view.scope]);
  const sessionIdForSearch = session?.session_id;
  const onSearch = useCallback(
    (next: Search) => {
      if (!sessionIdForSearch) return;
      act("Αναζήτηση…", () => loadPage(sessionIdForSearch, { ...viewRef.current, q: next.q, scope: next.scope, page: 1 }));
    },
    [sessionIdForSearch, act, loadPage],
  );

  const exportData = (options: ExportOptions) =>
    act("Εξαγωγή…", async () => {
      if (!session) return;
      const gridView = options.onlyView ? { q: view.q, scope: view.scope, hide: hidden, sort: view.sort, desc: view.desc } : undefined;
      await download(api.exportUrl(session.session_id, options.format, options.encoding, options.delimiter, gridView), "export");
      setModal(null);
    });

  const quickCsv = () =>
    act("Λήψη CSV…", async () => {
      if (!session) return;
      await download(api.exportUrl(session.session_id, "csv", "utf-8-sig", ","), "export.csv");
    });

  const keepMatches = () =>
    act("Φίλτρο γραμμών…", async () => {
      if (!session) return;
      const data = await api.op(session.session_id, "rows.filter", searchToFilter(view, session.profile), false);
      applyState(data);
      setResult(data.result);
      // The rows now ARE the matches: clear the search so the grid shows the new version as it is.
      await loadPage(session.session_id, { ...view, page: 1, q: "", scope: null });
      setToast({ tone: "ok", text: data.result.message || "Έγινε" });
    });

  const showScript = () =>
    act("Δημιουργία κώδικα…", async () => {
      if (!session) return;
      const data = await api.script(session.session_id);
      setModal({ kind: "script", script: data.script });
    });

  const downloadRecipe = () =>
    act("Recipe…", async () => {
      if (!session) return;
      const recipe = await api.recipe(session.session_id);
      saveBlob(new Blob([JSON.stringify(recipe, null, 2)], { type: "application/json" }), "recipe.json");
    });

  const applyRecipe = (file: File) =>
    act("Εφαρμογή recipe…", async () => {
      if (!session) return;
      let recipe: unknown;
      try {
        recipe = JSON.parse(await file.text());
      } catch {
        throw new Error("Το αρχείο δεν είναι έγκυρο recipe.json.");
      }
      const data = await api.applyRecipe(session.session_id, recipe);
      applyState(data);
      setResult(data.result);
      await loadPage(session.session_id, { ...view, page: 1, sort: null });
    });

  const attach = async (file: File) => {
    if (!session) return [];
    const data = await api.attach(session.session_id, file);
    applyState(data);
    return data.attachments;
  };

  const newFile = () => {
    if (session) api.deleteSession(session.session_id).catch(() => undefined);
    setSession(null);
    setPage(null);
    setResult(null);
    setChat(EMPTY_CHAT);
    setChatOpen(false);
    setPythonOpen(false);
    setPythonMounted(false);
  };

  const sortBy = (column: string) => {
    if (!session) return;
    const next: View = !column
      ? { ...view, sort: null, desc: false, page: 1 }
      : view.sort === column
        ? { ...view, desc: !view.desc, page: 1 }
        : { ...view, sort: column, desc: false, page: 1 };
    act("Ταξινόμηση…", () => loadPage(session.session_id, next));
  };

  const toastView = toast && (
    <div className={`toast ${toast.tone}`} role="status">
      <span>{toast.text}</span>
      <button className="icon-btn" onClick={() => setToast(null)} aria-label="Κλείσιμο">✕</button>
    </div>
  );

  if (!session || !page || !catalog)
    return (
      <div className={`tab-pane ${active ? "" : "hidden"}`} role="tabpanel">
        {restoring ? (
          <main className="upload-screen">
            <div className="spinner" />
            <p>Επαναφορά «{title}»…</p>
          </main>
        ) : (
          <Upload busy={busy !== null} onFile={(file) => { setNotice(null); upload(file); }} notice={notice} />
        )}
        {toastView}
      </div>
    );

  const { source, profile, history } = session;
  const columns = Object.entries(profile.columns);

  return (
    <div className={`app tab-pane ${active ? "" : "hidden"}`} role="tabpanel">
      <header className="topbar">
        <div className="file-info" title={source.read_warnings?.join("\n")}>
          <b>{source.filename}</b>
          <span className="muted small">
            {source.format.toUpperCase()} · {formatBytes(source.size_bytes)}
            {source.encoding && ` · ${source.encoding}`}
            {source.delimiter && ` · ${DELIMITER_LABEL[source.delimiter] ?? source.delimiter}`}
            {source.sheet && ` · sheet: ${source.sheet}`}
          </span>
          {!!source.read_warnings?.length && <span className="chip warn">{source.read_warnings.length} προειδοποιήσεις</span>}
        </div>
        <div className="topbar-actions">
          {busy && <span className="busy"><span className="spinner small" />{busy}</span>}
          <button
            className={`btn ${pythonOpen ? "active" : ""}`}
            aria-pressed={pythonOpen}
            title="Γράψε δικό σου κώδικα pandas· τρέχει στον browser σου"
            onClick={() => {
              setPythonMounted(true);
              setPythonOpen((v) => !v);
              setChatOpen(false);
            }}
          >
            🐍 Python
          </button>
          <button className={`btn ${chatOpen ? "active" : ""}`} onClick={() => { setChatOpen((v) => !v); setPythonOpen(false); }} aria-pressed={chatOpen}>
            💬 Βοηθός{chat.messages.length ? ` (${chat.messages.filter((m) => m.role === "user").length})` : ""}
          </button>
          <button className="btn" onClick={() => setModal({ kind: "reload" })}>Ξαναδιάβασε</button>
          <button className="btn" onClick={showScript}>Κώδικας</button>
          <span className="split-btn">
            <button className="btn primary" onClick={quickCsv} title="Κατέβασε αμέσως ολόκληρο τον καθαρό πίνακα (CSV, UTF-8, σωστά ελληνικά στο Excel)">
              ⬇ CSV
            </button>
            <button className="btn primary" onClick={() => setModal({ kind: "export" })} title="Άλλη μορφή, encoding ή μόνο ό,τι φαίνεται">
              Εξαγωγή…
            </button>
          </span>
          <button className="btn ghost" onClick={newFile}>Νέο αρχείο</button>
        </div>
      </header>

      <Sidebar catalog={catalog} suggestions={session.suggestions} onPick={pickOp} />

      <main className="workspace">
        <ProfileBar profile={profile} version={history.current_version} />
        {result && (
          <ResultPanel
            result={result}
            sessionId={session.session_id}
            onClose={() => setResult(null)}
            onApply={() => {
              const op = catalog.operations.find((o) => o.id === result.op);
              if (op) runOp(op, result.params ?? {}, false);
            }}
          />
        )}
        <DataGrid
          page={page}
          profile={profile}
          sort={view.sort}
          desc={view.desc}
          search={searchState}
          hidden={hidden}
          onSearch={onSearch}
          onHidden={(next) => setHidden(session.session_id, next)}
          onKeepMatches={keepMatches}
          onSort={sortBy}
          onPage={(n) => act("Φόρτωση…", () => loadPage(session.session_id, { ...view, page: n }))}
          onSize={(n) => act("Φόρτωση…", () => loadPage(session.session_id, { ...view, size: n, page: 1 }))}
        />
      </main>

      <HistoryPanel
        history={history}
        onUndo={() => move("Αναίρεση…", api.undo)}
        onRedo={() => move("Επανάληψη…", api.redo)}
        onCheckout={(v) => move(`Μετάβαση στη v${v}…`, (id) => api.checkout(id, v))}
        onScript={showScript}
        onRecipe={downloadRecipe}
        onApplyRecipe={applyRecipe}
      />

      {dialog && (
        <ParamDialog
          op={dialog.op}
          columns={columns}
          attachments={session.attachments ?? []}
          onAttach={attach}
          initial={dialog.initial}
          onClose={() => setDialog(null)}
          onRun={(params, preview) => runOp(dialog.op, params, preview)}
        />
      )}
      {pythonMounted && (
        <PythonPanel
          key={session.session_id}
          sessionId={session.session_id}
          version={history.current_version}
          profile={profile}
          filename={source.filename}
          open={pythonOpen}
          onClose={() => setPythonOpen(false)}
          onSave={(payload) => api.saveBrowserVersion(session.session_id, payload)}
          onSaved={(data) => {
            applyState(data);
            setResult(data.result);
            setToast({ tone: "ok", text: `Νέα έκδοση v${data.history.current_version} από τον browser` });
            loadPage(session.session_id, { ...view, page: 1, sort: null }).catch(() => undefined);
          }}
        />
      )}
      {chatOpen && (
        <ChatPanel
          sessionId={session.session_id}
          status={assistant}
          chat={chat}
          busy={chatBusy}
          onSend={sendChat}
          onClear={clearChat}
          onClose={() => setChatOpen(false)}
        />
      )}
      {modal?.kind === "export" && (
        <ExportDialog
          viewActive={viewActive}
          viewSummary={`${page.total_rows} γραμμές × ${page.columns.length} στήλες`}
          onClose={() => setModal(null)}
          onExport={exportData}
        />
      )}
      {modal?.kind === "reload" && <ReloadDialog source={source} onClose={() => setModal(null)} onReload={reload} />}
      {modal?.kind === "script" && (
        <ScriptDialog
          script={modal.script}
          onClose={() => setModal(null)}
          onDownload={() => saveBlob(new Blob([modal.script], { type: "text/x-python" }), "pipeline.py")}
        />
      )}
      {toastView}
    </div>
  );
}
