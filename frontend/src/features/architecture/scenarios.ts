import type { NodeRun } from "./FlowDiagram";

// One step of a replay. The same shape will carry real events once the backend streams them:
// who changed state, which links carried a message, and what each agent said.
export interface Step {
  title: string;
  nodes: Record<string, NodeRun>; // status changes made in this step; earlier statuses carry over
  edges: string[]; // "from-to" keys of the links carrying a message right now
  log: { who: string; text: string }[];
  dt?: number; // simulated seconds this step takes (drives the log clock)
  ms?: number; // how long the step stays on screen at 1x
  approval?: boolean; // the run pauses here until a person decides
}

export interface Scenario {
  id: string;
  label: string;
  blurb: string;
  pre: Step[]; // everything up to the approval gate
  approved: Step[];
  rejected: Step[];
}

interface Case {
  id: string;
  label: string;
  blurb: string;
  alert: string;
  resource: string;
  logs: string;
  logsDeeper?: string;
  metrics: string;
  change: string;
  firstConfidence?: number; // set when the first pass is not convincing and Diagnosis asks for more
  whyUnsure?: string;
  confidence: number;
  cause: string;
  fix: string;
  risk: string;
  fixResult: string;
  report: string;
}

const W = (chip: string): NodeRun => ({ status: "working", chip });
const D = (chip?: string): NodeRun => ({ status: "done", chip });
const busy: NodeRun = { status: "working" };
const done: NodeRun = { status: "done" };

function build(c: Case): Scenario {
  const looped = c.firstConfidence !== undefined;
  const pre: Step[] = [
    {
      title: "Alert fires",
      nodes: { alert: W("firing"), api: W("receiving") },
      edges: ["alert-api"],
      log: [
        { who: "Azure Monitor", text: `Alert fired: ${c.alert}` },
        { who: "Triage API", text: "Run #1042 created. Starting the agent graph." },
      ],
    },
    {
      title: "Triage supervisor plans the run",
      nodes: { alert: D(), api: D(), triage: W("classifying…"), openai: busy },
      edges: ["api-triage", "triage-openai"],
      log: [{ who: "Triage supervisor", text: `Affected resource: ${c.resource}. Starting Logs, Metrics and Change agents in parallel.` }],
    },
    {
      title: "Three evidence agents query in parallel",
      nodes: {
        triage: D("dispatched"), openai: done,
        logs: W("querying…"), metrics: W("querying…"), change: W("querying…"),
        cl: busy, cm: busy, cc: busy, azlog: busy, azmet: busy, azact: busy, azpipe: busy,
      },
      edges: ["triage-logs", "triage-metrics", "triage-change", "logs-cl", "metrics-cm", "change-cc", "cl-azlog", "cm-azmet", "cc-azact", "cc-azpipe"],
      log: [
        { who: "Logs agent", text: "Running templated KQL on Log Analytics for the last 30 minutes." },
        { who: "Metrics agent", text: "Reading latency, error rate, CPU and memory from Azure Monitor." },
        { who: "Change agent", text: "Listing deploys and config changes since 12:00." },
      ],
      ms: 2800,
    },
    {
      title: "Findings flow to the Diagnosis agent",
      nodes: {
        logs: D("1 finding"), metrics: D("1 finding"), change: D("1 finding"),
        cl: done, cm: done, cc: done, azlog: done, azmet: done, azact: done, azpipe: done,
        diagnosis: W("weighing…"),
      },
      edges: ["logs-diagnosis", "metrics-diagnosis", "change-diagnosis"],
      log: [
        { who: "Logs agent", text: c.logs },
        { who: "Metrics agent", text: c.metrics },
        { who: "Change agent", text: c.change },
      ],
      ms: 3000,
    },
  ];

  if (looped) {
    pre.push(
      {
        title: "Diagnosis is not convinced and asks for more",
        nodes: { diagnosis: W(`${c.firstConfidence}% confident`), logs: W("digging deeper…"), cl: busy, azlog: busy },
        edges: ["diagnosis-logs", "logs-cl", "cl-azlog"],
        log: [
          { who: "Diagnosis agent", text: `Confidence ${c.firstConfidence}%. ${c.whyUnsure} Asking the Logs agent for a second pass.` },
          { who: "Logs agent", text: "Second pass: widening the window and pulling full stack traces." },
        ],
        ms: 2800,
      },
      {
        title: "The Logs agent returns the missing evidence",
        nodes: { logs: D("2nd pass done"), cl: done, azlog: done, diagnosis: W("weighing…") },
        edges: ["logs-diagnosis"],
        log: [{ who: "Logs agent", text: c.logsDeeper ?? "Second pass confirms the first finding." }],
      },
    );
  }

  pre.push(
    {
      title: "Root cause identified",
      nodes: { diagnosis: D(`${c.confidence}% confident`) },
      edges: [],
      log: [{ who: "Diagnosis agent", text: `Root cause: ${c.cause} (confidence ${c.confidence}%).` }],
    },
    {
      title: "Remediation agent proposes a fix",
      nodes: { remediation: W("planning fix…") },
      edges: ["diagnosis-remediation"],
      log: [{ who: "Remediation agent", text: "Comparing fix options by risk and rollback cost." }],
    },
    {
      title: "Waiting for a person to approve",
      nodes: { remediation: D("fix proposed"), gate: { status: "waiting", chip: "needs you" } },
      edges: ["remediation-gate"],
      log: [
        { who: "Remediation agent", text: `Proposed fix: ${c.fix}. Risk: ${c.risk}.` },
        { who: "Approval gate", text: "Paused. Nothing runs until the on-call engineer decides." },
      ],
      approval: true,
    },
  );

  const approved: Step[] = [
    {
      title: "Approved: the Action executor applies the fix",
      nodes: { gate: D("approved"), executor: W("running fix…"), carm: busy, azres: busy },
      edges: ["gate-executor", "executor-carm", "carm-azres"],
      log: [
        { who: "Approval gate", text: "Approved by the on-call engineer." },
        { who: "Action executor", text: `Applying: ${c.fix}.` },
      ],
      ms: 2600,
    },
    {
      title: "Fix verified, Postmortem agent starts",
      nodes: { executor: D("fixed"), carm: done, azres: done, postmortem: W("writing…") },
      edges: ["executor-postmortem", "gate-postmortem"],
      log: [
        { who: "Action executor", text: c.fixResult },
        { who: "Postmortem agent", text: "Drafting timeline, cause and follow-ups." },
      ],
    },
    {
      title: "Postmortem filed to Azure DevOps Boards",
      nodes: { postmortem: D("filed"), cdo: done, azbrd: done },
      edges: ["postmortem-cdo", "cdo-azbrd"],
      log: [{ who: "Postmortem agent", text: c.report }],
    },
    { title: "Run complete", nodes: {}, edges: [], log: [{ who: "Triage API", text: "Run #1042 closed: resolved with an approved fix." }], dt: 2 },
  ];

  const rejected: Step[] = [
    {
      title: "Rejected: nothing is changed, the Postmortem agent still runs",
      nodes: { gate: { status: "failed", chip: "rejected" }, postmortem: W("writing…") },
      edges: ["gate-postmortem"],
      log: [
        { who: "Approval gate", text: "Rejected by the on-call engineer. The fix will not be applied." },
        { who: "Postmortem agent", text: "Drafting a report that records the diagnosis and the proposed fix." },
      ],
      ms: 2600,
    },
    {
      title: "Report filed to Azure DevOps Boards",
      nodes: { postmortem: D("filed"), cdo: done, azbrd: done },
      edges: ["postmortem-cdo", "cdo-azbrd"],
      log: [{ who: "Postmortem agent", text: "Work item created with root cause, evidence and the rejected fix for follow-up." }],
    },
    { title: "Run complete", nodes: {}, edges: [], log: [{ who: "Triage API", text: "Run #1042 closed: fix rejected, handed to the on-call engineer." }], dt: 2 },
  ];

  return { id: c.id, label: c.label, blurb: c.blurb, pre, approved, rejected };
}

export const scenarios: Scenario[] = [
  build({
    id: "bad-deploy",
    label: "Bad deploy",
    blurb: "A release breaks pricing. Diagnosis needs a second look at the logs before it is sure.",
    alert: "orders-api p95 latency above 2 s for 5 minutes",
    resource: "orders-api (App Service, production)",
    logs: "NullReferenceException in PricingCalculator, first seen 14:02, 340 times in 10 minutes.",
    logsDeeper: "Full stack traces all end in PricingCalculator.ApplyDiscount, added in the latest release.",
    metrics: "HTTP 5xx rate rose from 0.2% to 9% at 14:02. CPU and memory are normal.",
    change: "Deploy #482 finished at 14:01 and changed the pricing module.",
    firstConfidence: 62,
    whyUnsure: "The errors start right after a deploy, but the log lines do not yet name the changed code.",
    confidence: 91,
    cause: "deploy #482 introduced a null reference in the pricing module",
    fix: "roll orders-api back to deploy #481",
    risk: "low, #481 ran cleanly for 6 days",
    fixResult: "Rollback to #481 complete. 5xx rate back to 0.2% within 2 minutes.",
    report: "Work item created: bad deploy #482, rollback to #481, follow-up to add a pricing test.",
  }),
  build({
    id: "memory-leak",
    label: "Memory leak",
    blurb: "No recent change. The metrics tell the story, so Diagnosis is confident on the first pass.",
    alert: "checkout-api restarted 6 times in one hour",
    resource: "checkout-api (AKS, 3 pods)",
    logs: "OOMKilled events on all three pods, roughly every 9 minutes.",
    metrics: "Memory climbs in a straight line from 300 MB to the 1 GB limit between restarts.",
    change: "No deploys or config changes in the last 48 hours.",
    confidence: 88,
    cause: "a memory leak in the running build, with no related change",
    fix: "restart the pods now and raise the memory limit to 2 GB as a stopgap",
    risk: "medium, a rolling restart briefly lowers capacity",
    fixResult: "Rolling restart complete and the new limit applied. Memory is stable at 380 MB.",
    report: "Work item created: suspected leak in checkout-api, stopgap applied, follow-up to profile the heap.",
  }),
  build({
    id: "db-connections",
    label: "Database connections",
    blurb: "A config change from two days ago finally bites under load. Diagnosis loops back once.",
    alert: "payments-api failing requests with timeouts",
    resource: "payments-api and its Azure SQL database",
    logs: "Timeouts waiting for a connection from the pool, 1,200 in 15 minutes.",
    logsDeeper: "Pool errors begin the moment morning traffic doubles, not at a fixed time.",
    metrics: "Database connections sit at 100 of 100. CPU on the database is only 30%.",
    change: "Config change 2 days ago lowered the connection pool size from 200 to 50.",
    firstConfidence: 70,
    whyUnsure: "The pool change fits, but the timing of the failures is not yet explained.",
    confidence: 93,
    cause: "the pool size was cut to 50 and now runs out under peak traffic",
    fix: "set the connection pool size back to 200 and restart the app",
    risk: "low, it restores the previous setting",
    fixResult: "Pool size restored. Connections peak at 140 of 200 and timeouts stop.",
    report: "Work item created: pool size regression, config restored, follow-up to load-test pool settings.",
  }),
];
