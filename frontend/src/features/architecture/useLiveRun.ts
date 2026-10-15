import { useCallback, useState } from "react";
import type { RunApi } from "./runApi";
import { scenarios } from "./scenarios";
import { json, useRunStream } from "./useRunStream";

// Starts a real run on the backend (demo data, scripted reasoner) when you press the button, and follows it.
export function useLiveRun(focusIds: Set<string>): RunApi {
  const stream = useRunStream(focusIds);
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const scenario = scenarios.find((s) => s.id === scenarioId)!;
  const { busy, connecting, attach, fail, reset } = stream;

  const play = useCallback(async () => {
    if (busy) return;
    connecting();
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: json,
        body: JSON.stringify({ title: `${scenario.label} (live demo)`, resource: "demo", labels: { demo_scenario: scenario.id } }),
      });
      if (!res.ok) throw new Error(`The backend answered ${res.status}.`);
      attach((await res.json()).id);
    } catch (e) {
      fail(`Could not start a live run. ${e instanceof Error ? e.message : ""} Is the backend running?`.replace("  ", " "));
    }
  }, [busy, connecting, attach, fail, scenario]);

  return {
    mode: "live",
    scenarios,
    scenario,
    pick: (id: string) => {
      reset();
      setScenarioId(id);
    },
    view: stream.view,
    log: stream.log,
    stepTitle: stream.stepTitle,
    statusText: stream.error ?? (stream.phase === "connecting" ? "Starting a live run on the backend…" : stream.phase === "failed" ? "The run failed." : undefined),
    idx: stream.idx,
    playing: stream.phase === "connecting" || stream.phase === "running",
    waiting: stream.phase === "awaiting_approval",
    finished: stream.phase === "completed" || stream.phase === "failed",
    speed: 1,
    setSpeed: () => {},
    play,
    pause: () => {},
    next: () => {},
    decide: stream.decide,
    reset,
  };
}
