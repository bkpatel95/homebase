import React from 'react';

function Bar({ pct }) {
  const v = Math.max(0, Math.min(100, pct ?? 0));
  return (
    <div className="h-1.5 w-full bg-paperdark border rule-thin overflow-hidden">
      <div className="h-full bg-ink" style={{ width: `${v}%` }} />
    </div>
  );
}

function Stat({ label, value, unit, pct }) {
  return (
    <div className="py-2">
      <div className="flex items-baseline justify-between">
        <div className="meta-sans uppercase tracking-wider">{label}</div>
        <div className="data-num text-xl">
          {value != null ? value : '—'}
          {value != null && unit && <span className="text-sm font-normal text-inksoft ml-0.5">{unit}</span>}
        </div>
      </div>
      {pct != null && <div className="mt-1.5"><Bar pct={pct} /></div>}
    </div>
  );
}

function fmtUptime(secs) {
  if (!secs && secs !== 0) return null;
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  if (d > 0) return `${d}d ${h}h`;
  const m = Math.floor((secs % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function SystemMetrics({ data }) {
  if (!data) {
    return (
      <section>
        <header className="rule-after mb-3">
          <div className="section-eyebrow">The Pulse</div>
          <h3 className="headline text-[1.35rem] mt-1">System Metrics</h3>
        </header>
        <p className="ink-loading body-serif">Waiting on Prometheus…</p>
      </section>
    );
  }

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">The Pulse</div>
        <h3 className="headline text-[1.35rem] mt-1">System Metrics</h3>
      </header>

      <div className="divide-y rule-thin border-t rule-thin border-b">
        <Stat label="CPU"        value={fmt(data.cpu_pct, 1)} unit="%" pct={data.cpu_pct} />
        <Stat label="Memory"     value={fmt(data.mem_pct, 1)} unit="%" pct={data.mem_pct} />
        <Stat label="Disk (/)"   value={fmt(data.disk_pct, 1)} unit="%" pct={data.disk_pct} />
        <Stat label="Load avg"   value={fmt(data.load1, 2)} />
        <Stat label="Uptime"     value={fmtUptime(data.uptime_seconds)} />
      </div>

      <p className="byline mt-3">
        From the Prometheus wire · refreshed {refreshedAgo(data.collected_at)}
      </p>
    </section>
  );
}

function fmt(n, digits = 1) {
  if (n == null || Number.isNaN(n)) return null;
  return Number(n).toFixed(digits);
}

function refreshedAgo(iso) {
  if (!iso) return 'recently';
  const diff = (Date.now() - Date.parse(iso)) / 1000;
  if (diff < 60) return 'moments ago';
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}
