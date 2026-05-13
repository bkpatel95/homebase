import React, { useEffect, useMemo, useState } from 'react';
import { useSources } from '../hooks/useSources.js';

const STATUS_LABEL = {
  connected: 'Connected',
  disconnected: 'Not configured',
  error: 'Error',
};

const STATUS_DOT = {
  connected: 'dot-ok',
  disconnected: 'dot-warn',
  error: 'dot-bad',
};

const CATEGORY_ORDER = ['infra', 'data', 'personal', 'media'];
const CATEGORY_LABEL = {
  infra: 'Infrastructure',
  data: 'Data & Markets',
  personal: 'Personal',
  media: 'Media',
};

export default function SourcesPanel({ open, onClose, onChange }) {
  const { sources, loading, error, refresh, save, test, remove } = useSources({ active: open });
  const [selectedId, setSelectedId] = useState(null);
  const [flash, setFlash] = useState(null);

  // Reset selection when panel closes
  useEffect(() => {
    if (!open) setSelectedId(null);
  }, [open]);

  // Esc to close
  useEffect(() => {
    if (!open) return;
    function onKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const selected = useMemo(
    () => sources.find((s) => s.id === selectedId) || null,
    [sources, selectedId]
  );

  const grouped = useMemo(() => {
    const m = new Map();
    for (const s of sources) {
      const k = s.category || 'data';
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(s);
    }
    return CATEGORY_ORDER
      .map((k) => [k, m.get(k) || []])
      .concat(
        Array.from(m.entries()).filter(([k]) => !CATEGORY_ORDER.includes(k))
      );
  }, [sources]);

  function flashMsg(text, tone = 'ok') {
    setFlash({ text, tone });
    window.setTimeout(() => setFlash(null), 3000);
  }

  async function handleSave(id, config) {
    try {
      await save(id, config);
      flashMsg('Saved.', 'ok');
      onChange?.();
    } catch (e) {
      flashMsg(`Save failed: ${e.message}`, 'bad');
    }
  }

  async function handleTest(id) {
    try {
      const result = await test(id);
      flashMsg(
        result?.ok ? `Test ok: ${result.detail || 'reachable'}` : `Test failed: ${result?.detail || 'unknown'}`,
        result?.ok ? 'ok' : 'bad'
      );
      return result;
    } catch (e) {
      flashMsg(`Test error: ${e.message}`, 'bad');
      return { ok: false, detail: e.message };
    }
  }

  async function handleRemove(id) {
    try {
      await remove(id);
      flashMsg('Stored config removed.', 'ok');
      onChange?.();
    } catch (e) {
      flashMsg(`Remove failed: ${e.message}`, 'bad');
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-30 bg-ink/20 transition-opacity duration-200 ${open ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={`sources-panel fixed z-40 bg-paper border rule-thick shadow-xl flex flex-col
                    transition-transform duration-300 ease-out
                    ${open ? 'translate-x-0' : '-translate-x-full md:-translate-x-full'}`}
        role="dialog"
        aria-label="Manage data sources"
      >
        <header className="px-4 py-3 flex items-center justify-between border-b rule-thick">
          <div>
            <div className="section-eyebrow">Sources</div>
            <div className="byline">Connect or disconnect data feeds</div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={refresh}
              className="meta-sans uppercase tracking-wider px-2 py-1.5 hover:underline"
            >Refresh</button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close sources panel"
              className="min-w-[44px] min-h-[44px] grid place-items-center hover:bg-paperdark rounded"
            >
              <span aria-hidden="true" className="text-xl leading-none">×</span>
            </button>
          </div>
        </header>

        {flash && (
          <div className={`px-4 py-2 meta-sans border-b rule-thin ${flash.tone === 'bad' ? 'text-accent' : ''}`}>
            {flash.text}
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {loading && <p className="ink-loading body-serif text-center py-10">Loading sources…</p>}
          {error && <p className="body-serif italic text-center py-10 text-accent">{error}</p>}

          {!loading && !error && !selected && (
            <div className="px-4 py-3 space-y-5">
              {grouped.map(([cat, list]) => (
                list.length === 0 ? null : (
                  <section key={cat}>
                    <div className="section-eyebrow mb-2">{CATEGORY_LABEL[cat] || cat}</div>
                    <ul className="space-y-2">
                      {list.map((s) => (
                        <li key={s.id}>
                          <button
                            type="button"
                            onClick={() => setSelectedId(s.id)}
                            className="w-full text-left bg-paper border rule-thin hover:border-rule-thick px-3 py-2.5 flex items-start gap-3"
                          >
                            <span aria-hidden="true" className="text-lg leading-none mt-0.5 w-6 text-center">{s.icon}</span>
                            <span className="flex-1 min-w-0">
                              <span className="flex items-center justify-between gap-2">
                                <span className="headline text-[1rem] truncate">{s.name}</span>
                                <StatusPill status={s.status} />
                              </span>
                              <span className="byline block truncate">{s.description}</span>
                              <span className="meta-sans block mt-1 truncate">
                                {s.last_sync
                                  ? `Last sync ${formatRelative(s.last_sync)}`
                                  : s.configured
                                    ? 'Not yet synced'
                                    : 'Not configured'}
                                {s.last_error && (
                                  <span className="text-accent"> · {truncate(s.last_error, 60)}</span>
                                )}
                              </span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                )
              ))}
              {sources.length === 0 && (
                <p className="body-serif italic text-center py-10">No connectors registered.</p>
              )}
            </div>
          )}

          {selected && (
            <ConnectorEditor
              key={selected.id}
              source={selected}
              onBack={() => setSelectedId(null)}
              onSave={(config) => handleSave(selected.id, config)}
              onTest={() => handleTest(selected.id)}
              onRemove={() => handleRemove(selected.id)}
            />
          )}
        </div>
      </aside>
    </>
  );
}

function StatusPill({ status }) {
  return (
    <span className="meta-sans inline-flex items-center gap-1.5 uppercase tracking-wider whitespace-nowrap">
      <span className={`dot ${STATUS_DOT[status] || 'dot-warn'}`} aria-hidden="true" />
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function ConnectorEditor({ source, onBack, onSave, onTest, onRemove }) {
  // Seed from stored values; fall back to defaults from the schema (the user
  // can see what the field "would be" without those values committed yet).
  const initial = useMemo(() => {
    const out = {};
    for (const f of source.config_schema || []) {
      const stored = source.values?.[f.name];
      if (stored?.set) {
        // We only echo non-secret previews; passwords stay blank.
        out[f.name] = stored.preview || '';
      } else {
        out[f.name] = '';
      }
    }
    return out;
  }, [source]);

  const [draft, setDraft] = useState(initial);
  const [submitting, setSubmitting] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  function update(name, value) {
    setDraft((prev) => ({ ...prev, [name]: value }));
  }

  async function handleSave(e) {
    e?.preventDefault();
    setSubmitting(true);
    try {
      // Only send non-empty values. Empty fields keep the env_fallback in play
      // and don't shadow it with a stored empty string.
      const config = {};
      for (const [k, v] of Object.entries(draft)) {
        if (v !== '' && v != null) config[k] = v;
      }
      await onSave(config);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTest() {
    setSubmitting(true);
    try { await onTest(); } finally { setSubmitting(false); }
  }

  async function handleRemove() {
    setSubmitting(true);
    try { await onRemove(); } finally { setSubmitting(false); setConfirmRemove(false); }
  }

  const schema = source.config_schema || [];

  return (
    <form onSubmit={handleSave} className="px-4 py-3 space-y-4">
      <button
        type="button"
        onClick={onBack}
        className="meta-sans uppercase tracking-wider hover:underline -ml-1 px-1"
      >← All sources</button>

      <header>
        <div className="flex items-center gap-2 mb-1">
          <span aria-hidden="true" className="text-xl">{source.icon}</span>
          <h3 className="headline text-[1.4rem]">{source.name}</h3>
        </div>
        <p className="body-serif text-[15px] leading-snug">{source.description}</p>
        <p className="meta-sans mt-2">
          Feeds: {(source.widget_ids || []).join(', ') || '—'}
        </p>
      </header>

      <div className="meta-sans flex items-center gap-3 border rule-thin px-3 py-2 bg-paperdark/40">
        <StatusPill status={source.status} />
        {source.last_sync && <span>Last sync {formatRelative(source.last_sync)}</span>}
        {source.last_tested_at && <span>Tested {formatRelative(source.last_tested_at)}</span>}
      </div>

      {source.last_error && (
        <p className="meta-sans text-accent border-l-2 border-accent pl-2">{source.last_error}</p>
      )}

      {schema.length === 0 ? (
        <p className="body-serif italic">This connector needs no configuration.</p>
      ) : (
        <div className="space-y-3">
          {schema.map((f) => {
            const valueState = source.values?.[f.name];
            return (
              <Field
                key={f.name}
                field={f}
                value={draft[f.name] ?? ''}
                onChange={(v) => update(f.name, v)}
                valueState={valueState}
              />
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-2 border-t rule-thin">
        <button
          type="submit"
          disabled={submitting}
          className="min-h-[44px] px-4 border rule-thick body-serif hover:bg-paperdark disabled:opacity-40"
        >Save</button>
        <button
          type="button"
          onClick={handleTest}
          disabled={submitting}
          className="min-h-[44px] px-4 border rule-thin body-serif hover:bg-paperdark disabled:opacity-40"
        >Test connection</button>
        <span className="flex-1" />
        {!confirmRemove ? (
          <button
            type="button"
            onClick={() => setConfirmRemove(true)}
            className="meta-sans uppercase tracking-wider px-2 py-1 hover:underline text-accent"
          >Remove</button>
        ) : (
          <span className="meta-sans flex items-center gap-2">
            Remove stored config?
            <button
              type="button"
              onClick={handleRemove}
              disabled={submitting}
              className="meta-sans uppercase tracking-wider px-2 py-1 border rule-thin hover:bg-paperdark text-accent"
            >Yes, remove</button>
            <button
              type="button"
              onClick={() => setConfirmRemove(false)}
              className="meta-sans uppercase tracking-wider px-2 py-1 hover:underline"
            >Cancel</button>
          </span>
        )}
      </div>
    </form>
  );
}

function Field({ field, value, onChange, valueState }) {
  const { name, label, type = 'string', help, placeholder, required, env_fallback } = field;
  const fromEnv = !!valueState?.from_env;
  const isSecret = type === 'password';

  const inputProps = {
    id: `src-field-${name}`,
    value,
    placeholder: placeholder || (fromEnv ? '(provided by environment)' : ''),
    onChange: (e) => onChange(e.target.value),
    className: 'w-full bg-paper border rule-thin px-3 py-2 body-serif focus:outline-none focus:border-ink',
  };

  return (
    <div>
      <label htmlFor={`src-field-${name}`} className="meta-sans uppercase tracking-wider flex items-center justify-between mb-1">
        <span>{label}{required && <span className="text-accent"> *</span>}</span>
        {fromEnv && <span className="italic normal-case tracking-normal">using ${env_fallback}</span>}
      </label>
      {type === 'textarea' ? (
        <textarea {...inputProps} rows={5} />
      ) : (
        <input
          {...inputProps}
          type={isSecret ? 'password' : (type === 'number' ? 'number' : 'text')}
          autoComplete={isSecret ? 'new-password' : 'off'}
        />
      )}
      {help && <p className="byline mt-1">{help}</p>}
    </div>
  );
}

function formatRelative(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
    return d.toLocaleString();
  } catch { return iso; }
}

function truncate(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
