import React, { useEffect, useRef, useState } from 'react';
import { useChat } from '../hooks/useChat.js';
import { toolLabel } from './toolLabels.js';

const STORAGE_OPEN = 'daily-bhavi:chat:open';

export default function ChatBar({ onLayoutChange }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const { messages, send, sending, clear, abort } = useChat({ onLayoutChange });

  // Restore last open/closed state for the session (not across days).
  useEffect(() => {
    if (sessionStorage.getItem(STORAGE_OPEN) === '1') setOpen(true);
  }, []);
  useEffect(() => {
    if (open) sessionStorage.setItem(STORAGE_OPEN, '1');
    else sessionStorage.removeItem(STORAGE_OPEN);
  }, [open]);

  // Auto-scroll to latest message
  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  // Esc to close, Cmd/Ctrl+K to open + focus
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape' && open) setOpen(false);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // Focus the input when the panel opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 80);
  }, [open]);

  function handleSubmit(e) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    send(text);
    setDraft('');
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      handleSubmit(e);
    }
  }

  const hasMessages = messages.length > 0;

  return (
    <>
      {/* Backdrop when open */}
      <div
        className={`fixed inset-0 z-30 bg-ink/10 transition-opacity duration-300 ${open ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      {/* Panel: bottom sheet on mobile, right-side rail on tablet+ */}
      <aside
        className={`chat-panel fixed z-40 bg-paper border rule-thick shadow-xl
                    transition-transform duration-300 ease-out
                    ${open ? 'translate-y-0 md:translate-x-0' : 'translate-y-full md:translate-y-0 md:translate-x-full'}`}
        role="dialog"
        aria-label="Chat with The Daily Bhavi editor"
      >
        <div className="flex flex-col h-full">
          <header className="px-4 py-3 flex items-center justify-between border-b rule-thick">
            <div>
              <div className="section-eyebrow">Editor's Desk</div>
              <div className="byline">Ask or edit · Cmd-K to summon</div>
            </div>
            <div className="flex items-center gap-2">
              {hasMessages && (
                <button
                  type="button"
                  onClick={clear}
                  className="meta-sans uppercase tracking-wider px-2 py-1.5 hover:underline"
                >
                  Clear
                </button>
              )}
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close chat"
                className="min-w-[44px] min-h-[44px] grid place-items-center hover:bg-paperdark rounded"
              >
                <span aria-hidden="true" className="text-xl leading-none">
                  ×
                </span>
              </button>
            </div>
          </header>

          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {!hasMessages && (
              <div className="py-6">
                <p className="body-serif italic mb-3">Welcome to the editor's desk. Try:</p>
                <ul className="space-y-1.5">
                  {[
                    'Hide the media section.',
                    'Move markets to the top.',
                    'How did I sleep last night?',
                    "What's the S&P doing today?",
                    'Reset the layout.',
                  ].map((q) => (
                    <li key={q}>
                      <button
                        type="button"
                        onClick={() => {
                          setDraft(q);
                          inputRef.current?.focus();
                        }}
                        className="text-left meta-sans hover:text-accent underline-offset-2 hover:underline"
                      >
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {messages.map((m) => (
              <Bubble key={m.id} msg={m} />
            ))}

            {sending &&
              messages[messages.length - 1]?.role === 'assistant' &&
              !messages[messages.length - 1]?.text && <TypingIndicator />}
          </div>

          <form
            onSubmit={handleSubmit}
            className="border-t rule-thick p-3 flex items-end gap-2 bg-paperdark/40"
          >
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask or edit…"
              rows={1}
              className="flex-1 bg-paper border rule-thin px-3 py-2 body-serif resize-none min-h-[44px] max-h-[120px]
                         focus:outline-none focus:border-ink"
            />
            {sending ? (
              <button
                type="button"
                onClick={abort}
                className="min-h-[44px] px-4 border rule-thick body-serif hover:bg-paperdark"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim()}
                className="min-h-[44px] px-4 border rule-thick body-serif hover:bg-paperdark disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Send
              </button>
            )}
          </form>
        </div>
      </aside>

      {/* Collapsed pill */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open chat with the editor"
        className={`chat-pill fixed z-30 bottom-4 left-1/2 -translate-x-1/2
                    bg-paperdark border rule-thick px-5 py-3 min-h-[48px]
                    flex items-center gap-3 shadow-md hover:bg-paper
                    transition-opacity duration-200 ${open ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}
      >
        <span aria-hidden="true" className="dot dot-ok" />
        <span className="byline not-italic">Ask or edit…</span>
        <span className="meta-sans hidden sm:inline">⌘K</span>
      </button>
    </>
  );
}

function Bubble({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] px-3.5 py-2 ${
          isUser ? 'bg-paperdark border rule-thin' : 'bg-paper border rule-thin'
        } `}
      >
        {msg.toolCalls?.length > 0 && (
          <div className="space-y-1 mb-2">
            {msg.toolCalls.map((tc) => (
              <ToolChip key={tc.id} call={tc} />
            ))}
          </div>
        )}
        {msg.text && (
          <p className="body-serif text-[15px] whitespace-pre-wrap leading-snug">{msg.text}</p>
        )}
        {msg.status === 'error' && (
          <p className="meta-sans text-accent italic mt-1">
            Trouble at the press — {msg.error || 'unknown error'}.
          </p>
        )}
      </div>
    </div>
  );
}

function ToolChip({ call }) {
  const label = toolLabel(call);
  const tone =
    call.status === 'error'
      ? 'border-accent text-accent'
      : call.status === 'running'
        ? 'border-rule-thick text-inksoft ink-loading'
        : 'border-rule-thick text-ink';
  return (
    <div
      className={`meta-sans uppercase tracking-wider px-2 py-1 border ${tone} inline-flex items-center gap-2`}
    >
      <span aria-hidden="true">
        {call.status === 'done' ? '✓' : call.status === 'error' ? '!' : '…'}
      </span>
      <span>{label}</span>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="px-3.5 py-2 border rule-thin bg-paper">
        <span className="ink-loading body-serif">Composing…</span>
      </div>
    </div>
  );
}
