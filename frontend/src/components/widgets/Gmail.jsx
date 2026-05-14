import React from 'react';
import StalenessBadge from '../StalenessBadge.jsx';
import EmptyState from '../EmptyState.jsx';
import { useResource } from '../../hooks/useResource.js';

function timeAgo(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const diff = Math.max(0, Date.now() - t) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function senderName(from) {
  if (!from) return '';
  // Pull "Name" out of "Name <addr@domain>" if present.
  const m = String(from).match(/^"?([^"<]+?)"?\s*<.+>$/);
  return (m ? m[1] : from).trim();
}

function MessageRow({ msg }) {
  return (
    <li className="py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="headline text-[0.95rem] leading-snug truncate">
          {msg.subject || '(no subject)'}
        </span>
        <span className="meta-sans tabular whitespace-nowrap">
          {timeAgo(msg.date || msg.received_at)}
        </span>
      </div>
      <div className="flex items-baseline justify-between gap-3 mt-0.5">
        <span className="meta-sans italic truncate">{senderName(msg.from)}</span>
        {msg.label && <span className="meta-sans tabular">{msg.label}</span>}
      </div>
      {msg.snippet && (
        <div className="body-serif text-[13px] mt-1 text-inksoft line-clamp-2 italic">
          {msg.snippet}
        </div>
      )}
    </li>
  );
}

function Header({ timestamp, unread }) {
  return (
    <header className="rule-after mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="section-eyebrow">Correspondence</div>
          <h3 className="headline text-[1.35rem] mt-1">Letters &amp; Inbox</h3>
        </div>
        <div className="flex items-baseline gap-2">
          {unread != null && <span className="meta-sans tabular">{unread} unread</span>}
          <StalenessBadge timestamp={timestamp} />
        </div>
      </div>
    </header>
  );
}

export default function Gmail() {
  const { data, error, loading, refresh } = useResource('/api/gmail');

  if (loading && !data && !error) {
    return (
      <section>
        <Header />
        <p className="ink-loading body-serif">Sorting the morning post…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section>
        <Header />
        <EmptyState source="email" detail={error} onRetry={refresh} />
      </section>
    );
  }

  if (!data || data.available === false) return null;

  const messages = (data.messages || data.unread || []).slice(0, 6);
  if (!messages.length) return null; // empty inbox → collapse

  const unread = data.unread_count ?? messages.length;
  const timestamp = data.collected_at || data.updated_at;

  return (
    <section>
      <Header timestamp={timestamp} unread={unread} />

      <ul className="divide-y rule-thin border-t rule-thin border-b">
        {messages.map((m, i) => (
          <MessageRow key={m.id || i} msg={m} />
        ))}
      </ul>

      <p className="byline mt-3">
        Filed from {data.source || 'Gmail'} · {unread} unread letter
        {unread === 1 ? '' : 's'} at the door.
      </p>
    </section>
  );
}
