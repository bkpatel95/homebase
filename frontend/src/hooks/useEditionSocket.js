import { useEffect, useRef } from 'react';

/**
 * Subscribe to /api/ws and call onDirty() whenever the server tells us the
 * edition has changed (e.g. the chat bar mutated layout). Auto-reconnects with
 * a small back-off so transient network blips don't leave us stale.
 *
 * The hook intentionally does not return any state — it's a side-effect
 * subscriber. The caller decides what to do when notified (typically refetch
 * /api/edition).
 */
export function useEditionSocket({ onDirty }) {
  const ref = useRef({ ws: null, retry: 0, closed: false });

  useEffect(() => {
    const state = ref.current;
    state.closed = false;

    function connect() {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${window.location.host}/api/ws`;
      const ws = new WebSocket(url);
      state.ws = ws;

      ws.addEventListener('open', () => {
        state.retry = 0;
      });
      ws.addEventListener('message', (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'edition_dirty') onDirty?.(msg);
        } catch {
          /* ignore non-JSON */
        }
      });
      ws.addEventListener('close', () => {
        if (state.closed) return;
        const wait = Math.min(15_000, 500 * 2 ** state.retry++);
        setTimeout(connect, wait);
      });
      ws.addEventListener('error', () => {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      });
    }

    connect();
    return () => {
      state.closed = true;
      try {
        state.ws?.close();
      } catch {
        /* noop */
      }
    };
  }, [onDirty]);
}
