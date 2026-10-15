// Exports the architecture diagram as a standalone SVG for the README and BLUEPRINT.md.
// It reads the same data the site draws (src/features/architecture/diagrams.ts) and repeats the
// site's layout rules, so the picture in the docs cannot drift from the page.
//
//   npm run export:diagram        ->  ../docs/architecture.svg
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dir = resolve(here, "../src/features/architecture");
const out = resolve(here, "../../docs/architecture.svg");

const data = readFileSync(resolve(dir, "diagrams.ts"), "utf8");
const flow = readFileSync(resolve(dir, "FlowDiagram.tsx"), "utf8");

// ---- parse ----
const KINDS = Object.fromEntries(
  [...flow.matchAll(/(\w+): \{ color: "(#\w+)", label: "([^"]*)" \}/g)].map((m) => [m[1], { color: m[2], label: m[3] }]),
);
const nodes = Object.fromEntries(
  [...data.matchAll(/\w+: node\("(\w+)", "([^"]*)", "([^"]*)", \w+, "(\w+)"\)/g)].map((m) => [m[1], { id: m[1], title: m[2], sub: m[3], kind: m[4] }]),
);
const lanes = [...data.matchAll(/\{ title: "([^"]*)"(?:, hint: "([^"]*)")?, ids: \[([^\]]*)\](?:, at: \[([^\]]*)\])?(?:, cols: (\d+))?(?:, group: "(\w+)")? \}/g)].map((m) => {
  const ids = m[3].split(",").map((s) => s.trim().replace(/"/g, ""));
  return { title: m[1], hint: m[2], ids, at: m[4] ? m[4].split(",").map(Number) : undefined, cols: m[5] ? Number(m[5]) : Math.max(ids.length, 3), group: m[6] };
});
const groupLabels = Object.fromEntries([...(data.match(/groups: \{([^}]*)\}/)?.[1] ?? "").matchAll(/(\w+): "([^"]*)"/g)].map((m) => [m[1], m[2]]));
const edges = [...data.matchAll(/\{ from: "(\w+)", to: "(\w+)"(?:, label: "([^"]*)")?(?:, fa: (\d+))?(?:, fb: (\d+))? \}/g)].map((m) => ({
  from: m[1], to: m[2], label: m[3], fa: m[4] ? Number(m[4]) : undefined, fb: m[5] ? Number(m[5]) : undefined,
}));
const note = data.match(/note: "([^"]*)"/)?.[1];

// ---- layout (mirrors the site: padded box, lanes 80px apart, grid columns 20px apart) ----
const W = 1180, PAD = 24, GAP = 20, LANE_GAP = 80, TITLE_H = 28;
const BG = "#070b14", BORDER = "#1e2a44", MUTED = "#8b98b5";
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const wrap = (text, max) => {
  const lines = [];
  let cur = "";
  for (const w of text.split(" ")) {
    if (cur && (cur + " " + w).length > max) { lines.push(cur); cur = w; } else cur = cur ? cur + " " + w : w;
  }
  if (cur) lines.push(cur);
  return lines;
};

const rects = {};
let y = PAD;
const laneBoxes = [];
const zones = []; // dashed zones around groups of lanes (the agent team): 32px above the first lane, 24px below the last
let zoneTop = 0;
lanes.forEach((lane, i) => {
  const startsGroup = lane.group && lanes[i - 1]?.group !== lane.group;
  const endsGroup = lane.group && lanes[i + 1]?.group !== lane.group;
  if (startsGroup) { zoneTop = y; y += 32; }
  const colW = (W - 2 * PAD - (lane.cols - 1) * GAP) / lane.cols;
  const cards = lane.ids.map((id, i) => {
    const n = nodes[id];
    const agent = n.kind === "agent"; // agents get a robot avatar, so their text column is narrower and the card taller
    const tl = wrap(n.title, agent ? 13 : 15), sl = wrap(n.sub, agent ? 16 : 19);
    const h = agent ? 28 + Math.max(44, 12 + tl.length * 16 + sl.length * 13) : 24 + tl.length * 16 + sl.length * 13;
    return { n, agent, tl, sl, col: lane.at ? lane.at[i] - 1 : i, h };
  });
  const h = Math.max(60, ...cards.map((c) => c.h));
  const cardsY = y + TITLE_H;
  for (const c of cards) {
    rects[c.n.id] = { x: PAD + c.col * (colW + GAP), y: cardsY, w: colW, h };
  }
  laneBoxes.push({ lane, y, cards });
  y = cardsY + h;
  if (endsGroup) { y += 24; zones.push({ label: groupLabels[lane.group] ?? lane.group, top: zoneTop, bottom: y }); }
  y += LANE_GAP;
});
const diagramH = y - LANE_GAP + PAD;

// ---- edges (same routing rules as FlowDiagram.tsx) ----
const loops = {};
const paths = [];
for (const e of edges) {
  const a = rects[e.from], b = rects[e.to];
  if (!a || !b) continue;
  const down = b.y > a.y + a.h / 2;
  const sameRow = Math.abs(b.y - a.y) < 8;
  const lo = Math.min(a.x, b.x), hi = Math.max(a.x, b.x);
  const skips = sameRow && Object.entries(rects).some(([id, o]) => id !== e.from && id !== e.to && Math.abs(o.y - a.y) < 8 && o.x > lo && o.x < hi);
  let x1, y1, x2, y2, d, ly;
  if (skips) {
    x1 = a.x + a.w / 2; y1 = a.y + a.h; x2 = b.x + b.w / 2; y2 = b.y + b.h;
    const depth = 40 + 34 * (loops[e.from] ?? 0);
    loops[e.from] = (loops[e.from] ?? 0) + 1;
    d = `M${x1},${y1} C${x1},${y1 + depth} ${x2},${y2 + depth} ${x2},${y2}`;
    ly = y1 + depth * 0.75;
  } else if (sameRow) {
    const right = b.x > a.x;
    x1 = right ? a.x + a.w : a.x; y1 = a.y + a.h / 2;
    x2 = right ? b.x : b.x + b.w; y2 = b.y + b.h / 2;
    const mx = (x1 + x2) / 2;
    d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    ly = (y1 + y2) / 2;
  } else {
    x1 = a.x + (e.fa ?? a.w / 2); y1 = down ? a.y + a.h : a.y;
    x2 = b.x + (e.fb ?? b.w / 2); y2 = down ? b.y : b.y + b.h;
    const far = Math.abs(y2 - y1) > 150;
    const c1 = y1 + (y2 - y1) * (far ? 0.12 : 0.5);
    const c2 = y2 - (y2 - y1) * (far ? 0.62 : 0.5);
    d = `M${x1},${y1} C${x1},${c1} ${x2},${c2} ${x2},${y2}`;
    ly = (y1 + y2) / 2;
  }
  paths.push({ d, color: KINDS[nodes[e.from].kind].color, lx: (x1 + x2) / 2, ly, label: e.label });
}

// ---- legend and note ----
const kindsUsed = [...new Set(Object.values(nodes).map((n) => n.kind))];
const noteLines = note ? wrap(note, 205) : [];
const legendY = diagramH + 26;
const totalH = legendY + 22 + noteLines.length * 15 + 10;

// ---- draw ----
const s = [];
s.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${totalH}" width="${W}" role="img" aria-label="Incident triage architecture: eight agents, five connectors, Azure and Azure DevOps">`);
s.push(`<defs>`);
s.push(`<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#1e2a44"/></pattern>`);
for (const c of new Set(paths.map((p) => p.color))) {
  s.push(`<marker id="m${c.slice(1)}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`);
}
s.push(`</defs>`);
s.push(`<style>text{font-family:Inter,'Segoe UI',Helvetica,Arial,sans-serif}.mono{font-family:'JetBrains Mono',Consolas,'Courier New',monospace}</style>`);
s.push(`<rect width="${W}" height="${totalH}" fill="${BG}"/><rect width="${W}" height="${diagramH}" fill="url(#dots)"/>`);

for (const p of paths) {
  s.push(`<path d="${p.d}" fill="none" stroke="${p.color}" stroke-opacity="0.18" stroke-width="5"/>`);
  s.push(`<path d="${p.d}" fill="none" stroke="${p.color}" stroke-width="1.5" stroke-dasharray="6 6" marker-end="url(#m${p.color.slice(1)})"/>`);
}

const AGENT = KINDS.agent.color;
for (const z of zones) {
  s.push(`<rect x="8" y="${z.top}" width="${W - 16}" height="${z.bottom - z.top}" rx="24" fill="${AGENT}" fill-opacity="0.04" stroke="${AGENT}" stroke-opacity="0.53" stroke-dasharray="5 5"/>`);
  const label = z.label.toUpperCase();
  const w = label.length * 9.4 + 28;
  s.push(`<rect x="32" y="${z.top - 12}" width="${w}" height="24" rx="12" fill="#0b1120" stroke="${AGENT}" stroke-opacity="0.67"/>`);
  s.push(`<text x="46" y="${z.top + 4}" font-size="11" font-weight="600" letter-spacing="1.8" fill="${AGENT}">${esc(label)}</text>`);
}

for (const { lane, y: ly } of laneBoxes) {
  const label = lane.title.toUpperCase();
  const w = label.length * 9.4 + (lane.hint ? lane.hint.length * 5.6 + 10 : 0) + 38;
  s.push(`<rect x="${PAD}" y="${ly - 2}" width="${w}" height="18" rx="3" fill="${BG}"/>`);
  s.push(`<line x1="${PAD}" y1="${ly + 8}" x2="${PAD + 24}" y2="${ly + 8}" stroke="${BORDER}"/>`);
  s.push(`<text x="${PAD + 32}" y="${ly + 12}" font-size="10.5" font-weight="600" letter-spacing="1.8" fill="${MUTED}">${esc(label)}</text>`);
  if (lane.hint) s.push(`<text x="${PAD + 32 + label.length * 9.4 + 8}" y="${ly + 12}" font-size="10.5" fill="${MUTED}" fill-opacity="0.6">${esc(lane.hint)}</text>`);
}

for (const b of laneBoxes) {
  for (const c of b.cards) {
    const r = rects[c.n.id];
    const color = KINDS[c.n.kind].color;
    const cy = r.y + r.h / 2;
    let tx = r.x + 46;
    let block = c.tl.length * 16 + c.sl.length * 13;
    if (c.agent) {
      // robot avatar in a round badge, a role dot on its corner, and an AGENT tag above the title
      const cx = r.x + 33;
      s.push(`<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="16" fill="${color}" fill-opacity="0.2" stroke="${color}" stroke-opacity="0.6" stroke-width="2"/>`);
      s.push(`<circle cx="${cx}" cy="${cy}" r="22" fill="${color}" fill-opacity="0.28" stroke="${color}" stroke-opacity="0.67" stroke-width="1.5"/>`);
      s.push(`<g stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" fill="none"><rect x="${cx - 9}" y="${cy - 5}" width="18" height="13" rx="3.5"/><line x1="${cx}" y1="${cy - 5}" x2="${cx}" y2="${cy - 10}"/><line x1="${cx - 12}" y1="${cy + 0.5}" x2="${cx - 12}" y2="${cy + 4.5}"/><line x1="${cx + 12}" y1="${cy + 0.5}" x2="${cx + 12}" y2="${cy + 4.5}"/></g>`);
      s.push(`<circle cx="${cx}" cy="${cy - 11.5}" r="1.8" fill="#fff"/><circle cx="${cx - 3.6}" cy="${cy + 1.5}" r="1.7" fill="#fff"/><circle cx="${cx + 3.6}" cy="${cy + 1.5}" r="1.7" fill="#fff"/>`);
      s.push(`<circle cx="${cx + 15}" cy="${cy + 16}" r="9" fill="#0b1120" stroke="${color}"/><circle cx="${cx + 15}" cy="${cy + 16}" r="2.6" fill="${color}"/>`);
      tx = r.x + 64;
      block += 12;
      let ty0 = cy - block / 2 + 8;
      s.push(`<text x="${tx}" y="${ty0}" font-size="9" font-weight="600" letter-spacing="1.5" fill="${color}">AGENT</text>`);
    } else {
      s.push(`<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="14" fill="${color}" fill-opacity="0.12" stroke="${color}" stroke-opacity="0.45"/>`);
      s.push(`<rect x="${r.x + 8}" y="${cy - 15}" width="30" height="30" rx="9" fill="${color}" fill-opacity="0.2"/>`);
      s.push(`<circle cx="${r.x + 23}" cy="${cy}" r="5" fill="none" stroke="${color}" stroke-width="1.8"/>`);
    }
    let ty = r.y + (r.h - block) / 2 + 12 + (c.agent ? 12 : 0);
    for (const line of c.tl) { s.push(`<text x="${tx}" y="${ty}" font-size="13" font-weight="600" fill="#fff">${esc(line)}</text>`); ty += 16; }
    for (const line of c.sl) { s.push(`<text x="${tx}" y="${ty - 1}" font-size="10.5" fill="${MUTED}">${esc(line)}</text>`); ty += 13; }
  }
}

for (const p of paths) {
  if (!p.label) continue;
  const w = p.label.length * 6.6 + 16;
  s.push(`<rect x="${p.lx - w / 2}" y="${p.ly - 9}" width="${w}" height="18" rx="9" fill="#0b1120" stroke="${BORDER}"/>`);
  s.push(`<text class="mono" x="${p.lx}" y="${p.ly + 3.5}" font-size="10" text-anchor="middle" fill="${MUTED}">${esc(p.label)}</text>`);
}

let lx = PAD;
for (const k of kindsUsed) {
  const { color, label } = KINDS[k];
  s.push(`<rect x="${lx}" y="${legendY - 9}" width="20" height="12" rx="3" fill="${color}" fill-opacity="0.2" stroke="${color}"/>`);
  s.push(`<text x="${lx + 28}" y="${legendY + 1}" font-size="12" fill="${MUTED}">${esc(label)}</text>`);
  lx += 28 + label.length * 6.4 + 22;
}
noteLines.forEach((line, i) => s.push(`<text x="${PAD}" y="${legendY + 24 + i * 15}" font-size="11.5" fill="${MUTED}" fill-opacity="0.8">${esc(line)}</text>`));
s.push(`</svg>`);

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, s.join("\n") + "\n");
console.log(`wrote ${out} (${lanes.length} lanes, ${Object.keys(nodes).length} nodes, ${edges.length} edges)`);
