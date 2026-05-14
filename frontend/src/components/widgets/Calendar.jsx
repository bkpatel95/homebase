import React from 'react';
import StalenessBadge from '../StalenessBadge.jsx';
import EmptyState from '../EmptyState.jsx';
import NotConfigured from '../NotConfigured.jsx';

const ACCENTS = ['#8a2a1f', '#3b5d4a', '#6b4a8a', '#a36a1f', '#1f4a6a'];

function formatTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  } catch {
    return iso;
  }
}

function isAllDay(ev) {
  return ev.all_day === true || (ev.start && ev.start.length === 10);
}

function Header({ timestamp }) {
  return (
    <header className="rule-after mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="section-eyebrow">The Schedule</div>
          <h3 className="headline text-[1.35rem] mt-1">Today's Calendar</h3>
        </div>
        <StalenessBadge timestamp={timestamp} />
      </div>
    </header>
  );
}

export default function Calendar({ data }) {
  if (data?.error) {
    return (
      <section>
        <Header timestamp={data.collected_at} />
        <EmptyState source="calendar" detail={data.error} />
      </section>
    );
  }

  if (!data?.available) {
    // `reason` is set by the connector when the feed file is missing; an
    // available:false response *without* a reason just means "no events today".
    if (data?.reason) {
      return (
        <NotConfigured
          label="Calendar"
          hint="Point CALENDAR_EVENTS at a today.json feed to show today's meetings."
          reason={data.reason}
        />
      );
    }
    return null;
  }
  const events = data.events || [];
  if (events.length === 0) return null;

  return (
    <section>
      <Header timestamp={data.collected_at} />

      <ul className="space-y-2">
        {events.map((ev, i) => {
          const color = ACCENTS[i % ACCENTS.length];
          return (
            <li
              key={ev.id || i}
              className="pl-3 py-1.5 bg-paperdark/40"
              style={{ borderLeft: `3px solid ${color}` }}
            >
              <div className="flex items-baseline justify-between gap-3">
                <div className="headline text-[1rem] leading-tight">{ev.title || 'Untitled'}</div>
                <div className="meta-sans tabular whitespace-nowrap">
                  {isAllDay(ev) ? 'All day' : formatTime(ev.start)}
                </div>
              </div>
              {(ev.location || ev.meeting_link) && (
                <div className="meta-sans mt-0.5">
                  {ev.meeting_link ? <a href={ev.meeting_link}>Join meeting</a> : ev.location}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <p className="byline mt-3">
        {data.count} event{data.count === 1 ? '' : 's'} on the schedule.
      </p>
    </section>
  );
}
