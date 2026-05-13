import { useCallback, useEffect, useState } from 'react';

/**
 * Read + mutate the connector list at /api/sources.
 *
 * Returned API:
 *   sources       — list of connector snapshots (see /api/sources)
 *   loading, error
 *   refresh()
 *   save(id, config)        — POST /api/sources/{id}/configure
 *   test(id)                — POST /api/sources/{id}/test  → returns the test result
 *   remove(id)              — DELETE /api/sources/{id}
 */
export function useSources({ active = true } = {}) {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/sources', { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setSources(data.sources || []);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    refresh();
  }, [active, refresh]);

  const save = useCallback(async (id, config) => {
    const r = await fetch(`/api/sources/${encodeURIComponent(id)}/configure`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    });
    if (!r.ok) {
      const detail = await safeDetail(r);
      throw new Error(detail);
    }
    const updated = await r.json();
    setSources((prev) => prev.map((s) => (s.id === id ? updated : s)));
    return updated;
  }, []);

  const test = useCallback(async (id) => {
    const r = await fetch(`/api/sources/${encodeURIComponent(id)}/test`, {
      method: 'POST',
      credentials: 'same-origin',
    });
    if (!r.ok) {
      const detail = await safeDetail(r);
      throw new Error(detail);
    }
    const data = await r.json();
    if (data.source) {
      setSources((prev) => prev.map((s) => (s.id === id ? data.source : s)));
    }
    return data.result;
  }, []);

  const remove = useCallback(async (id) => {
    const r = await fetch(`/api/sources/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });
    if (!r.ok) {
      const detail = await safeDetail(r);
      throw new Error(detail);
    }
    const data = await r.json();
    if (data.source) {
      setSources((prev) => prev.map((s) => (s.id === id ? data.source : s)));
    }
    return data;
  }, []);

  return { sources, loading, error, refresh, save, test, remove };
}

async function safeDetail(resp) {
  try {
    const j = await resp.json();
    return j.detail || j.error || `HTTP ${resp.status}`;
  } catch {
    return `HTTP ${resp.status}`;
  }
}
