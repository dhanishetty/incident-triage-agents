import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { NodeRun } from "./FlowDiagram";
import { overview } from "./diagrams";
import type { LogLine, RunApi } from "./runApi";
import { scenarios } from "./scenarios";

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

type Phase = "idle" | "connecting" | "running" | "awaiting_approval" | "completed" | "failed";

const EDGE_TTL = 1800; // a link stays lit this long after the backend reports it, since parallel agents report in turn
const json = { "content-type": "application/json" };

// Starts a real run on the backend (demo data, scripted reasoner) and follows its server-sent events.
export function useLiveRun(focusIds: Set<string>): RunApi {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const scenario = scenarios.find((s) => s.id === scenarioId)!;
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

  const pick = (id: string) => {
    reset();
    setScenarioId(id);
  };

  const play = useCallback(async () => {
    if (busy) return;
    close();
    setEvents([]);
    setError(null);
    setPhase("connecting");
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: json,
        body: JSON.stringify({ title: `${scenario.label} (live demo)`, resource: "demo", labels: { demo_scenario: scenario.id } }),
      });
      if (!res.ok) throw new Error(`The backend answered ${res.status}.`);
      const { id } = await res.json();
      setRunId(id);

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
        } else {
          setPhase((p) => (p === "connecting" ? "running" : p));
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
    } catch (e) {
      setPhase("failed");
      setError(`Could not start a live run. ${e instanceof Error ? e.message : ""} Is the backend running?`.replace("  ", " "));
    }
  }, [busy, close, scenario]);

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
        .map((e) => ({
          time: new Date(e.time).toLocaleTimeString([], { hour12: false }),
          who: e.who ?? "",
          text: e.text ?? "",
        })),
    [events],
  );

  const last = derived.lastNode;
  const stepTitle = last?.node ? `${overview.nodes[last.node]?.title ?? last.node}: ${last.chip ?? last.status}` : undefined;
  const statusText =
    error ?? (phase === "connecting" ? "Starting a live run on the backend…" : phase === "failed" ? "The run failed." : undefined);

  return {
    mode: "live",
    scenarios,
    scenario,
    pick,
    view: events.length ? { nodes: derived.nodes, edges: derived.edges, focus: derived.focus, seq: derived.seq } : undefined,
    log,
    stepTitle,
    statusText,
    idx: events.length ? events.length - 1 : -1,
    playing: phase === "connecting" || phase === "running",
    waiting: phase === "awaiting_approval",
    finished: phase === "completed" || phase === "failed",
    speed: 1,
    setSpeed: () => {},
    play,
    pause: () => {},
    next: () => {},
    decide,
    reset,
  };
}
