# One incident, step by step

What happens from the alert to the closed run. GitHub renders the diagram below.
The code behind each step is in `backend/src/triage/` (`graph.py` wires the steps, `agents.py` holds them).

```mermaid
sequenceDiagram
    autonumber
    participant AM as Azure Monitor
    participant API as Triage API
    participant T as Triage supervisor
    participant L as Logs agent
    participant M as Metrics agent
    participant C as Change agent
    participant D as Diagnosis agent
    participant R as Remediation agent
    participant G as Approval gate
    actor P as On-call engineer
    participant X as Action executor
    participant PM as Postmortem agent
    participant AZ as Azure (logs, metrics, activity log, resources)
    participant W as Work items (Azure DevOps)

    AM->>API: POST /alerts (common alert schema)
    API->>T: start run (alert)
    T->>T: plan: which agents, which resource

    par parallel evidence gathering
        T->>L: investigate
        L->>AZ: KQL over Log Analytics
        AZ-->>L: error rows
    and
        T->>M: investigate
        M->>AZ: request and gauge metrics
        AZ-->>M: samples
    and
        T->>C: investigate
        C->>AZ: Activity Log (deploys, config writes)
        AZ-->>C: changes
    end
    L-->>D: finding
    M-->>D: finding
    C-->>D: finding

    D->>D: reasoner weighs the findings, scores confidence
    loop while unsure and rounds are left (max 2)
        D->>L: second pass: full stack traces
        L->>AZ: deeper KQL
        AZ-->>L: more rows
        L-->>D: updated finding
        D->>D: reasoner weighs again
    end

    D->>R: diagnosis (kind, cause, confidence)
    R->>R: pick the fix from a fixed catalog
    R->>G: proposed fix and its risk
    G-->>API: run pauses (status: awaiting_approval)
    API-->>P: proposal shown in the UI
    P->>API: POST /runs/{id}/approval (approve or reject)
    API->>G: resume from the checkpoint

    alt approved
        G->>X: apply the fix
        X->>AZ: rollback, restart or set pool size
        AZ-->>X: result, then check the system recovered
        X->>PM: outcome (fixed, or applied but unhealthy)
    else rejected
        G->>PM: outcome (rejected)
    end

    PM->>PM: reasoner drafts the postmortem
    PM->>W: create work item
    PM-->>API: run completed
    API-->>P: summary and work item link
```

## Notes

- The Logs, Metrics and Change agents run at the same time. Diagnosis starts only when all three have reported.
- The loop is capped (`Deps.max_rounds`, default 2), so Diagnosis cannot ask forever.
- The pause at the approval gate is a LangGraph `interrupt`. The run's thread ends, and approving starts a new
  thread that resumes from the checkpoint. Nothing in the executor can run before a person decides.
- The Postmortem agent always runs, whether the fix worked, failed, was rejected or was not applicable.
- In Azure mode the Action executor is not wired yet, so an approved fix is reported as "not applied" and handed to a person.
- The work item sink is in-memory today (`DemoWorkItems`). The Azure DevOps connector is planned.
