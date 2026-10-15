import { useEffect, useRef } from "react";
import clsx from "clsx";
import { Check, Pause, Play, RotateCcw, SkipForward, X } from "lucide-react";
import type { LogLine, RunApi } from "./runApi";

export type Mode = RunApi["mode"];

const whoColor = (who: string) => (/agent|supervisor|executor/i.test(who) ? "#818cf8" : /gate/i.test(who) ? "#fbbf24" : "#94a3b8");

const btn =
  "inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-white transition hover:border-azure/60 disabled:cursor-not-allowed disabled:opacity-40";

// Sticks to the top of the diagram card so the controls stay in reach while the page follows the action.
export function RunBar({ run, mode, onMode }: { run: RunApi; mode: Mode; onMode: (m: Mode) => void }) {
  const { scenario, scenarios, idx, playing, waiting, finished, speed } = run;
  const live = run.mode === "live";
  const idle = idx < 0;
  const last = run.log[run.log.length - 1];

  return (
    <div className="sticky top-2 z-30 space-y-2 rounded-xl border border-border bg-[#0b1120]/95 p-3 shadow-lg backdrop-blur">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-border p-0.5 text-xs" role="group" aria-label="Where the run comes from">
          {(["simulated", "live"] as const).map((m) => (
            <button
              key={m}
              onClick={() => onMode(m)}
              aria-pressed={mode === m}
              className={clsx("rounded-md px-2.5 py-1 transition", mode === m ? "bg-azure/20 text-white" : "text-muted hover:text-white")}
            >
              {m === "simulated" ? "Simulated" : "Live backend"}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-xs text-muted">
          Incident
          <select
            value={scenario.id}
            onChange={(e) => run.pick(e.target.value)}
            className="rounded-lg border border-border bg-surface px-2 py-1.5 text-sm text-white [color-scheme:dark]"
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>

        {!live && playing && !waiting ? (
          <button onClick={run.pause} className={btn}>
            <Pause size={14} /> Pause
          </button>
        ) : (
          <button onClick={run.play} disabled={waiting || (live && playing)} className={clsx(btn, "border-azure/60 bg-azure/20")}>
            <Play size={14} /> {finished ? "Replay" : live ? (playing ? "Running…" : "Start live run") : idle ? "Play a run" : "Resume"}
          </button>
        )}
        {!live && (
          <button onClick={run.next} disabled={waiting || finished} className={btn} aria-label="Next step">
            <SkipForward size={14} /> Step
          </button>
        )}
        <button onClick={run.reset} disabled={idle && !run.statusText} className={btn} aria-label="Restart">
          <RotateCcw size={14} /> {live ? "Reset" : "Restart"}
        </button>

        {!live && (
          <div className="ml-auto flex items-center gap-1 text-xs text-muted" role="group" aria-label="Speed">
            Speed
            {[0.5, 1, 2].map((s) => (
              <button
                key={s}
                onClick={() => run.setSpeed(s)}
                aria-pressed={speed === s}
                className={clsx("rounded-md px-2 py-1 transition", speed === s ? "bg-azure/20 text-white" : "hover:text-white")}
              >
                {s}×
              </button>
            ))}
          </div>
        )}
      </div>

      {waiting ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warn/50 bg-warn/10 px-3 py-2">
          <span className="text-sm text-warn">The Approval gate is waiting for you. The Remediation agent proposes a fix. Nothing runs until you decide.</span>
          <span className="ml-auto flex gap-2">
            <button onClick={() => run.decide("approve")} className={clsx(btn, "border-ok/60 bg-ok/15")}>
              <Check size={14} /> Approve fix
            </button>
            <button onClick={() => run.decide("reject")} className={clsx(btn, "border-bad/60 bg-bad/10")}>
              <X size={14} /> Reject
            </button>
          </span>
        </div>
      ) : (
        <div className="space-y-0.5 text-sm" aria-live="polite">
          <div className={run.statusText?.startsWith("Could not") || run.statusText?.startsWith("Lost") ? "text-bad" : "text-white"}>
            {run.statusText ??
              (idle
                ? live
                  ? "Press Start live run. The real agent graph runs on the backend with demo data."
                  : "Press Play to replay a simulated incident through the agents."
                : finished
                  ? "Run complete. Press Replay to watch it again."
                  : live
                    ? `Live: ${run.stepTitle ?? "working"}`
                    : `Step ${idx + 1}: ${run.stepTitle ?? ""}`)}
          </div>
          {last && (
            <div className="truncate font-mono text-xs text-muted">
              {last.time} <span style={{ color: whoColor(last.who) }}>{last.who}</span> {last.text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function EventLog({ lines }: { lines: LogLine[] }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  return (
    <div className="glass space-y-3 p-6">
      <h2 className="text-lg font-semibold">Event log</h2>
      <p className="text-sm text-muted">What each agent says as the run unfolds, in the same shape the backend streams.</p>
      <div ref={box} className="max-h-72 overflow-y-auto rounded-xl border border-border bg-[#070b14] p-3 font-mono text-xs leading-relaxed">
        {lines.length === 0 ? (
          <div className="text-muted">No events yet. Start a run above.</div>
        ) : (
          lines.map((l, i) => (
            <div key={i} className="flex gap-3">
              <span className="shrink-0 text-muted">{l.time}</span>
              <span className="w-40 shrink-0 font-semibold" style={{ color: whoColor(l.who) }}>
                {l.who}
              </span>
              <span className="min-w-0 text-[#cbd5f5]">{l.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
