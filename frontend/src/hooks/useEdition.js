import { useEffect, useState, useCallback, useRef } from 'react';

const REFRESH_MS = 60_000;
const ERROR_REFRESH_MS = 10_000;
// Two failures in a row (~10s apart) is enough to call it "reconnecting"
// without flipping UI on a single transient blip.
const RECONNECTING_THRESHOLD = 2;

export function useEdition() {
  const [edition, setEdition] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);
  const timer = useRef(null);
  const failures = useRef(0);

  const scheduleNext = useCallback((fn, delay) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(fn, delay);
  }, []);

  const fetchEdition = useCallback(async () => {
    try {
      const r = await fetch('/api/edition', { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setEdition(data);
      setError(null);
      setReconnecting(false);
      failures.current = 0;
      scheduleNext(fetchEdition, REFRESH_MS);
    } catch (e) {
      failures.current += 1;
      setError(e.message || String(e));
      if (failures.current >= RECONNECTING_THRESHOLD) {
        setReconnecting(true);
        // Hand recovery polling to the SW so it keeps probing /api/health
        // even if this tab is backgrounded. The SW posts back when the
        // backend returns, and the listener below reloads us cleanly.
        navigator.serviceWorker?.controller?.postMessage({
          type: 'backend-error',
        });
      }
      scheduleNext(fetchEdition, ERROR_REFRESH_MS);
    } finally {
      setLoading(false);
    }
  }, [scheduleNext]);

  useEffect(() => {
    fetchEdition();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [fetchEdition]);

  // iOS PWAs throttle/suspend background timers aggressively — when the
  // user reopens the app or the device comes back online, force a fresh
  // probe instead of waiting for the next scheduled tick.
  useEffect(() => {
    const onWake = () => {
      if (document.visibilityState === 'visible') fetchEdition();
    };
    document.addEventListener('visibilitychange', onWake);
    window.addEventListener('online', onWake);
    return () => {
      document.removeEventListener('visibilitychange', onWake);
      window.removeEventListener('online', onWake);
    };
  }, [fetchEdition]);

  // SW pings us when /api/health recovers after a failure window. Reload
  // so the network-first nav handler pulls a fresh shell and we drop any
  // stale in-memory state — that's the recovery path that fixes the iOS
  // "Load failed" stickiness.
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return;
    const handler = (event) => {
      if (event.data?.type === 'backend-recovered') {
        window.location.reload();
      }
    };
    navigator.serviceWorker.addEventListener('message', handler);
    return () => navigator.serviceWorker.removeEventListener('message', handler);
  }, []);

  return { edition, error, loading, reconnecting, refresh: fetchEdition };
}
