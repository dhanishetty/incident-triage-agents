import { useCallback, useEffect, useRef, useState } from "react";
import type { RunApi, ShopStatus } from "./runApi";
import { scenarios } from "./scenarios";
import { useRunStream } from "./useRunStream";

const POLL_MS = 1500;

// The demo environment mode. You break the real shop service; its own alert rule fires a webhook at the backend,
// which starts a run. This hook watches for that run to appear and follows it.
export function useEnvironmentRun(focusIds: Set<string>, enabled: boolean): RunApi {
  const stream = useRunStream(focusIds);
  const [shop, setShop] = useState<ShopStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const seen = useRef<Set<string> | null>(null); // runs that existed before, so only a new alert's run is followed
  const busyRef = useRef(false);
  busyRef.current = stream.busy;
  const { attach, reset } = stream;

  useEffect(() => {
    if (!enabled) {
      seen.current = null;
      return;
    }
    let stop = false;
    const tick = async () => {
      try {
        const [s, runs] = await Promise.all([
          fetch("/shop/status").then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status))))),
          fetch("/api/runs").then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status))))),
        ]);
        if (stop) return;
        setShop(s);
        setError(null);
        const ids: string[] = runs.map((r: { id: string }) => r.id);
        if (seen.current === null) {
          seen.current = new Set(ids); // the first look only records what is already there
          return;
        }
        const fresh = ids.filter((id) => !seen.current!.has(id));
        if (fresh.length && !busyRef.current) {
          const id = fresh[fresh.length - 1];
          fresh.forEach((f) => seen.current!.add(f));
          attach(id);
        }
      } catch {
        if (!stop) setError("The demo environment is not reachable. Is the shop container running?");
      }
    };
    tick();
    const t = window.setInterval(tick, POLL_MS);
    return () => {
      stop = true;
      window.clearInterval(t);
    };
  }, [enabled, attach]);

  const call = useCallback(async (path: string) => {
    setActing(true);
    try {
      const res = await fetch(path, { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      setShop(await fetch("/shop/status").then((r) => r.json()));
      setError(null);
    } catch {
      setError("The demo environment did not answer. Is the shop container running?");
    } finally {
      setActing(false);
    }
  }, []);

  return {
    mode: "environment",
    scenarios,
    scenario: scenarios[0],
    pick: () => {},
    view: stream.view,
    log: stream.log,
    stepTitle: stream.stepTitle,
    statusText: error ?? stream.error ?? undefined,
    idx: stream.idx,
    playing: stream.phase === "running",
    waiting: stream.phase === "awaiting_approval",
    finished: stream.phase === "completed" || stream.phase === "failed",
    speed: 1,
    setSpeed: () => {},
    play: () => {},
    pause: () => {},
    next: () => {},
    decide: stream.decide,
    reset,
    environment: {
      status: shop,
      acting,
      breakIt: (fault: string) => call(`/shop/faults/${fault}`),
      heal: async () => {
        reset();
        seen.current = null; // look again from scratch, so the run that is still listed is not followed
        await call("/shop/reset");
      },
    },
  };
}
