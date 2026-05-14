import React, { useMemo } from 'react';
import StalenessBadge from '../StalenessBadge.jsx';
import EmptyState from '../EmptyState.jsx';
import NotConfigured from '../NotConfigured.jsx';
import { useResource } from '../../hooks/useResource.js';

function isOverdue(due) {
  if (!due) return false;
  const t = Date.parse(due);
  if (!Number.isFinite(t)) return false;
  return t < Date.now();
}

function formatDue(due) {
  if (!due) return '';
  const d = new Date(due);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function groupByList(items) {
  const groups = new Map();
  for (const it of items) {
    const key = it.list || it.list_name || 'Other';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(it);
  }
  return Array.from(groups.entries()).map(([name, entries]) => ({ name, entries }));
}

function ReminderRow({ item }) {
  const overdue = isOverdue(item.due);
  return (
    <li className="py-1.5 flex items-baseline gap-2">
      <span
        className="inline-block w-3 h-3 border rule-thin shrink-0 translate-y-0.5"
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <span className={`body-serif text-[14.5px] ${overdue ? 'text-[var(--accent)]' : ''}`}>
            {item.title || 'Untitled'}
          </span>
          {item.due && (
            <span
              className={`meta-sans tabular whitespace-nowrap ${overdue ? 'text-[var(--accent)]' : ''}`}
            >
              {overdue ? '· overdue · ' : ''}
              {formatDue(item.due)}
            </span>
          )}
        </div>
        {item.notes && <div className="meta-sans truncate">{item.notes}</div>}
      </div>
    </li>
  );
}

function Header({ timestamp, count }) {
  return (
    <header className="rule-after mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="section-eyebrow">The Checklist</div>
          <h3 className="headline text-[1.35rem] mt-1">Reminders &amp; To-Do</h3>
        </div>
        <div className="flex items-baseline gap-2">
          {count != null && <span className="meta-sans tabular">{count} open</span>}
          <StalenessBadge timestamp={timestamp} />
        </div>
      </div>
    </header>
  );
}

export default function Reminders() {
  const { data, error, loading, refresh } = useResource('/api/reminders');

  const groups = useMemo(() => {
    if (!data) return [];
    const items = (data.items || data.reminders || []).filter(
      (r) => !(r.completed === true || r.done === true)
    );
    // Overdue first within each list — easier to scan.
    const sorted = [...items].sort((a, b) => {
      const ao = isOverdue(a.due) ? 0 : 1;
      const bo = isOverdue(b.due) ? 0 : 1;
      if (ao !== bo) return ao - bo;
      const ad = a.due ? Date.parse(a.due) : Infinity;
      const bd = b.due ? Date.parse(b.due) : Infinity;
      return ad - bd;
    });
    return groupByList(sorted);
  }, [data]);

  if (loading && !data && !error) {
    return (
      <section>
        <Header />
        <p className="ink-loading body-serif">Gathering the day's tasks…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section>
        <Header />
        <EmptyState source="reminders" detail={error} onRetry={refresh} />
      </section>
    );
  }

  if (data && data.available === false) {
    if (data.reason) {
      return (
        <NotConfigured
          label="Reminders"
          hint="Grant Reminders access in System Settings → Privacy, or point REMINDERS_PATH at a synced JSON file."
          reason={data.reason}
        />
      );
    }
    return null;
  }
  if (!data) return null;

  if (!groups.length) return null; // collapse: nothing outstanding

  const totalOpen = groups.reduce((n, g) => n + g.entries.length, 0);
  const timestamp = data.collected_at || data.updated_at;

  return (
    <section>
      <Header timestamp={timestamp} count={totalOpen} />

      <div className="space-y-3">
        {groups.map((g) => (
          <div key={g.name}>
            <div className="meta-sans uppercase tracking-wider mb-1">{g.name}</div>
            <ul className="divide-y rule-thin border-t rule-thin border-b">
              {g.entries.slice(0, 8).map((item, i) => (
                <ReminderRow key={item.id || `${g.name}-${i}`} item={item} />
              ))}
            </ul>
          </div>
        ))}
      </div>

      <p className="byline mt-3">
        Filed from {data.source || 'Reminders'} · {totalOpen} open across {groups.length} list
        {groups.length === 1 ? '' : 's'}.
      </p>
    </section>
  );
}
