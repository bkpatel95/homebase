import React, { useMemo } from 'react';
import StalenessBadge from '../StalenessBadge.jsx';
import EmptyState from '../EmptyState.jsx';
import { useResource } from '../../hooks/useResource.js';

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function fmtTemp(t) {
  if (t == null || Number.isNaN(Number(t))) return '—';
  return `${Math.round(Number(t))}°`;
}

function fmtRange(hi, lo) {
  if (hi == null && lo == null) return '';
  return `${fmtTemp(hi)} / ${fmtTemp(lo)}`;
}

function weekdayLabel(iso, i) {
  if (i === 0) return 'Today';
  if (!iso) return '';
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso);
  if (Number.isNaN(d.getTime())) return '';
  return WEEKDAY[d.getDay()];
}

// Small sparkline of the day's hourly temperatures. Pure SVG so it follows
// the same ink-on-paper aesthetic as the rest of the page.
function HourlyTrend({ hourly }) {
  const points = useMemo(() => {
    if (!hourly || hourly.length < 2) return null;
    const temps = hourly.map((h) => Number(h.temp)).filter((n) => Number.isFinite(n));
    if (temps.length < 2) return null;
    const min = Math.min(...temps);
    const max = Math.max(...temps);
    const span = max - min || 1;
    const w = 200;
    const h = 36;
    const step = w / (temps.length - 1);
    const coords = temps.map((t, i) => {
      const x = i * step;
      const y = h - ((t - min) / span) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return {
      path: coords.join(' '),
      w,
      h,
      min,
      max,
      first: temps[0],
      last: temps[temps.length - 1],
    };
  }, [hourly]);

  if (!points) return null;

  return (
    <div className="flex items-end gap-2 mt-2">
      <span className="meta-sans tabular">{fmtTemp(points.first)}</span>
      <svg
        viewBox={`0 0 ${points.w} ${points.h}`}
        width="100%"
        height="36"
        preserveAspectRatio="none"
        className="flex-1"
        aria-label="Hourly temperature trend"
      >
        <polyline
          points={points.path}
          fill="none"
          stroke="var(--ink)"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span className="meta-sans tabular">{fmtTemp(points.last)}</span>
    </div>
  );
}

function Forecast({ days }) {
  const list = (days || []).slice(0, 3);
  if (!list.length) return null;
  return (
    <ul className="divide-y rule-thin border-t rule-thin border-b">
      {list.map((d, i) => (
        <li key={d.date || i} className="py-1.5 flex items-baseline justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <span className="headline text-[1rem]">{weekdayLabel(d.date, i)}</span>
            {d.conditions && (
              <span className="meta-sans truncate max-w-[10rem]">{d.conditions}</span>
            )}
          </div>
          <span className="data-num tabular text-right whitespace-nowrap">
            {fmtRange(d.high, d.low)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Header({ timestamp }) {
  return (
    <header className="rule-after mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="section-eyebrow">The Forecast</div>
          <h3 className="headline text-[1.35rem] mt-1">Today's Weather</h3>
        </div>
        <StalenessBadge timestamp={timestamp} />
      </div>
    </header>
  );
}

export default function Weather() {
  const { data, error, loading, refresh } = useResource('/api/weather');

  if (loading && !data && !error) {
    return (
      <section>
        <Header />
        <p className="ink-loading body-serif">Awaiting the forecast…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section>
        <Header />
        <EmptyState source="weather" detail={error} onRetry={refresh} />
      </section>
    );
  }

  if (!data || data.available === false) {
    // Collapse: nothing to show, no error to report.
    return null;
  }

  const current = data.current || {};
  const forecast = data.forecast || data.daily || [];
  const hourly = data.hourly || [];
  const location = data.location || data.city || '';
  const timestamp = data.collected_at || data.updated_at;

  return (
    <section>
      <Header timestamp={timestamp} />

      <div className="flex items-baseline justify-between gap-3 mb-2">
        <div>
          <div className="data-num text-4xl leading-none">{fmtTemp(current.temp)}</div>
          {current.conditions && (
            <div className="body-serif italic text-[14px] mt-1">{current.conditions}</div>
          )}
        </div>
        <div className="text-right">
          {current.feels_like != null && (
            <div className="meta-sans">Feels {fmtTemp(current.feels_like)}</div>
          )}
          {current.high != null && current.low != null && (
            <div className="meta-sans tabular">
              H {fmtTemp(current.high)} · L {fmtTemp(current.low)}
            </div>
          )}
          {location && <div className="meta-sans truncate max-w-[10rem]">{location}</div>}
        </div>
      </div>

      <HourlyTrend hourly={hourly} />

      <div className="meta-sans uppercase tracking-wider mt-3 mb-1">3-Day Outlook</div>
      <Forecast days={forecast} />

      <p className="byline mt-3">
        Filed from {data.source || 'the weather wire'}
        {location ? ` · ${location}` : ''}.
      </p>
    </section>
  );
}
