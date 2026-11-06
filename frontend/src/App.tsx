import { useCallback, useEffect, useState } from "react";
import { api, download, saveBlob, type ReloadOptions } from "./api";
import { DataGrid } from "./components/DataGrid";
import { ExportDialog, ReloadDialog, ScriptDialog, type ExportOptions } from "./components/Dialogs";
import { HistoryPanel } from "./components/HistoryPanel";
import { ParamDialog, hasParams } from "./components/ParamDialog";
import { ProfileBar } from "./components/ProfileBar";
import { ResultPanel } from "./components/ResultPanel";
import { Sidebar } from "./components/Sidebar";
import { Upload } from "./components/Upload";
import { DELIMITER_LABEL, formatBytes } from "./format";
import type { Catalog, OpResult, Operation, Page, SessionState } from "./types";

interface View {
  page: number;
  size: number;
  sort: string | null;
  desc: boolean;
}

type Modal = { kind: "export" } | { kind: "reload" } | { kind: "script"; script: string } | null;

const FIRST_VIEW: View = { page: 1, size: 50, sort: null, desc: false };

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [view, setView] = useState<View>(FIRST_VIEW);
  const [result, setResult] = useState<OpResult | null>(null);
  const [dialog, setDialog] = useState<{ op: Operation; initial?: Record<string, unknown> } | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  useEffect(() => {
    api.catalog().then(setCatalog).catch((e: Error) => setToast({ tone: "error", text: e.message }));
  }, []);

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

  const loadPage = useCallback(async (id: string, next: View) => {
    setView(next);
    setPage(await api.data(id, next.page, next.size, next.sort, next.desc));
  }, []);

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
    });

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

  const exportData = (options: ExportOptions) =>
    act("Εξαγωγή…", async () => {
      if (!session) return;
      await download(api.exportUrl(session.session_id, options.format, options.encoding, options.delimiter), "export");
      setModal(null);
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
      <>
        <Upload busy={busy !== null} onFile={upload} />
        {toastView}
      </>
    );

  const { source, profile, history } = session;
  const columns = Object.entries(profile.columns);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">DataPrep Studio</div>
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
          <button className="btn" onClick={() => setModal({ kind: "reload" })}>Ξαναδιάβασε</button>
          <button className="btn" onClick={showScript}>Κώδικας</button>
          <button className="btn primary" onClick={() => setModal({ kind: "export" })}>Εξαγωγή</button>
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
      {modal?.kind === "export" && <ExportDialog onClose={() => setModal(null)} onExport={exportData} />}
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
