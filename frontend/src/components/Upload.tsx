import { useRef, useState } from "react";

const ACCEPT = ".csv,.tsv,.txt,.dat,.xlsx,.xlsm,.json,.jsonl,.ndjson,.parquet,.feather";

export function Upload({ busy, onFile }: { busy: boolean; onFile: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  async function loadSample() {
    const response = await fetch("/samples/pelates_demo.csv");
    onFile(new File([await response.blob()], "πελάτες_demo.csv", { type: "text/csv" }));
  }

  return (
    <main className="upload-screen">
      <h1>DataPrep Studio</h1>
      <p className="muted">Ανέβασε ένα αρχείο, δες τι περιέχει και καθάρισέ το με κουμπιά. Κάθε βήμα αναιρείται και γίνεται κώδικας pandas.</p>
      <div
        className={`dropzone ${over ? "over" : ""} ${busy ? "busy" : ""}`}
        onClick={() => !busy && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const file = e.dataTransfer.files[0];
          if (file && !busy) onFile(file);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      >
        {busy ? (
          <><div className="spinner" /><p>Ανάγνωση αρχείου…</p></>
        ) : (
          <>
            <p className="drop-title">Σύρε το αρχείο εδώ ή κάνε κλικ</p>
            <p className="muted small">CSV · TSV · TXT · Excel (.xlsx) · JSON · JSONL · Parquet · Feather — έως 200 MB</p>
            <p className="muted small">Encoding (UTF-8, Windows-1253, ISO-8859-7…), διαχωριστικό και δεκαδικό αναγνωρίζονται αυτόματα.</p>
          </>
        )}
      </div>
      <button className="link sample-link" disabled={busy} onClick={loadSample}>
        ή δοκίμασε με ένα δείγμα (πελάτες σε Windows-1253, με κενά, διπλότυπα και «N/A»)
      </button>
      <div hidden>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
            e.target.value = "";
          }}
        />
      </div>
    </main>
  );
}
