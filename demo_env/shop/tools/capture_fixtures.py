"""Capture real telemetry from the shop for the backend's tests.

Runs the shop healthy for a while, breaks it, lets it suffer, then saves what its telemetry API would return.

    python tools/capture_fixtures.py <bad-deploy|memory-leak|db-pool> <output dir>
"""
import json
import sys
import time
from pathlib import Path

from shop.service import Shop

HEALTHY_FOR, BROKEN_FOR = 25, 40  # seconds

name, out = sys.argv[1], Path(sys.argv[2])
shop = Shop(backend_url=None)
shop.start()
time.sleep(HEALTHY_FOR)
shop.inject(name)
time.sleep(BROKEN_FOR)
shop.stop()

snapshot = {
    "scenario": name,
    "captured_at": time.time(),
    "logs": shop.t.logs_since(1800, "ERROR"),  # what /telemetry/logs?minutes=30&level=ERROR returns
    "metrics": shop.t.samples_since(1800),
    "changes": shop.t.changes_since(72 * 3600),
}
out.mkdir(parents=True, exist_ok=True)
(out / f"{name}.json").write_text(json.dumps(snapshot, indent=1))
print(f"{name}: {len(snapshot['logs'])} error logs, {len(snapshot['metrics'])} samples, {len(snapshot['changes'])} changes")
