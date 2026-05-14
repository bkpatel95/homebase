import React, { useEffect, useState } from 'react';

const FRESH_MS = 5 * 60 * 1000;
const STALE_MS = 30 * 60 * 1000;

export function stalenessLevel(ts) {
  if (!ts) return 'unknown';
  const parsed = typeof ts === 'number' ? ts : Date.parse(ts);
  if (!Number.isFinite(parsed)) return 'unknown';
  const age = Date.now() - parsed;
  if (age < FRESH_MS) return 'fresh';
  if (age < STALE_MS) return 'stale';
  return 'old';
}

function formatAge(ts) {
  if (!ts) return '';
  const parsed = typeof ts === 'number' ? ts : Date.parse(ts);
  if (!Number.isFinite(parsed)) return '';
  const diff = Math.max(0, Date.now() - parsed);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'moments ago';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// Subtle staleness indicator for a widget header. Every widget that fetches
// data uses this same component so the freshness signal is consistent across
// the broadsheet.
//
// - fresh (< 5 min):     green dot + "X min ago" / "moments ago"
// - stale (5–30 min):    amber dot + "X min ago"
// - very stale (> 30 min): red dot + "X min ago"
// - unknown timestamp:   nothing
export default function StalenessBadge({ timestamp, label = 'updated' }) {
  const [, force] = useState(0);

  // Re-render once a minute so the dot can transition between tiers and the
  // "X min ago" label keeps step. Widgets refresh on their own cadence too,
  // but this guarantees the badge keeps current even on a quiet feed.
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const level = stalenessLevel(timestamp);
  if (level === 'unknown') return null;

  const age = formatAge(timestamp);
  const toneClass =
    level === 'fresh' ? 'dot-ok' : level === 'stale' ? 'dot-warn' : 'dot-bad';
  const aria =
    level === 'fresh'
      ? `Data is fresh — ${label} ${age}`
      : level === 'stale'
        ? `Data is stale — ${label} ${age}`
        : `Data is very stale — ${label} ${age}`;

  return (
    <span
      className="inline-flex items-center gap-1 align-middle meta-sans"
      title={`${label} ${age}`}
      aria-label={aria}
    >
      <span className={`dot ${toneClass}`} />
      <span className="text-[10px] tabular">
        {label} {age}
      </span>
    </span>
  );
}
