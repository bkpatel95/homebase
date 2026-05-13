import { useEffect, useState, useCallback, useRef } from 'react';

const REFRESH_MS = 60_000;

export function useEdition() {
  const [edition, setEdition] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef(null);

  const fetchEdition = useCallback(async () => {
    try {
      const r = await fetch('/api/edition', { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setEdition(data);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEdition();
    timer.current = setInterval(fetchEdition, REFRESH_MS);
    return () => clearInterval(timer.current);
  }, [fetchEdition]);

  return { edition, error, loading, refresh: fetchEdition };
}
