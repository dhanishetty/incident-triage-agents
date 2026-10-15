import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { Bot, Check, Hourglass, Loader2, X, type LucideIcon } from "lucide-react";

export type Kind = "external" | "entry" | "agent" | "connector" | "shared" | "human";

export const KINDS: Record<Kind, { color: string; label: string }> = {
  external: { color: "#94a3b8", label: "People and Azure services" },
  entry: { color: "#38bdf8", label: "Entry (nginx, API)" },
  agent: { color: "#818cf8", label: "Agents" },
  connector: { color: "#34d399", label: "Connectors" },
  shared: { color: "#fb923c", label: "Shared services" },
  human: { color: "#fbbf24", label: "Human in the loop" },
};

export interface NodeDef {
  id: string;
  title: string;
  sub: string;
  icon: LucideIcon;
  kind: Kind;
}

export const node = (id: string, title: string, sub: string, icon: LucideIcon, kind: Kind): NodeDef => ({
  id, title, sub, icon, kind,
});

export interface Lane {
  title?: string;
  hint?: string;
  ids: string[];
  at?: number[]; // explicit grid column for each card, to leave gaps
  cols?: number; // default: one column per card, at least three
  group?: string; // consecutive lanes with the same group are drawn inside one dashed zone
}

export interface Edge {
  from: string;
  to: string;
  label?: string;
  fa?: number; // where the link leaves the first card, in pixels from its left edge (default: the middle)
  fb?: number; // where it enters the second card, same units
}

export interface Diagram {
  nodes: Record<string, NodeDef>;
  lanes: Lane[];
  edges: Edge[];
  groups?: Record<string, string>; // group id -> label shown on the zone
  note?: string;
}

// A replay in progress: which nodes have a status, which links are carrying a message right now,
// and a counter that changes on every step so the view can scroll to the new action.
export type RunStatus = "working" | "done" | "waiting" | "failed";
export interface NodeRun {
  status: RunStatus;
  chip?: string;
}
export interface RunView {
  nodes: Record<string, NodeRun>;
  edges: string[]; // "from-to" keys of the links that are active in this step
  focus?: string;
  seq: number;
}

const STATUS_COLOR: Record<RunStatus, string> = { working: "", done: "#34d399", waiting: "#fbbf24", failed: "#f87171" };

interface Path {
  key: string;
  d: string;
  from: string;
  to: string;
  color: string;
  lx: number;
  ly: number;
  label?: string;
}

const colorOf = (n: NodeDef) => KINDS[n.kind].color;

function NodeCard({
  def,
  column,
  active,
  dim,
  state,
  setRef,
  onHover,
}: {
  def: NodeDef;
  column?: string;
  active: boolean;
  dim: boolean;
  state?: NodeRun;
  setRef: (id: string, el: HTMLDivElement | null) => void;
  onHover: (id: string | null) => void;
}) {
  const color = colorOf(def);
  const Icon = def.icon;
  const agent = def.kind === "agent";
  return (
    <div
      ref={(el) => setRef(def.id, el)}
      onMouseEnter={() => onHover(def.id)}
      onMouseLeave={() => onHover(null)}
      className={`relative flex min-w-0 cursor-default items-center rounded-2xl backdrop-blur transition-[opacity,box-shadow,border-color] duration-200 ${
        agent ? "gap-2.5 border-2 px-2.5 py-4" : "gap-2 border px-2 py-3"
      } ${state?.status === "working" || state?.status === "waiting" ? "run-working" : ""}`}
      style={{
        ...({ "--c": state?.status === "waiting" ? "#fbbf24" : color } as CSSProperties),
        gridColumn: column,
        borderColor: active ? color : agent ? `${color}99` : `${color}55`,
        background: agent ? `linear-gradient(135deg, ${color}33, #0f1626cc)` : `linear-gradient(135deg, ${color}1f, #0f162699)`,
        boxShadow: active
          ? `0 0 0 1px ${color}, 0 8px 30px ${color}${agent ? "55" : "40"}`
          : agent
            ? `0 0 18px ${color}26, 0 2px 12px #00000040`
            : "0 2px 12px #00000040",
        opacity: dim ? 0.3 : 1,
      }}
    >
      {state?.chip && (
        <span
          className="absolute -top-2.5 right-2 z-20 flex items-center gap-1 whitespace-nowrap rounded-full border bg-[#0b1120] px-2 py-0.5 text-[10px] font-medium"
          style={{ borderColor: STATUS_COLOR[state.status] || color, color: STATUS_COLOR[state.status] || color }}
        >
          {state.status === "working" && <Loader2 size={10} className="run-spin" />}
          {state.status === "done" && <Check size={10} strokeWidth={3} />}
          {state.status === "waiting" && <Hourglass size={10} />}
          {state.status === "failed" && <X size={10} strokeWidth={3} />}
          {state.chip}
        </span>
      )}
      {agent ? (
        // Robot avatar; the small badge keeps the agent's own role icon
        <div className="relative shrink-0">
          <div
            className="flex h-11 w-11 items-center justify-center rounded-full text-white"
            style={{ background: `radial-gradient(circle at 30% 25%, ${color}77, ${color}22)`, boxShadow: `0 0 0 1.5px ${color}aa` }}
          >
            <Bot size={24} strokeWidth={1.7} />
          </div>
          <span className="absolute -bottom-1 -right-1 flex h-[18px] w-[18px] items-center justify-center rounded-full border bg-[#0b1120]" style={{ borderColor: color, color }}>
            <Icon size={10} strokeWidth={2.2} />
          </span>
        </div>
      ) : (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: `${color}26`, color }}>
          <Icon size={18} strokeWidth={1.8} />
        </div>
      )}
      <div className="min-w-0 break-words">
        {agent && (
          <div className="text-[9px] font-semibold uppercase tracking-[0.16em]" style={{ color }}>
            Agent
          </div>
        )}
        <div className="text-sm font-semibold leading-tight text-white">{def.title}</div>
        <div className="text-[11px] leading-snug text-muted">{def.sub}</div>
      </div>
    </div>
  );
}

export default function FlowDiagram({ diagram, run }: { diagram: Diagram; run?: RunView }) {
  const { nodes, lanes, edges, groups, note } = diagram;
  const running = !!run;
  const activeEdges = new Set(run?.edges ?? []);
  const reduceMotion = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const uid = useId().replace(/:/g, "");
  const box = useRef<HTMLDivElement>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  const [paths, setPaths] = useState<Path[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<string | null>(null);

  const setRef = useCallback((id: string, el: HTMLDivElement | null) => {
    refs.current[id] = el;
  }, []);

  const measure = useCallback(() => {
    const root = box.current;
    if (!root) return;
    const base = root.getBoundingClientRect();
    const rect = (id: string) => {
      const el = refs.current[id];
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height };
    };
    const out: Path[] = [];
    const loops: Record<string, number> = {}; // loops leaving the same card get different depths
    for (const e of edges) {
      const a = rect(e.from);
      const b = rect(e.to);
      if (!a || !b) continue;
      const down = b.y > a.y + a.h / 2;
      const sameRow = Math.abs(b.y - a.y) < 8;
      let x1: number, y1: number, x2: number, y2: number, d: string;
      let loopDepth = 0;
      // a link inside one row loops under it only when another card sits between its two ends
      const lo = Math.min(a.x, b.x);
      const hi = Math.max(a.x, b.x);
      const skips =
        sameRow &&
        Object.keys(refs.current).some((id) => {
          if (id === e.from || id === e.to) return false;
          const o = rect(id);
          return !!o && Math.abs(o.y - a.y) < 8 && o.x > lo && o.x < hi;
        });
      if (skips) {
        x1 = a.x + a.w / 2;
        y1 = a.y + a.h;
        x2 = b.x + b.w / 2;
        y2 = b.y + b.h;
        const depth = 40 + 34 * (loops[e.from] ?? 0);
        loops[e.from] = (loops[e.from] ?? 0) + 1;
        loopDepth = depth;
        d = `M${x1},${y1} C${x1},${y1 + depth} ${x2},${y2 + depth} ${x2},${y2}`;
      } else if (sameRow) {
        const right = b.x > a.x;
        x1 = right ? a.x + a.w : a.x;
        y1 = a.y + a.h / 2;
        x2 = right ? b.x : b.x + b.w;
        y2 = b.y + b.h / 2;
        const mx = (x1 + x2) / 2;
        d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
      } else {
        x1 = a.x + (e.fa ?? a.w / 2);
        y1 = down ? a.y + a.h : a.y;
        x2 = b.x + (e.fb ?? b.w / 2);
        y2 = down ? b.y : b.y + b.h;
        // long hops (over a whole lane) run straight down for the last stretch, through the gaps between cards
        const far = Math.abs(y2 - y1) > 150;
        const c1 = y1 + (y2 - y1) * (far ? 0.12 : 0.5);
        const c2 = y2 - (y2 - y1) * (far ? 0.62 : 0.5);
        d = `M${x1},${y1} C${x1},${c1} ${x2},${c2} ${x2},${y2}`;
      }
      out.push({
        key: `${e.from}-${e.to}`,
        d,
        from: e.from,
        to: e.to,
        color: colorOf(nodes[e.from]),
        lx: (x1 + x2) / 2,
        ly: skips ? y1 + loopDepth * 0.75 : (y1 + y2) / 2,
        label: e.label,
      });
    }
    setPaths(out);
    setSize({ w: base.width, h: base.height });
  }, [edges, nodes]);

  useLayoutEffect(() => {
    measure();
  }, [measure]);

  useEffect(() => {
    const root = box.current;
    if (!root) return;
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  // After every step of a replay, bring the card that just woke up into view
  useEffect(() => {
    if (run?.focus) refs.current[run.focus]?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.seq]);

  const linked = new Set<string>();
  if (hover) {
    linked.add(hover);
    for (const e of edges) {
      if (e.from === hover) linked.add(e.to);
      if (e.to === hover) linked.add(e.from);
    }
  }

  const kindsUsed = [...new Set(Object.values(nodes).map((n) => n.kind))];

  const blocks: { group?: string; lanes: Lane[] }[] = [];
  for (const lane of lanes) {
    const last = blocks[blocks.length - 1];
    if (lane.group && last?.group === lane.group) last.lanes.push(lane);
    else blocks.push({ group: lane.group, lanes: [lane] });
  }

  const renderLane = (lane: Lane) => {
    const cols = lane.cols ?? Math.max(lane.ids.length, 3);
    return (
      <section key={lane.ids[0]} className="relative">
        {lane.title && (
          <div className="relative z-10 mb-3 flex w-fit items-baseline gap-2 rounded bg-[#070b14] pr-2">
            <span className="h-px w-6 bg-border" />
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{lane.title}</h3>
            {lane.hint && <span className="text-[11px] text-muted/60">{lane.hint}</span>}
          </div>
        )}
        <div className="grid gap-x-5" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {lane.ids.map((id, i) => (
            <NodeCard
              key={id}
              column={lane.at ? String(lane.at[i]) : undefined}
              def={nodes[id]}
              active={!running && hover === id}
              dim={running ? !run!.nodes[id] : !!hover && !linked.has(id)}
              state={run?.nodes[id]}
              setRef={setRef}
              onHover={setHover}
            />
          ))}
        </div>
      </section>
    );
  };

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto overflow-y-hidden rounded-2xl border border-border">
        <div
          ref={box}
          className="relative min-w-[980px] p-6"
          style={{
            backgroundColor: "#070b14",
            backgroundImage:
              "radial-gradient(circle at 20% 0%, #3b9cff14, transparent 45%), radial-gradient(circle at 90% 100%, #8b5cf616, transparent 45%), radial-gradient(#1e2a44 1px, transparent 1px)",
            backgroundSize: "auto, auto, 22px 22px",
          }}
        >
          <style>{`
            @keyframes arch-flow { to { stroke-dashoffset: -24; } }
            .arch-flow { animation: arch-flow 1.4s linear infinite; }
            @keyframes run-glow {
              0%, 100% { box-shadow: 0 0 0 1px var(--c), 0 0 12px var(--c); }
              50% { box-shadow: 0 0 0 2px var(--c), 0 0 32px var(--c); }
            }
            .run-working { animation: run-glow 1.3s ease-in-out infinite; }
            @keyframes run-spin { to { transform: rotate(360deg); } }
            .run-spin { animation: run-spin 0.9s linear infinite; }
            @media (prefers-reduced-motion: reduce) { .arch-flow, .run-working, .run-spin { animation: none; } }
          `}</style>

          <svg className="pointer-events-none absolute inset-0" width={size.w} height={size.h} aria-hidden>
            <defs>
              {[...new Set(paths.map((p) => p.color))].map((c) => (
                <marker key={c} id={`${uid}-${c.slice(1)}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill={c} />
                </marker>
              ))}
            </defs>
            {paths.map((p) => {
              const on = running ? activeEdges.has(p.key) : !hover || p.from === hover || p.to === hover;
              const bright = running ? on : !!hover && on;
              return (
                <g key={p.key} style={{ opacity: on ? 1 : running ? 0.1 : 0.07, transition: "opacity 200ms" }}>
                  <path d={p.d} fill="none" stroke={p.color} strokeOpacity={bright ? 0.35 : 0.18} strokeWidth={bright ? 7 : 5} />
                  <path
                    d={p.d}
                    fill="none"
                    stroke={p.color}
                    strokeWidth={bright ? 2.4 : 1.5}
                    strokeDasharray="6 6"
                    className="arch-flow"
                    markerEnd={`url(#${uid}-${p.color.slice(1)})`}
                  />
                  {running && on && !reduceMotion &&
                    [0, -0.7].map((begin) => (
                      <circle key={begin} r={4} fill={p.color} style={{ filter: `drop-shadow(0 0 4px ${p.color})` }}>
                        <animateMotion dur="1.4s" begin={`${begin}s`} repeatCount="indefinite" path={p.d} />
                      </circle>
                    ))}
                </g>
              );
            })}
          </svg>

          <div className="space-y-20">
            {blocks.map((b) =>
              b.group ? (
                // The agent team: one dashed zone around the lanes that hold agents. -mx-4/px-4 keeps the cards where they were.
                <div
                  key={b.lanes[0].ids[0]}
                  className="relative -mx-4 space-y-20 rounded-3xl border border-dashed px-4 pb-6 pt-8"
                  style={{ borderColor: `${KINDS.agent.color}88`, boxShadow: `inset 0 0 60px ${KINDS.agent.color}14` }}
                >
                  <span
                    className="absolute -top-3 left-6 rounded-full border bg-[#0b1120] px-3 py-0.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
                    style={{ borderColor: `${KINDS.agent.color}aa`, color: KINDS.agent.color }}
                  >
                    {groups?.[b.group] ?? b.group}
                  </span>
                  {b.lanes.map(renderLane)}
                </div>
              ) : (
                renderLane(b.lanes[0])
              ),
            )}
          </div>

          {paths
            .filter((p) => p.label && (running ? activeEdges.has(p.key) : !hover || p.from === hover || p.to === hover))
            .map((p) => (
              <span
                key={`l-${p.key}`}
                className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full border border-border bg-[#0b1120] px-2 py-0.5 font-mono text-[10px] text-muted"
                style={{ left: p.lx, top: p.ly }}
              >
                {p.label}
              </span>
            ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted">
        {kindsUsed.map((k) => (
          <span key={k} className="flex items-center gap-2">
            <span className="inline-block h-3 w-5 rounded" style={{ background: KINDS[k].color + "33", border: "1px solid " + KINDS[k].color }} />
            {KINDS[k].label}
          </span>
        ))}
        <span className="text-muted/70">{running ? "A run is in progress. Lit boxes and moving dots show what is happening now." : "Hover a box to follow its connections."}</span>
        {note && <span className="basis-full text-muted/70">{note}</span>}
      </div>
    </div>
  );
}
