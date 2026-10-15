import { useState, type ReactNode } from "react";
import clsx from "clsx";
import FlowDiagram from "./FlowDiagram";
import { overview } from "./diagrams";
import { EventLog, RunBar } from "./RunControls";
import { useRun } from "./useRun";

type Status = "Running" | "Planned";

const STATUS_STYLE: Record<Status, string> = {
  Running: "border-ok/40 text-ok",
  Planned: "border-warn/40 text-warn",
};

function Badge({ status }: { status: Status }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${STATUS_STYLE[status]}`}>
      {status === "Running" ? "Running in Docker" : "Planned"}
    </span>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
            {head.map((h) => (
              <th key={h} className="py-2 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border/50 align-top">
              {r.map((c, j) => (
                <td key={j} className={`py-2 pr-4 ${j === 0 ? "font-medium" : "text-muted"}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const steps: [string, string][] = [
  ["Alert fires", "Azure Monitor posts the alert to /alerts. The API stores a run and starts the graph."],
  ["Triage", "The supervisor reads the alert, picks the affected resources and decides which evidence agents to start."],
  ["Evidence, in parallel", "Logs, Metrics and Change agents query only through connectors and return findings with confidence."],
  ["Diagnosis", "Ranks root causes and cites the evidence. Low confidence loops back for more queries."],
  ["Remediation and approval", "Fix options are scored for risk. A person approves before anything executes."],
  ["Execute and write up", "The executor runs the approved fix. The postmortem agent files the report to Azure DevOps Boards."],
];

function Steps() {
  return (
    <ol className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
      {steps.map(([title, text], i) => (
        <li key={title} className="flex gap-3">
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-azure/15 font-mono text-xs text-azure">{i + 1}</span>
          <div>
            <div className="text-sm font-medium">{title}</div>
            <div className="text-xs text-muted">{text}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

const components: { name: string; what: string; tech: string; status: Status }[] = [
  { name: "Frontend", what: "This site. nginx serves the React build and will forward /api to the Triage API.", tech: "React, Vite, Tailwind, nginx", status: "Running" },
  { name: "Triage API", what: "Receives alert webhooks, starts runs, stores approvals and streams progress to the UI.", tech: "FastAPI", status: "Planned" },
  { name: "Orchestrator", what: "Wires the eight agents into a state machine: parallel fan-out, a loop back for more evidence, and a pause for approval.", tech: "LangGraph, Azure OpenAI", status: "Planned" },
  { name: "Connector layer", what: "Interfaces for logs, metrics, changes and actions. One implementation per backend: Azure, or the demo stack.", tech: "Python, azure-monitor-query, Azure DevOps REST", status: "Planned" },
  { name: "Demo environment", what: "A small sample app, Prometheus, Loki and a fault injector that breaks it on demand, so every run is testable without Azure.", tech: "Docker Compose", status: "Planned" },
  { name: "Run store and traces", what: "Run state and reports in Postgres; every agent step traced with cost in Langfuse.", tech: "Postgres, Langfuse", status: "Planned" },
];

const agents: { name: string; job: string; reads: string; writes: string }[] = [
  { name: "Triage supervisor", job: "Reads the alert, picks the affected resources, decides which evidence agents to start.", reads: "the alert", writes: "no" },
  { name: "Logs agent", job: "Finds error patterns in the alert window.", reads: "Log Analytics, through the Logs connector", writes: "no" },
  { name: "Metrics agent", job: "Finds spikes and saturation.", reads: "Azure Monitor metrics, through the Metrics connector", writes: "no" },
  { name: "Change agent", job: "Finds recent deploys, commits and config changes.", reads: "Activity Log and Azure DevOps, through the Change connector", writes: "no" },
  { name: "Diagnosis agent", job: "Ranks root causes with cited evidence. Asks the evidence agents for more when confidence is low.", reads: "the three agents' findings", writes: "no" },
  { name: "Remediation agent", job: "Proposes fixes with a risk rating and a rollback plan.", reads: "the diagnosis", writes: "no" },
  { name: "Action executor", job: "Runs the approved fix.", reads: "the approved plan", writes: "Azure resources, only after approval" },
  { name: "Postmortem agent", job: "Writes timeline, cause and follow-ups.", reads: "the whole run", writes: "a work item in Azure DevOps Boards" },
];

type Tab = "overview" | "components";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "components", label: "Agents and components" },
];

// Agents and the approval gate are the nodes the replay scrolls to
const FOCUS_IDS = new Set(Object.values(overview.nodes).filter((n) => n.kind === "agent" || n.kind === "human").map((n) => n.id));

function Overview() {
  const run = useRun(FOCUS_IDS);
  return (
    <div className="space-y-6">
      <div className="glass space-y-3 p-6">
        <h2 className="text-lg font-semibold">The whole picture</h2>
        <p className="text-sm text-muted">
          {run.view ? run.scenario.blurb : "Arrows show who calls whom. Press Play a run to watch the agents handle a simulated incident."}
        </p>
        <RunBar run={run} />
        <FlowDiagram diagram={overview} run={run.view} />
      </div>
      <EventLog lines={run.log} />
      <div className="glass space-y-4 p-6">
        <h2 className="text-lg font-semibold">How one incident moves through the system</h2>
        <Steps />
      </div>
    </div>
  );
}

export default function ArchitecturePage() {
  const [tab, setTab] = useState<Tab>(() => TABS.find((t) => t.id === location.hash.slice(1))?.id ?? "overview");
  const pick = (id: Tab) => {
    setTab(id);
    history.replaceState(null, "", `#${id}`);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Architecture</h1>
        <p className="max-w-3xl text-sm text-muted">
          An Azure Monitor alert wakes a team of agents. They collect evidence in parallel, name the likely root cause, propose a fix, and wait for a person before touching anything.
        </p>
      </div>

      <nav className="glass flex w-fit flex-wrap gap-1 p-1" aria-label="Architecture views">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => pick(t.id)}
            aria-current={tab === t.id}
            className={clsx("rounded-xl px-3 py-2 text-sm transition", tab === t.id ? "bg-azure/20 text-white" : "text-muted hover:text-white")}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "overview" && <Overview />}

      {tab === "components" && (
        <div className="space-y-6">
          <div className="glass space-y-3 p-6">
            <h2 className="text-lg font-semibold">The eight agents</h2>
            <Table head={["Agent", "Job", "Reads", "Can change anything?"]} rows={agents.map((a) => [a.name, a.job, a.reads, a.writes])} />
          </div>
          <div className="glass space-y-3 p-6">
            <h2 className="text-lg font-semibold">Components</h2>
            <Table
              head={["Component", "What it does", "Tech", "Status"]}
              rows={components.map((c) => [c.name, c.what, c.tech, <Badge key={c.name} status={c.status} />])}
            />
          </div>
        </div>
      )}
    </div>
  );
}
