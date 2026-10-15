import {
  BellRing,
  Boxes,
  Cable,
  CircleUser,
  ClipboardList,
  FileText,
  GitBranch,
  GitCommitHorizontal,
  Layout,
  LineChart,
  ListChecks,
  Play,
  Radar,
  ScrollText,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Wrench,
} from "lucide-react";
import { node, type Diagram } from "./FlowDiagram";

// Six-column grid. The agents in the middle lanes sit on the even columns (2, 4), which leaves the odd
// columns (1, 3, 5) free so each evidence agent's link to its connector runs straight down between cards.
export const overview: Diagram = {
  nodes: {
    alert: node("alert", "Azure Monitor alert", "Action Group webhook", BellRing, "external"),
    engineer: node("engineer", "On-call engineer", "opens the site, approves fixes", CircleUser, "human"),
    api: node("api", "Triage API", "FastAPI: /alerts, /runs", ServerCog, "entry"),
    frontend: node("frontend", "Frontend", "nginx serves this site", Layout, "entry"),

    triage: node("triage", "Triage supervisor", "classify, plan, route", Radar, "agent"),
    openai: node("openai", "Azure OpenAI", "every agent reasons here", Sparkles, "shared"),

    logs: node("logs", "Logs agent", "error patterns", ScrollText, "agent"),
    metrics: node("metrics", "Metrics agent", "spikes, saturation", LineChart, "agent"),
    change: node("change", "Change agent", "deploys, config diffs", GitCommitHorizontal, "agent"),

    diagnosis: node("diagnosis", "Diagnosis agent", "ranked root causes", Stethoscope, "agent"),
    remediation: node("remediation", "Remediation agent", "fix options and risk", ListChecks, "agent"),

    gate: node("gate", "Approval gate", "nothing runs without a person", ShieldCheck, "human"),

    postmortem: node("postmortem", "Postmortem agent", "timeline, cause, follow-ups", FileText, "agent"),
    executor: node("executor", "Action executor", "runs the approved fix", Play, "agent"),

    cl: node("cl", "Logs connector", "templated KQL", Cable, "connector"),
    cdo: node("cdo", "Work item connector", "writes to Boards", Cable, "connector"),
    cm: node("cm", "Metrics connector", "metric queries", Cable, "connector"),
    carm: node("carm", "Action connector", "restart, scale, rollback", Wrench, "connector"),
    cc: node("cc", "Change connector", "Activity Log, DevOps reads", Cable, "connector"),

    azlog: node("azlog", "Log Analytics", "KQL query API", ScrollText, "external"),
    azbrd: node("azbrd", "Azure DevOps Boards", "work items", ClipboardList, "external"),
    azmet: node("azmet", "Azure Monitor", "metrics API", LineChart, "external"),
    azres: node("azres", "Azure resources", "App Service, AKS, VMs", Boxes, "external"),
    azact: node("azact", "Activity Log", "who changed what", ScrollText, "external"),
    azpipe: node("azpipe", "Azure DevOps", "Pipelines, Repos", GitBranch, "external"),
  },
  lanes: [
    { title: "Outside", hint: "people and Azure", ids: ["alert", "engineer"], at: [2, 5], cols: 6 },
    { title: "Entry", ids: ["api", "frontend"], at: [2, 5], cols: 6 },
    { title: "Orchestrator", hint: "LangGraph state machine", ids: ["triage", "openai"], at: [3, 5], cols: 6, group: "agents" },
    { title: "Evidence agents", hint: "run in parallel, read-only", ids: ["logs", "metrics", "change"], at: [1, 3, 5], cols: 6, group: "agents" },
    { title: "Reasoning", hint: "no tools, only the evidence", ids: ["diagnosis", "remediation"], at: [2, 4], cols: 6, group: "agents" },
    { title: "Human in the loop", ids: ["gate"], at: [4], cols: 6, group: "agents" },
    { title: "Action", hint: "the only agents that write anything", ids: ["postmortem", "executor"], at: [2, 4], cols: 6, group: "agents" },
    { title: "Connector layer", hint: "the only way agents reach Azure; demo mode swaps it", ids: ["cl", "cdo", "cm", "carm", "cc"], at: [1, 2, 3, 4, 5], cols: 6 },
    { title: "Azure and Azure DevOps", hint: "your subscription", ids: ["azlog", "azbrd", "azmet", "azres", "azact", "azpipe"], cols: 6 },
  ],
  groups: { agents: "Agent team · LangGraph" },
  edges: [
    { from: "alert", to: "api", label: "webhook" },
    { from: "engineer", to: "frontend", label: "HTTPS" },
    { from: "frontend", to: "api", label: "/api" },
    { from: "api", to: "triage", label: "start run" },
    { from: "triage", to: "openai" },

    { from: "triage", to: "logs" },
    { from: "triage", to: "metrics" },
    { from: "triage", to: "change" },

    { from: "logs", to: "diagnosis", label: "findings" },
    { from: "metrics", to: "diagnosis" },
    { from: "change", to: "diagnosis" },
    { from: "diagnosis", to: "logs", label: "needs more evidence", fa: 40, fb: 40 },
    { from: "diagnosis", to: "remediation", label: "root cause" },
    { from: "remediation", to: "gate", label: "proposed fix" },
    { from: "gate", to: "executor", label: "approved" },
    { from: "gate", to: "postmortem", label: "always" },
    { from: "executor", to: "postmortem", label: "result" },

    { from: "logs", to: "cl", label: "KQL" },
    { from: "metrics", to: "cm", label: "metrics" },
    { from: "change", to: "cc", label: "read-only" },
    { from: "executor", to: "carm", label: "after approval" },
    { from: "postmortem", to: "cdo", label: "work item" },

    { from: "cl", to: "azlog" },
    { from: "cdo", to: "azbrd" },
    { from: "cm", to: "azmet" },
    { from: "carm", to: "azres" },
    { from: "cc", to: "azact" },
    { from: "cc", to: "azpipe" },
  ],
  note: "Eight agents share one run. The Triage supervisor starts three evidence agents in parallel; Diagnosis weighs their findings and can send them back out for more. Agents never call Azure directly: each evidence agent reads through its own connector, and the one connector that can change a resource (Action) is reachable only after a person approves. In demo mode the connector layer points at Prometheus, Loki and a fault injector instead of Azure.",
};
