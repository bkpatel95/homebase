import { useCallback, useEffect, useRef, useState } from 'react';

const SID_KEY = 'daily-bhavi:chat:sid';

function getSessionId() {
  let sid = localStorage.getItem(SID_KEY);
  if (!sid) {
    sid = (crypto?.randomUUID?.() || `s_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
    localStorage.setItem(SID_KEY, sid);
  }
  return sid;
}

/**
 * Manages the chat conversation.
 *
 * Messages shape:
 *   { id, role: 'user' | 'assistant' | 'system',
 *     text: string,           // accumulated text (streamed in deltas)
 *     toolCalls: [{name,input,output,status}],
 *     status: 'pending' | 'done' | 'error',
 *     error?: string }
 *
 * The send() call:
 *  - appends a user message,
 *  - appends a placeholder assistant message,
 *  - opens a POST to /api/chat that returns text/event-stream,
 *  - parses SSE events, appending text to the assistant message,
 *  - records tool_use / tool_result events so the UI can show
 *    "Updating layout..." chips inside the assistant bubble.
 *
 * Returns: { messages, send, sending, error, clear, sessionId }
 */
export function useChat({ onLayoutChange } = {}) {
  const [sessionId] = useState(getSessionId);
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  // Rehydrate any prior session transcript so refreshes don't lose context.
  useEffect(() => {
    let alive = true;
    fetch(`/api/chat/${encodeURIComponent(sessionId)}`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!alive || !data?.messages) return;
        setMessages(data.messages.map((m, i) => ({
          id: `hist-${i}`,
          role: m.role,
          text: m.text,
          toolCalls: [],
          status: 'done',
        })));
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId]);

  const clear = useCallback(async () => {
    abortRef.current?.abort();
    setMessages([]);
    setError(null);
    setSending(false);
    try { await fetch(`/api/chat/${encodeURIComponent(sessionId)}`, { method: 'DELETE', credentials: 'same-origin' }); }
    catch { /* noop */ }
  }, [sessionId]);

  const send = useCallback(async (text) => {
    const trimmed = (text || '').trim();
    if (!trimmed || sending) return;

    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: trimmed, toolCalls: [], status: 'done' };
    const asstId = `a-${Date.now()}`;
    const asstMsg = { id: asstId, role: 'assistant', text: '', toolCalls: [], status: 'pending' };
    setMessages((prev) => [...prev, userMsg, asstMsg]);
    setSending(true);
    setError(null);

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify({ session_id: sessionId, message: trimmed }),
        signal: ac.signal,
      });

      if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try { const j = await resp.json(); detail = j.detail || j.error || detail; } catch { /* noop */ }
        throw new Error(detail);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      // Track whether we've reported a layout change so we only toast once
      // per send (multiple update_layout calls in one turn → one toast).
      let layoutChanged = false;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // Split on SSE message boundary
        const events = buf.split('\n\n');
        buf = events.pop() ?? '';
        for (const ev of events) {
          const line = ev.split('\n').find((l) => l.startsWith('data:'));
          if (!line) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let data;
          try { data = JSON.parse(payload); } catch { continue; }
          handleEvent(data);
        }
      }

      function handleEvent(ev) {
        setMessages((prev) => prev.map((m) => {
          if (m.id !== asstId) return m;
          if (ev.type === 'text') {
            return { ...m, text: (m.text || '') + (ev.delta || '') };
          }
          if (ev.type === 'tool_use') {
            return { ...m, toolCalls: [...m.toolCalls, { id: ev.id, name: ev.tool, input: ev.input, status: 'running' }] };
          }
          if (ev.type === 'tool_result') {
            return {
              ...m,
              toolCalls: m.toolCalls.map((tc) =>
                tc.id === ev.id ? { ...tc, output: ev.output, status: ev.output?.ok === false ? 'error' : 'done' } : tc
              ),
            };
          }
          if (ev.type === 'error') {
            return { ...m, status: 'error', error: ev.message };
          }
          if (ev.type === 'done') {
            return { ...m, status: 'done' };
          }
          return m;
        }));

        if (ev.type === 'tool_use' && ev.tool === 'update_layout') layoutChanged = true;
        if (ev.type === 'tool_use' && ev.tool === 'update_ticker') layoutChanged = true;
      }

      if (layoutChanged) onLayoutChange?.();
    } catch (e) {
      if (e.name === 'AbortError') return;
      setError(e.message || String(e));
      setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, status: 'error', error: e.message || 'Failed' } : m));
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }, [sending, sessionId, onLayoutChange]);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setSending(false);
  }, []);

  return { messages, send, sending, error, clear, abort, sessionId };
}
