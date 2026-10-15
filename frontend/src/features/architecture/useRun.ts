import { useCallback, useEffect, useMemo, useState } from "react";
import type { NodeRun, RunView } from "./FlowDiagram";
import type { LogLine, RunApi } from "./runApi";
import { scenarios, type Scenario, type Step } from "./scenarios";

const START = 14 * 3600 + 2 * 60 + 11; // the simulated clock starts at 14:02:11
const clock = (s: number) => [Math.floor(s / 3600) % 24, Math.floor(s / 60) % 60, s % 60].map((n) => String(n).padStart(2, "0")).join(":");

// Drives a replay. Steps advance on a timer, or one at a time; the approval step waits for a person.
// Decisions append the approved or rejected branch to the plan, so the run is one list of steps.
export function useRun(focusKinds: Set<string>): RunApi {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const scenario: Scenario = scenarios.find((s) => s.id === scenarioId)!;
  const [plan, setPlan] = useState<Step[]>(scenario.pre);
  const [idx, setIdx] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);

  const step: Step | undefined = plan[idx];
  const waiting = !!step?.approval && !decision;
  const finished = idx >= 0 && idx === plan.length - 1 && !waiting;

  const reset = useCallback((s: Scenario = scenario) => {
    setPlan(s.pre);
    setIdx(-1);
    setPlaying(false);
    setDecision(null);
  }, [scenario]);

  const pick = (id: string) => {
    setScenarioId(id);
    reset(scenarios.find((s) => s.id === id)!);
  };

  useEffect(() => {
    if (!playing || waiting || idx >= plan.length - 1) return;
    const t = window.setTimeout(() => setIdx((i) => i + 1), (idx < 0 ? 0 : (step?.ms ?? 2200)) / speed);
    return () => window.clearTimeout(t);
  }, [playing, waiting, idx, plan.length, step, speed]);

  useEffect(() => {
    if (finished) setPlaying(false);
  }, [finished]);

  const play = () => {
    if (finished) {
      reset();
      setPlaying(true);
      return;
    }
    setPlaying(true);
    if (idx < 0) setIdx(0);
  };
  const pause = () => setPlaying(false);
  const next = () => {
    setPlaying(false);
    if (!waiting && idx < plan.length - 1) setIdx((i) => i + 1);
  };
  const decide = (d: "approve" | "reject") => {
    setDecision(d);
    setPlan((p) => [...p, ...(d === "approve" ? scenario.approved : scenario.rejected)]);
    setIdx((i) => i + 1);
    setPlaying(true);
  };

  const view: RunView | undefined = useMemo(() => {
    if (idx < 0) return undefined;
    const nodes: Record<string, NodeRun> = {};
    for (let i = 0; i <= idx; i++) Object.assign(nodes, plan[i].nodes);
    const current = plan[idx].nodes;
    const live = Object.keys(current).filter((id) => current[id].status === "working" || current[id].status === "waiting");
    return {
      nodes,
      edges: plan[idx].edges,
      focus: live.find((id) => focusKinds.has(id)) ?? live[0],
      seq: idx,
    };
  }, [idx, plan, focusKinds]);

  const log: LogLine[] = useMemo(() => {
    const out: LogLine[] = [];
    let t = START;
    for (let i = 0; i <= idx; i++) {
      const s = plan[i];
      const dt = s.dt ?? 3;
      s.log.forEach((l, k) => out.push({ time: clock(t + Math.min(k, dt - 1)), who: l.who, text: l.text }));
      t += dt;
    }
    return out;
  }, [idx, plan]);

  return {
    mode: "simulated",
    scenarios, scenario, pick, view, log, stepTitle: step?.title, idx, playing, waiting, finished, speed, setSpeed, play, pause, next, decide,
    reset: () => reset(),
  };
}
