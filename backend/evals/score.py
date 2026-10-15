"""Score a reasoner on the captured incidents: did it name the right cause, and would the fix it leads to be right?

    python evals/score.py            # the rules-based baseline
    TRIAGE_REASONER=openai AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_DEPLOYMENT=... python evals/score.py

Each incident is scored at the first pass and again after the deeper look at the logs. After the deeper look a
reasoner must have decided (not ask for more) and be confident enough to act.
"""
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent.parent / "tests"), str(Path(__file__).parent.parent / "src")]

from envhelpers import alert  # noqa: E402
from test_rule_reasoner import findings  # noqa: E402
from triage.llm.rules import ENOUGH, RuleReasoner  # noqa: E402

EXPECTED = {
    "bad-deploy": ("bad-deploy", "rollback", {"to": "v481"}),
    "memory-leak": ("memory-leak", "restart", {"limit_mb": 2048}),
    "db-pool": ("pool-size", "set_pool", {"size": 8}),
}


def pick():
    if os.getenv("TRIAGE_REASONER") == "openai":
        from triage.llm.azure_openai import from_env

        return "azure-openai", from_env()
    return "rules", RuleReasoner()


def main() -> int:
    name, r = pick()
    print(f"reasoner: {name}\n{'incident':<12} {'pass':<7} {'kind':<12} {'conf':<6} {'asks more':<10} fix")
    wrong = 0
    for incident, (kind, fix_kind, fix_params) in EXPECTED.items():
        for deeper in (False, True):
            d = r.diagnose(alert(), findings(incident, deeper), 2 if deeper else 1)
            fix = r.propose_fix(alert(), d)
            right = d.kind == kind and fix.kind == fix_kind and fix.params == fix_params
            if deeper:
                right = right and not d.needs_more and d.confidence >= ENOUGH
                wrong += not right
            print(f"{incident:<12} {'deeper' if deeper else 'first':<7} {d.kind:<12} {d.confidence:<6} {str(d.needs_more):<10} {fix.kind}" + (f"  {'OK' if right else 'WRONG'}" if deeper else ""))
    print("\nall correct after the deeper look" if not wrong else f"\n{wrong} incident(s) wrong after the deeper look")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
