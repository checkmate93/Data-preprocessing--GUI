/**
 * Main-thread handle to the Pyodide worker: promises for load/run/csv, a status callback,
 * and stop() = terminate the worker (the only reliable way to interrupt a running loop
 * without SharedArrayBuffer / cross-origin isolation headers).
 */
import type { ExportedFrame, LoadHints, RunResult, WorkerIn, WorkerOut } from "./protocol";

type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void };

export class PythonRuntime {
  private worker: Worker | null = null;
  private ready: Promise<string> | null = null;
  private pending = new Map<number, Pending>();
  private nextId = 1;

  constructor(private onStatus: (text: string) => void) {}

  start(): Promise<string> {
    if (this.ready) return this.ready;
    const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    this.worker = worker;
    this.ready = new Promise<string>((resolve, reject) => {
      worker.onmessage = (event: MessageEvent<WorkerOut>) => {
        const message = event.data;
        if (message.type === "status") this.onStatus(message.text);
        else if (message.type === "ready") resolve(message.version);
        else if (message.type === "error" && message.id === undefined) reject(new Error(message.error));
        else this.settle(message);
      };
      worker.onerror = (event) => reject(new Error(event.message || "Το Python δεν φορτώθηκε (δίκτυο ή CDN)."));
    });
    this.send({ type: "init" });
    return this.ready;
  }

  async load(csv: string, hints: LoadHints): Promise<[number, number]> {
    await this.start();
    return (await this.request({ type: "load", id: 0, csv, hints })) as [number, number];
  }

  async run(code: string): Promise<RunResult> {
    await this.start();
    return (await this.request({ type: "run", id: 0, code })) as RunResult;
  }

  async csv(name: string): Promise<string> {
    await this.start();
    return (await this.request({ type: "csv", id: 0, name })) as string;
  }

  async exportFrame(name: string): Promise<ExportedFrame> {
    await this.start();
    return (await this.request({ type: "export", id: 0, name })) as ExportedFrame;
  }

  /** Kill the worker (stops infinite loops). Variables are lost; the next call starts a fresh one. */
  stop() {
    this.worker?.terminate();
    this.worker = null;
    this.ready = null;
    for (const p of this.pending.values()) p.reject(new Error("Η εκτέλεση διακόπηκε."));
    this.pending.clear();
  }

  private request(message: Exclude<WorkerIn, { type: "init" }>) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.send({ ...message, id });
    });
  }

  private send(message: WorkerIn) {
    this.worker?.postMessage(message);
  }

  private settle(message: WorkerOut) {
    if (!("id" in message) || message.id === undefined) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    if (message.type === "error") pending.reject(new Error(message.error));
    else if (message.type === "loaded") pending.resolve(message.shape);
    else if (message.type === "csv") pending.resolve(message.csv);
    else if (message.type === "export") {
      const { type: _t, id: _i, ...frame } = message;
      pending.resolve(frame);
    }
    else if (message.type === "result") {
      const { type: _t, id: _i, ...result } = message;
      pending.resolve(result);
    }
  }
}
