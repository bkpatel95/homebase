import React from 'react';

function timeAgo(iso) {
  if (!iso) return '';
  const diff = (Date.now() - Date.parse(iso)) / 1000;
  if (Number.isNaN(diff)) return '';
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function Media({ data }) {
  if (!data?.available) return null;
  const recent = data.recently_added || [];
  const pending = data.pending_requests || [];

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">Arts & Leisure</div>
        <h3 className="headline text-[1.35rem] mt-1">The Marquee</h3>
      </header>

      {recent.length > 0 && (
        <>
          <div className="meta-sans uppercase tracking-wider mb-2">Recently added to Plex</div>
          <ul className="divide-y rule-thin border-t rule-thin border-b mb-3">
            {recent.slice(0, 6).map((m, i) => (
              <li key={i} className="py-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="body-serif text-[14px] truncate">{m.title}</span>
                  <span className="meta-sans whitespace-nowrap">{timeAgo(m.added_at)}</span>
                </div>
                {m.library && (
                  <div className="meta-sans">
                    {m.library}
                    {m.year ? ` · ${m.year}` : ''}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {pending.length > 0 && (
        <>
          <div className="meta-sans uppercase tracking-wider mb-2">Pending requests</div>
          <ul className="divide-y rule-thin border-t rule-thin border-b">
            {pending.map((p) => (
              <li key={p.id} className="py-1.5 flex items-baseline justify-between gap-3">
                <span className="body-serif text-[14px] truncate">{p.title}</span>
                <span className="meta-sans">{p.type}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="byline mt-3">Plex library{pending.length ? ' · Overseerr queue' : ''}.</p>
    </section>
  );
}
