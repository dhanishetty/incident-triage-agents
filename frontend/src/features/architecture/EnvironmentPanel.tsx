import clsx from "clsx";
import { Flame, HeartPulse } from "lucide-react";
import type { EnvironmentApi } from "./runApi";

const FAULTS = [
  { id: "bad-deploy", label: "Bad deploy", hint: "Releases v482, which crashes on orders without a coupon" },
  { id: "memory-leak", label: "Memory leak", hint: "Every order leaks memory until the container is killed" },
  { id: "db-pool", label: "Database pool", hint: "A config change shrinks the connection pool to 1" },
];

function Tile({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className={clsx("rounded-xl border px-3 py-2", bad ? "border-bad/50 bg-bad/10" : "border-border bg-surface")}>
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className={clsx("font-mono text-lg", bad && "text-bad")}>{value}</div>
    </div>
  );
}

// The shop service the agents investigate: its live numbers, and the buttons that really break it.
export function EnvironmentPanel({ env, error }: { env: EnvironmentApi; error?: string }) {
  const s = env.status;
  const errors = s?.error_rate_10s ?? 0;
  const p95 = s?.p95_ms_10s ?? 0;
  const lastAlert = s?.alerts.at(-1);

  return (
    <div className="space-y-3 rounded-xl border border-border bg-[#0b1120]/70 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">The shop service</h3>
        <span className="text-xs text-muted">
          A real service under steady load. Each button really breaks it, and its own alert rule starts a run within about 10 to 30 seconds.
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <Tile label="Version" value={s?.version ?? "…"} bad={s?.version === "v482"} />
        <Tile label="5xx rate" value={s ? `${(errors * 100).toFixed(1)}%` : "…"} bad={errors > 0.05} />
        <Tile label="p95 latency" value={s ? `${p95.toFixed(0)} ms` : "…"} bad={p95 > 200} />
        <Tile label="Memory" value={s?.latest ? `${s.latest.mem_mb.toFixed(0)} MB` : "…"} />
        <Tile label="Restarts" value={s?.latest ? String(s.latest.restarts) : "…"} bad={(s?.latest?.restarts ?? 0) > 0} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {FAULTS.map((f) => (
          <button
            key={f.id}
            onClick={() => env.breakIt(f.id)}
            disabled={env.acting || !s || s.faults.includes(f.id)}
            title={f.hint}
            className="inline-flex items-center gap-1.5 rounded-lg border border-bad/50 bg-bad/10 px-3 py-1.5 text-sm text-white transition hover:bg-bad/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Flame size={14} className="text-bad" /> Break: {f.label}
          </button>
        ))}
        <button
          onClick={env.heal}
          disabled={env.acting || !s}
          className="inline-flex items-center gap-1.5 rounded-lg border border-ok/50 bg-ok/10 px-3 py-1.5 text-sm text-white transition hover:bg-ok/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <HeartPulse size={14} className="text-ok" /> Reset to healthy
        </button>
        {s && s.faults.length > 0 && <span className="text-xs text-warn">Broken: {s.faults.join(", ")}</span>}
      </div>

      <div className="text-xs text-muted">
        {error
          ? error
          : lastAlert
            ? `Last alert: ${lastAlert.title}${lastAlert.delivered ? " (sent to the triage backend)" : " (could not be delivered)"}`
            : "No alert has fired yet."}
      </div>
    </div>
  );
}
