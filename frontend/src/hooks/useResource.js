import { useCallback, useEffect, useRef, useState } from 'react';

const DEFAULT_REFRESH_MS = 5 * 60 * 1000;

// Tiny self-refreshing fetcher used by self-contained widgets that pull
// straight from a dedicated endpoint (e.g. /api/weather). Returns the parsed
// JSON, an error string when the fetch failed, a loading flag, and a manual
// refresh handle for retry buttons.
export function useResource(url, { refreshMs = DEFAULT_REFRESH_MS } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef(null);
  const mounted = useRef(true);

  const fetchOnce = useCallback(async () => {
    try {
      const r = await fetch(url, { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      if (!mounted.current) return;
      setData(json);
      setError(null);
    } catch (e) {
      if (!mounted.current) return;
      setError(e.message || String(e));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    mounted.current = true;
    fetchOnce();
    if (refreshMs > 0) {
      timer.current = setInterval(fetchOnce, refreshMs);
    }
    return () => {
      mounted.current = false;
      if (timer.current) clearInterval(timer.current);
    };
  }, [fetchOnce, refreshMs]);

  return { data, error, loading, refresh: fetchOnce };
}
