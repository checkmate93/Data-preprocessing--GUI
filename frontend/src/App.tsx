/**
 * Tab manager: one tab per dataset. Every Workspace stays mounted (inactive ones are hidden with CSS),
 * so each tab keeps its own data, grid position, results, chat and Python variables while you switch.
 * Closing a tab deletes its server session.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Modal } from "./components/Modal";
import { Workspace, type TabMeta } from "./components/Workspace";
import type { AssistantStatus, Catalog } from "./types";

interface Tab {
  id: string;
  meta: TabMeta;
  restore?: { sessionId: string; title: string }; // remembered from an earlier visit
}

type Confirm = { kind: "one"; id: string } | { kind: "all" } | null;

const MAX_TABS = 10;
const STORAGE_KEY = "dataprep.tabs.v1";
let counter = 0;

function newTab(): Tab {
  counter += 1;
  return { id: `tab-${Date.now()}-${counter}`, meta: { title: "Νέο αρχείο", sessionId: null, dirty: false, busy: false } };
}

interface StoredTabs {
  tabs: { id: string; sessionId: string | null; title: string }[];
  activeId: string;
}

/** Only ids and titles are stored (a few bytes); the data stays on the server. */
function readStoredTabs(): { tabs: Tab[]; activeId: string } | null {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as StoredTabs | null;
    if (!stored?.tabs?.length) return null;
    const tabs = stored.tabs.slice(0, MAX_TABS).map((t): Tab => ({
      id: t.id,
      meta: { title: t.title, sessionId: t.sessionId, dirty: !!t.sessionId, busy: false },
      restore: t.sessionId ? { sessionId: t.sessionId, title: t.title } : undefined,
    }));
    const activeId = tabs.some((t) => t.id === stored.activeId) ? stored.activeId : tabs[0].id;
    return { tabs, activeId };
  } catch {
    return null; // storage blocked or corrupt: start with one empty tab
  }
}

function storeTabs(tabs: Tab[], activeId: string) {
  const data: StoredTabs = { tabs: tabs.map((t) => ({ id: t.id, sessionId: t.meta.sessionId, title: t.meta.title })), activeId };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    /* storage blocked: tabs just won't survive a refresh */
  }
}

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [assistant, setAssistant] = useState<AssistantStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [initial] = useState(() => readStoredTabs() ?? (() => { const t = newTab(); return { tabs: [t], activeId: t.id }; })());
  const [tabs, setTabs] = useState<Tab[]>(initial.tabs);
  const [activeId, setActiveId] = useState(initial.activeId);

  useEffect(() => storeTabs(tabs, activeId), [tabs, activeId]);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    api.catalog().then(setCatalog).catch((e: Error) => setLoadError(e.message));
    api.assistantStatus().then(setAssistant).catch(() => setAssistant(null));
  }, []);

  // One stable callback per tab id, so Workspace's effect does not re-fire on every render.
  const metaHandlers = useRef(new Map<string, (meta: TabMeta) => void>());
  const onMetaFor = useCallback((id: string) => {
    let handler = metaHandlers.current.get(id);
    if (!handler) {
      handler = (meta: TabMeta) =>
        setTabs((all) => all.map((t) => (t.id === id && JSON.stringify(t.meta) !== JSON.stringify(meta) ? { ...t, meta } : t)));
      metaHandlers.current.set(id, handler);
    }
    return handler;
  }, []);

  function addTab() {
    if (tabs.length >= MAX_TABS) return;
    const tab = newTab();
    setTabs((all) => [...all, tab]);
    setActiveId(tab.id);
  }

  /** Remove tabs, delete their server sessions, keep at least one (empty) tab. */
  function closeTabs(ids: string[]) {
    const closing = tabs.filter((t) => ids.includes(t.id));
    for (const tab of closing) {
      if (tab.meta.sessionId) api.deleteSession(tab.meta.sessionId).catch(() => undefined);
      metaHandlers.current.delete(tab.id);
    }
    const remaining = tabs.filter((t) => !ids.includes(t.id));
    if (remaining.length === 0) {
      const fresh = newTab();
      setTabs([fresh]);
      setActiveId(fresh.id);
      return;
    }
    if (ids.includes(activeId)) {
      const index = tabs.findIndex((t) => t.id === activeId);
      const next = tabs.slice(index + 1).find((t) => !ids.includes(t.id)) ?? remaining[remaining.length - 1];
      setActiveId(next.id);
    }
    setTabs(remaining);
  }

  function requestClose(id: string) {
    const tab = tabs.find((t) => t.id === id);
    if (tab?.meta.dirty || tab?.meta.busy) setConfirm({ kind: "one", id });
    else closeTabs([id]);
  }

  function requestCloseAll() {
    if (tabs.some((t) => t.meta.sessionId)) setConfirm({ kind: "all" });
    else closeTabs(tabs.map((t) => t.id));
  }

  function onTabKey(event: React.KeyboardEvent, index: number) {
    const move = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (move) {
      const next = tabs[(index + move + tabs.length) % tabs.length];
      setActiveId(next.id);
      tabRefs.current.get(next.id)?.focus();
    } else if (event.key === "Delete") {
      requestClose(tabs[index].id);
    }
  }

  const confirmTab = confirm?.kind === "one" ? tabs.find((t) => t.id === confirm.id) : null;
  const withData = tabs.filter((t) => t.meta.sessionId).length;

  return (
    <div className="shell">
      <nav className="tabbar">
        <div className="brand">DataPrep Studio</div>
        <div className="tabs" role="tablist" aria-label="Αρχεία">
          {tabs.map((tab, index) => (
            <div key={tab.id} className={`tab ${tab.id === activeId ? "active" : ""}`}>
              <button
                ref={(el) => {
                  if (el) tabRefs.current.set(tab.id, el);
                  else tabRefs.current.delete(tab.id);
                }}
                role="tab"
                aria-selected={tab.id === activeId}
                tabIndex={tab.id === activeId ? 0 : -1}
                className="tab-title"
                title={tab.meta.title}
                onClick={() => setActiveId(tab.id)}
                onAuxClick={(e) => e.button === 1 && requestClose(tab.id)}
                onKeyDown={(e) => onTabKey(e, index)}
              >
                {tab.meta.busy ? <span className="spinner small" /> : tab.meta.dirty ? <span className="dirty-dot" aria-label="έχει αλλαγές" /> : null}
                <span>{tab.meta.title}</span>
              </button>
              <button className="tab-close" onClick={() => requestClose(tab.id)} aria-label={`Κλείσιμο ${tab.meta.title}`} title="Κλείσιμο (Delete)">
                ✕
              </button>
            </div>
          ))}
          <button className="tab-add" onClick={addTab} disabled={tabs.length >= MAX_TABS}
            title={tabs.length >= MAX_TABS ? `Έως ${MAX_TABS} καρτέλες` : "Νέα καρτέλα"} aria-label="Νέα καρτέλα">
            +
          </button>
        </div>
        <button className="btn small ghost close-all" onClick={requestCloseAll} disabled={tabs.length === 1 && !tabs[0].meta.sessionId}>
          Κλείσιμο όλων
        </button>
      </nav>

      {loadError && <div className="alert error">Ο server δεν απαντά: {loadError}</div>}
      {tabs.map((tab) => (
        <Workspace key={tab.id} catalog={catalog} assistant={assistant} active={tab.id === activeId} onMeta={onMetaFor(tab.id)} restore={tab.restore} />
      ))}

      {confirm && (
        <Modal
          title={confirm.kind === "all" ? "Κλείσιμο όλων των καρτελών" : "Κλείσιμο καρτέλας"}
          onClose={() => setConfirm(null)}
          footer={
            <>
              <button className="btn ghost" onClick={() => setConfirm(null)}>Άκυρο</button>
              <button
                className="btn danger"
                autoFocus
                onClick={() => {
                  closeTabs(confirm.kind === "all" ? tabs.map((t) => t.id) : [confirm.id]);
                  setConfirm(null);
                }}
              >
                {confirm.kind === "all" ? `Κλείσιμο ${tabs.length}` : "Κλείσιμο"}
              </button>
            </>
          }
        >
          {confirm.kind === "all" ? (
            <p>Θα κλείσουν {tabs.length} καρτέλες ({withData} με δεδομένα). Οι εκδόσεις, οι συνομιλίες και ό,τι υπάρχει στο Python θα διαγραφούν και δεν επανέρχονται. Κατέβασε πρώτα ό,τι χρειάζεσαι.</p>
          ) : (
            <p>Η καρτέλα «{confirmTab?.meta.title}» έχει αλλαγές. Οι εκδόσεις, η συνομιλία και ό,τι υπάρχει στο Python θα διαγραφούν και δεν επανέρχονται.</p>
          )}
        </Modal>
      )}
    </div>
  );
}
