import React from 'react';

export default function ProdHealth({ data }) {
  if (!data) {
    return (
      <section>
        <header className="rule-after mb-3">
          <div className="section-eyebrow">Operations Desk</div>
          <h3 className="headline text-[1.35rem] mt-1">Prod Health Report</h3>
        </header>
        <p className="ink-loading body-serif">Awaiting the morning audit…</p>
      </section>
    );
  }

  if (data.error) {
    return (
      <section>
        <header className="rule-after mb-3">
          <div className="section-eyebrow">Operations Desk</div>
          <h3 className="headline text-[1.35rem] mt-1">Prod Health Report</h3>
        </header>
        <p className="body-serif italic">No audit on file — {data.error}</p>
      </section>
    );
  }

  const issues = data.issues || [];
  const status =
    issues.length === 0
      ? 'All Clear'
      : `${issues.length} Item${issues.length === 1 ? '' : 's'} of Note`;

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">Operations Desk</div>
        <h3 className="headline text-[1.35rem] mt-1">Prod Health Report</h3>
      </header>

      <div className="flex items-baseline gap-3 mb-2">
        <span className={`dot ${issues.length ? 'dot-warn' : 'dot-ok'}`} />
        <span className="data-num text-xl">{status}</span>
      </div>

      <p className="byline">Audit filed {timeAgo(data.timestamp)}</p>

      {issues.length > 0 && (
        <ul className="mt-3 list-disc pl-5 body-serif text-[14px] space-y-1">
          {issues.slice(0, 8).map((it, i) => (
            <li key={i}>{typeof it === 'string' ? it : it.message || JSON.stringify(it)}</li>
          ))}
        </ul>
      )}

      {data.summary && <p className="body-serif text-[14px] mt-3 italic">{data.summary}</p>}
    </section>
  );
}

function timeAgo(iso) {
  if (!iso) return 'at an unknown hour';
  const diff = (Date.now() - Date.parse(iso)) / 1000;
  if (Number.isNaN(diff)) return 'recently';
  if (diff < 60) return 'moments ago';
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
