import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { NodeRun, RunView } from "./FlowDiagram";
import { overview } from "./diagrams";
import type { LogLine } from "./runApi";

// The backend's event shape (backend/src/triage/events.py), plus when it arrived.
interface LiveEvent {
  seq: number;
  time: string;
  kind: "node" | "edges" | "log" | "run";
  node?: string | null;
  status?: string | null;
  chip?: string | null;
  edges: string[];
  who?: string | null;
  text?: string | null;
  at: number;
}

export type Phase = "idle" | "connecting" | "running" | "awaiting_approval" | "completed" | "failed";

const EDGE_TTL = 1800; // a link stays lit this long after the backend reports it, since parallel agents report in turn
export const json = { "content-type": "application/json" };

// Follows one run on the backend through its server-sent events, and turns them into what the diagram and log show.
// Who starts the run (a button, or an alert from the demo environment) is up to the caller: it calls attach(id).
export function useRunStream(focusIds: Set<string>) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const source = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    source.current?.close();
    source.current = null;
  }, []);
  useEffect(() => close, [close]);

  const busy = phase === "connecting" || phase === "running" || phase === "awaiting_approval";
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => setNow(Date.now()), 300); // lets lit links fade
    return () => window.clearInterval(t);
  }, [busy]);

  const reset = useCallback(() => {
    close();
    setEvents([]);
    setPhase("idle");
    setRunId(null);
    setError(null);
  }, [close]);

  const attach = useCallback(
    (id: string) => {
      close();
      setEvents([]);
      setError(null);
      setRunId(id);
      setPhase("running");
      const es = new EventSource(`/api/runs/${id}/events`);
      source.current = es;
      const onEvent = (e: MessageEvent) => {
        const ev: LiveEvent = { ...JSON.parse(e.data), at: Date.now() };
        setEvents((prev) => [...prev, ev]);
        if (ev.kind === "run") {
          const next = ev.status as Phase;
          setPhase(next);
          if (next === "completed" || next === "failed") {
            es.close(); // otherwise the browser reconnects and replays the whole run
            if (source.current === es) source.current = null;
          }
        }
      };
      for (const kind of ["node", "edges", "log", "run"]) es.addEventListener(kind, onEvent as EventListener);
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) return;
        es.close();
        source.current = null;
        setPhase((p) => (p === "completed" ? p : "failed"));
        setError("Lost the connection to the backend.");
      };
    },
    [close],
  );

  const connecting = useCallback(() => {
    close();
    setEvents([]);
    setError(null);
    setPhase("connecting");
  }, [close]);

  const fail = useCallback((message: string) => {
    setPhase("failed");
    setError(message);
  }, []);

  const decide = useCallback(
    async (d: "approve" | "reject") => {
      if (!runId) return;
      setPhase("running");
      try {
        const res = await fetch(`/api/runs/${runId}/approval`, { method: "POST", headers: json, body: JSON.stringify({ decision: d }) });
        if (!res.ok) throw new Error(String(res.status));
      } catch {
        setError("Could not send your decision.");
        setPhase("awaiting_approval");
      }
    },
    [runId],
  );

  const derived = useMemo(() => {
    const nodes: Record<string, NodeRun> = {};
    let focus: string | undefined;
    let seq = 0;
    let lastNode: LiveEvent | undefined;
    let lastEdges: string[] = [];
    const lit = new Set<string>();
    for (const e of events) {
      if (e.kind === "node" && e.node) {
        nodes[e.node] = { status: e.status as NodeRun["status"], chip: e.chip ?? undefined };
        lastNode = e;
        // scroll to the agent that just woke up, once per change of agent
        if ((e.status === "working" || e.status === "waiting") && focusIds.has(e.node) && e.node !== focus) {
          focus = e.node;
          seq++;
        }
      } else if (e.kind === "edges") {
        lastEdges = e.edges;
        if (now - e.at < EDGE_TTL) e.edges.forEach((k) => lit.add(k));
      }
    }
    if (phase === "awaiting_approval") lastEdges.forEach((k) => lit.add(k)); // keep the link into the gate lit while it waits
    return { nodes, focus, seq, lastNode, edges: [...lit] };
  }, [events, now, phase, focusIds]);

  const log: LogLine[] = useMemo(
    () =>
      events
        .filter((e) => e.kind === "log")
        .map((e) => ({ time: new Date(e.time).toLocaleTimeString([], { hour12: false }), who: e.who ?? "", text: e.text ?? "" })),
    [events],
  );

  const last = derived.lastNode;
  return {
    phase,
    error,
    busy,
    runId,
    log,
    attach,
    reset,
    decide,
    connecting,
    fail,
    view: events.length ? ({ nodes: derived.nodes, edges: derived.edges, focus: derived.focus, seq: derived.seq } satisfies RunView) : undefined,
    stepTitle: last?.node ? `${overview.nodes[last.node]?.title ?? last.node}: ${last.chip ?? last.status}` : undefined,
    idx: events.length ? events.length - 1 : -1,
  };
}
