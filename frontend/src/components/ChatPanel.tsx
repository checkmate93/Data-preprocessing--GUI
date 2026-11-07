import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import type { AssistantStatus, ChatMessage, ChatState, ChatStep } from "../types";
import { SectionView } from "./ResultPanel";

interface Props {
  sessionId: string;
  status: AssistantStatus | null;
  chat: ChatState;
  busy: boolean;
  onSend: (message: string, token: string) => Promise<void>;
  onClear: () => Promise<void>;
  onClose: () => void;
}

const EXAMPLES = [
  "Κάνε τη στήλη φύλο από female/male σε 1/0",
  "Ποιες στήλες έχουν outliers;",
  "Κάνε γραμμική παλινδρόμηση του ποσού με τα τεμάχια",
  "Δείξε μου τον μέσο όρο ποσού ανά πόλη σε γράφημα",
];

const TOKEN_KEY = "dataprep.assistantToken";
const compact = new Intl.NumberFormat("el-GR", { notation: "compact", maximumFractionDigits: 1 });

function readToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveToken(value: string) {
  try {
    sessionStorage.setItem(TOKEN_KEY, value);
  } catch {
    /* storage may be blocked; the token then lives only in memory */
  }
}

export function ChatPanel({ sessionId, status, chat, busy, onSend, onClear, onClose }: Props) {
  const [draft, setDraft] = useState("");
  const [token, setToken] = useState(readToken);
  const [confirmClear, setConfirmClear] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [chat.messages.length, pending]);

  async function send(text = draft) {
    const message = text.trim();
    if (!message || busy) return;
    setError(null);
    setPending(message);
    setDraft("");
    try {
      await onSend(message, token);
    } catch (e) {
      setError((e as Error).message);
      setDraft(message);
    } finally {
      setPending(null);
    }
  }

  const usage = chat.usage;
  const enabled = status?.enabled;
  return (
    <aside className="chat" aria-label="Βοηθός">
      <header className="chat-head">
        <div>
          <h2>Βοηθός</h2>
          <span className="muted small">{enabled ? `${status?.model}` : "δεν έχει ρυθμιστεί"}</span>
        </div>
        <div className="chat-head-actions">
          {confirmClear ? (
            <span className="confirm">
              Διαγραφή συνομιλίας;
              <button className="btn small danger" onClick={async () => { await onClear(); setConfirmClear(false); }}>Ναι</button>
              <button className="btn small" onClick={() => setConfirmClear(false)}>Όχι</button>
            </span>
          ) : (
            <button className="btn small" disabled={!chat.messages.length || busy} onClick={() => setConfirmClear(true)}
              title="Σβήνει τη συνομιλία· το μοντέλο ξεκινά από την αρχή. Οι εκδόσεις των δεδομένων μένουν.">
              Καθαρισμός
            </button>
          )}
          <button className="icon-btn" onClick={onClose} aria-label="Κλείσιμο">✕</button>
        </div>
      </header>

      <div className="chat-usage" title="Tokens που χρεώθηκαν σε αυτή τη συνομιλία. Ο «Καθαρισμός» τα μηδενίζει.">
        <span>Tokens: <b>{compact.format(usage.input_tokens)}</b> εισ. · <b>{compact.format(usage.output_tokens)}</b> εξ. · {usage.calls} κλήσεις</span>
        {usage.last_input_tokens > 0 && <span>τελευταίο context {compact.format(usage.last_input_tokens)}</span>}
      </div>

      <div className="chat-list" ref={list}>
        {!enabled && status && (
          <div className="alert warn">
            Ο βοηθός χρειάζεται κλειδί στον server: <code>ANTHROPIC_API_KEY</code> ή <code>OPENAI_API_KEY</code>
            (προαιρετικά <code>DATAPREP_LLM_MODEL</code>). Μετά κάνε restart.
          </div>
        )}
        {enabled && chat.messages.length === 0 && !pending && (
          <div className="chat-empty">
            <p>Ρώτα ό,τι θέλεις για τα δεδομένα ή ζήτα μια αλλαγή. Ο βοηθός γράφει και τρέχει κώδικα pandas· κάθε αλλαγή γίνεται νέα έκδοση με αναίρεση.</p>
            <div className="chat-examples">
              {EXAMPLES.map((example) => <button key={example} className="chip" onClick={() => send(example)}>{example}</button>)}
            </div>
            <p className="muted small">
              Στο μοντέλο στέλνονται ονόματα και τύποι στηλών, στατιστικά, έως 5 συχνές τιμές ανά στήλη κατηγοριών
              και τα αποτελέσματα του κώδικα που τρέχει — όχι ολόκληρο το αρχείο. Μην το χρησιμοποιείς για δεδομένα που δεν επιτρέπεται να φύγουν από τον οργανισμό.
            </p>
          </div>
        )}
        {chat.messages.map((message, i) => <Message key={i} message={message} sessionId={sessionId} />)}
        {pending && (
          <>
            <div className="msg user"><div className="bubble">{pending}</div></div>
            <div className="msg assistant"><div className="bubble thinking"><span className="spinner small" /> Σκέφτεται και τρέχει κώδικα…</div></div>
          </>
        )}
        {error && <div className="alert error">{error}</div>}
      </div>

      {enabled && status?.token_required && (
        <label className="chat-token">
          <span className="small">Κωδικός πρόσβασης</span>
          <input type="password" value={token} onChange={(e) => { setToken(e.target.value); saveToken(e.target.value); }} />
        </label>
      )}
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <textarea
          rows={2}
          value={draft}
          disabled={!enabled}
          placeholder={enabled ? "π.χ. «κάνε το female/male 1/0» — Enter για αποστολή" : "Ο βοηθός δεν είναι διαθέσιμος"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="btn primary" disabled={!enabled || busy || !draft.trim()}>Αποστολή</button>
      </form>
    </aside>
  );
}

function Message({ message, sessionId }: { message: ChatMessage; sessionId: string }) {
  if (message.role === "user")
    return <div className="msg user"><div className="bubble">{message.content}</div></div>;
  return (
    <div className="msg assistant">
      <div className={`bubble ${message.failed ? "failed" : ""}`}>
        <RichText text={message.content} />
        {!!message.steps?.length && (
          <div className="steps-list">
            {message.steps.map((step, i) => <Step key={i} step={step} sessionId={sessionId} />)}
          </div>
        )}
        {message.usage && (
          <div className="msg-usage">{compact.format(message.usage.input_tokens)} + {compact.format(message.usage.output_tokens)} tokens · {message.usage.calls} κλήσεις</div>
        )}
      </div>
    </div>
  );
}

function Step({ step, sessionId }: { step: ChatStep; sessionId: string }) {
  const [open, setOpen] = useState(false);
  const label =
    step.kind === "run_python"
      ? step.mode === "transform" ? "Αλλαγή με κώδικα" : "Ανάλυση με κώδικα"
      : `Κουμπί ${step.op}`;
  return (
    <div className={`step-item ${step.status}`}>
      <button className="step-toggle" onClick={() => setOpen((v) => !v)}>
        <span aria-hidden>{step.status === "ok" ? "✓" : "✗"}</span>
        <span className="step-title">{label}{step.description ? ` — ${step.description}` : ""}</span>
        {step.version !== null && <span className="chip version">v{step.version}</span>}
        <span className="muted">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="step-detail">
          {step.code && <pre className="code">{step.code}</pre>}
          {step.kind === "run_operation" && step.params && <pre className="code">{JSON.stringify(step.params, null, 2)}</pre>}
          {step.sections.filter((s) => s.type !== "text").map((section, i) => <SectionView key={i} section={section} sessionId={sessionId} />)}
          {step.output && (step.kind === "run_python" || step.status === "error" || !step.sections.some((s) => s.type !== "text")) && (
            <pre className="code output">{step.output}</pre>
          )}
        </div>
      )}
    </div>
  );
}

/** Minimal markdown: paragraphs, - lists, **bold**, `code`, ``` blocks. Everything stays text (no HTML injection). */
function RichText({ text }: { text: string }) {
  const blocks = text.split(/```(?:\w+)?\n?/);
  return (
    <div className="rich">
      {blocks.map((block, i) =>
        i % 2 === 1 ? (
          <pre key={i} className="code">{block.trimEnd()}</pre>
        ) : (
          <Fragment key={i}>
            {block.split(/\n{2,}/).filter((p) => p.trim()).map((paragraph, j) => {
              const lines = paragraph.split("\n");
              if (lines.every((l) => /^\s*[-*•]\s+/.test(l)))
                return <ul key={j}>{lines.map((l, k) => <li key={k}>{inline(l.replace(/^\s*[-*•]\s+/, ""))}</li>)}</ul>;
              return <p key={j}>{lines.map((l, k) => <Fragment key={k}>{k > 0 && <br />}{inline(l)}</Fragment>)}</p>;
            })}
          </Fragment>
        ),
      )}
    </div>
  );
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <b key={i}>{part.slice(2, -2)}</b>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return part;
  });
}
