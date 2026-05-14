import React from 'react';

function Item({ label, value, suffix, status }) {
  const dot =
    {
      bad: 'dot-bad',
      warn: 'dot-warn',
      ok: 'dot-ok',
      idle: '',
    }[status] || '';
  return (
    <div className="ticker-item flex items-center gap-2 px-4 py-2 min-w-max">
      {dot && <span className={`dot ${dot}`} aria-hidden="true" />}
      <span className="section-eyebrow text-[10px]">{label}</span>
      <span className="data-num text-[13px]">{value}</span>
      {suffix && <span className="meta-sans">{suffix}</span>}
    </div>
  );
}

export default function Ticker({ edition }) {
  const items = edition?.ticker || [];
  return (
    <div className="ticker-rail overflow-x-auto -mx-2 sm:mx-0">
      <div className="flex items-stretch">
        {items.length === 0 && (
          <div className="px-4 py-2 meta-sans italic">Compiling the ticker…</div>
        )}
        {items.map((it, i) => (
          <Item key={`${it.label}-${i}`} {...it} />
        ))}
      </div>
    </div>
  );
}
