import React from 'react';

function StatusDot({ state }) {
  const cls = state === 'running' ? 'dot-ok' : state === 'restarting' ? 'dot-warn' : 'dot-bad';
  return <span className={`dot ${cls}`} aria-label={state} />;
}

export default function InfraHealth({ data }) {
  if (!data) return <Skeleton title="Infrastructure" />;

  const { containers = [], containers_up = 0, containers_total = 0, containers_down = 0 } = data;

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">Infrastructure</div>
        <h3 className="headline text-[1.35rem] mt-1">The Container Beat</h3>
      </header>

      <div className="flex items-baseline gap-4 mb-3">
        <div>
          <div className="data-num text-3xl leading-none">{containers_up}<span className="text-inksoft text-base">/{containers_total}</span></div>
          <div className="meta-sans uppercase tracking-wider">running</div>
        </div>
        {containers_down > 0 && (
          <div>
            <div className="data-num text-3xl leading-none text-[var(--accent)]">{containers_down}</div>
            <div className="meta-sans uppercase tracking-wider">down</div>
          </div>
        )}
      </div>

      <ul className="text-[14px] body-serif divide-y rule-thin border-t rule-thin">
        {containers.slice(0, 12).map((c) => (
          <li key={c.name} className="flex items-center justify-between py-1.5">
            <span className="flex items-center gap-2">
              <StatusDot state={c.state} />
              <span className="tabular">{c.name}</span>
            </span>
            <span className="meta-sans">{c.restarts > 0 ? `↻ ${c.restarts}` : c.state}</span>
          </li>
        ))}
        {containers.length === 0 && (
          <li className="py-3 meta-sans italic">No container data — Prometheus may be quiet.</li>
        )}
      </ul>
    </section>
  );
}

function Skeleton({ title }) {
  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">{title}</div>
      </header>
      <p className="ink-loading body-serif">The presses are still warming…</p>
    </section>
  );
}
