from envhelpers import alert, env_deps_for, shop_client
from triage.connectors.env import EnvChanges, EnvLogs, EnvMetrics, signature


def evidence(name):
    shop, _ = shop_client(name)
    return EnvLogs(shop), EnvMetrics(shop), EnvChanges(shop)


def test_signature_groups_lines_that_differ_only_in_numbers():
    a = signature("Timeout waiting for a database connection from the pool (size=1, in use=1)")
    b = signature("Timeout waiting for a database connection from the pool (size=4, in use=3)")
    assert a == b


def test_bad_deploy_logs_name_the_failing_code_and_the_deeper_pass_adds_the_stack():
    logs, _, _ = evidence("bad-deploy")
    first = logs.query(alert())
    assert "PricingCalculator.apply_discount" in first.summary
    assert "stack trace" not in first.summary and "frames" not in first.detail
    deeper = logs.query(alert(), deeper=True)
    assert deeper.detail["frames"][0][0] == "pricing.py:apply_discount"
    assert "pricing.py:apply_discount" in deeper.summary


def test_bad_deploy_metrics_and_changes():
    _, metrics, changes = evidence("bad-deploy")
    m = metrics.query(alert())
    assert m.detail["error_rate_now"] > 0.15 and "5xx" in m.summary
    c = changes.recent(alert())
    assert c.detail["changes"][0]["meta"]["version"] == "v482"
    assert c.detail["changes"][0]["age_min"] < 5


def test_memory_leak_shows_up_as_restarts_and_climbing_memory_with_no_changes():
    logs, metrics, changes = evidence("memory-leak")
    assert "OOMKilled" in logs.query(alert()).summary
    m = metrics.query(alert())
    assert m.detail["restarts_last_minute"] >= 2 and m.detail["mem_slope_mb_per_min"] > 20
    assert "No deploys or config changes" in changes.recent(alert()).summary


def test_small_pool_shows_as_full_pool_timeouts_and_an_old_config_change():
    logs, metrics, changes = evidence("db-pool")
    assert "Timeout waiting for a database connection" in logs.query(alert()).summary
    assert logs.query(alert(), deeper=True).detail["pool_saturated"] is True
    m = metrics.query(alert())
    assert m.detail["db_util"] >= 0.9 and m.detail["p95_ms_now"] > 200
    change = changes.recent(alert()).detail["changes"][0]
    assert change["meta"]["setting"] == "pool_size" and 24 * 60 < change["age_min"] < 72 * 60


def test_actions_call_the_right_endpoint_and_none_does_nothing():
    from triage.models import FixProposal

    deps, calls = env_deps_for("bad-deploy")
    deps.actions.apply(alert(), FixProposal(action="x", risk="y", kind="rollback", params={"to": "v481"}))
    deps.actions.apply(alert(), FixProposal(action="x", risk="y", kind="set_pool", params={"size": 8}))
    deps.actions.apply(alert(), FixProposal(action="x", risk="y", kind="restart", params={"limit_mb": 2048}))
    assert calls == [("/actions/rollback", {"to": "v481"}), ("/actions/set-pool", {"size": "8"}), ("/actions/restart", {"limit_mb": "2048"})]
    calls.clear()
    result = deps.actions.apply(alert(), FixProposal(action="escalate", risk="none", kind="none"))
    assert calls == [] and not result.ok


def _actions_with_metrics(samples):
    """An Action connector whose shop returns the given metrics after the fix."""
    import httpx

    from triage.connectors.env import EnvActions, ShopClient

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"message": "Pool size set."})
        return httpx.Response(200, json=samples)

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://shop")
    return EnvActions(ShopClient("http://shop", http=http), verify_wait=3)


def _sample(error_rate, p95):
    return {"ts": 0, "rps": 25, "error_rate": error_rate, "p95_ms": p95, "mem_mb": 300, "restarts": 0, "db_in_use": 2, "db_pool": 8}


def test_a_fix_is_judged_on_the_settled_seconds_not_the_backlog_draining_at_first():
    from triage.models import FixProposal

    fix = FixProposal(action="x", risk="y", kind="set_pool", params={"size": 8})
    # the first seconds after the fix still show the old queue; the last three are healthy
    recovering = _actions_with_metrics([_sample(0.4, 330), _sample(0.2, 250), _sample(0.0, 110), _sample(0.0, 105), _sample(0.0, 100)])
    assert recovering.apply(alert(), fix).ok
    broken = _actions_with_metrics([_sample(0.4, 330)] * 5)
    result = broken.apply(alert(), fix)
    assert not result.ok and "still unhealthy" in result.message
