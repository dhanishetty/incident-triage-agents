"""The reasoner works from structured evidence, so these tests feed it what the connectors really return."""
import pytest

from envhelpers import alert, shop_client
from triage.connectors.env import EnvChanges, EnvLogs, EnvMetrics
from triage.llm.rules import ENOUGH, RuleReasoner
from triage.models import Finding


def findings(name: str, deeper: bool) -> dict[str, Finding]:
    shop, _ = shop_client(name)
    a = alert()
    out = {}
    for agent, ev in (("logs", EnvLogs(shop).query(a, deeper=deeper)), ("metrics", EnvMetrics(shop).query(a)), ("change", EnvChanges(shop).recent(a))):
        out[agent] = Finding(agent=agent, summary=ev.summary, round=2 if deeper and agent == "logs" else 1, detail=ev.detail)
    return out


r = RuleReasoner()


def test_bad_deploy_is_unsure_until_the_stack_trace_is_in():
    first = r.diagnose(alert(), findings("bad-deploy", deeper=False), 1)
    assert first.kind == "bad-deploy" and first.confidence < ENOUGH and first.needs_more and first.reason
    second = r.diagnose(alert(), findings("bad-deploy", deeper=True), 2)
    assert second.confidence >= ENOUGH and not second.needs_more
    assert "v482" in second.cause and second.params["rollback_to"] == "v481"


def test_memory_leak_is_confident_on_the_first_pass():
    d = r.diagnose(alert(), findings("memory-leak", deeper=False), 1)
    assert d.kind == "memory-leak" and d.confidence >= ENOUGH and not d.needs_more
    assert "nothing was deployed" in d.cause


def test_small_pool_is_unsure_until_the_deeper_pass_confirms_saturation():
    first = r.diagnose(alert(), findings("db-pool", deeper=False), 1)
    assert first.kind == "pool-size" and first.needs_more
    second = r.diagnose(alert(), findings("db-pool", deeper=True), 2)
    assert second.confidence >= ENOUGH and "from 8 to 1" in second.cause and second.params == {"from": 8, "to": 1}


@pytest.mark.parametrize("name,kind,fix_kind", [("bad-deploy", "bad-deploy", "rollback"), ("memory-leak", "memory-leak", "restart"), ("db-pool", "pool-size", "set_pool")])
def test_each_diagnosis_leads_to_the_matching_fix(name, kind, fix_kind):
    d = r.diagnose(alert(), findings(name, deeper=True), 2)
    fix = r.propose_fix(alert(), d)
    assert d.kind == kind and fix.kind == fix_kind


def test_a_healthy_system_gives_no_diagnosis_and_no_automatic_fix():
    healthy = {
        "logs": Finding(agent="logs", summary="No errors.", detail={"total": 0, "signatures": [], "deeper": False}),
        "metrics": Finding(agent="metrics", summary="All metrics look normal.", detail={"error_rate_now": 0.0, "db_util": 0.2}),
        "change": Finding(agent="change", summary="No changes.", detail={"changes": []}),
    }
    d = r.diagnose(alert(), healthy, 1)
    assert d.kind == "unknown" and d.confidence < ENOUGH
    assert r.propose_fix(alert(), d).kind == "none"


def test_the_postmortem_says_whether_the_fix_was_applied():
    d = r.diagnose(alert(), findings("bad-deploy", deeper=True), 2)
    fix = r.propose_fix(alert(), d)
    assert "Applied" in r.postmortem(alert(), d, fix, "fixed").summary
    assert "Not applied" in r.postmortem(alert(), d, fix, "not fixed").summary
