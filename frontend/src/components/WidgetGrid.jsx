import React, { Fragment } from 'react';
import InfraHealth from './widgets/InfraHealth.jsx';
import SystemMetrics from './widgets/SystemMetrics.jsx';
import ProdHealth from './widgets/ProdHealth.jsx';
import QuickLinks from './widgets/QuickLinks.jsx';
import HealthWellness from './widgets/HealthWellness.jsx';
import Calendar from './widgets/Calendar.jsx';
import Markets from './widgets/Markets.jsx';
import Media from './widgets/Media.jsx';
import Nutrition from './widgets/Nutrition.jsx';
import Weather from './widgets/Weather.jsx';
import Reminders from './widgets/Reminders.jsx';
import Gmail from './widgets/Gmail.jsx';

// Server is the source of truth for column order, visibility, and ticker.
// This file is now pure presentation — given `edition.layout.columns`, render
// each widget into its slot. Widgets that return `null` (no data, no error)
// emit no DOM, so the parent flex column's `gap` naturally reflows around
// them and the broadsheet doesn't leave empty boxes behind.

const COMPONENT_FOR = {
  infrastructure: (w) => <InfraHealth data={w.infrastructure} />,
  system_metrics: (w) => <SystemMetrics data={w.system_metrics} />,
  prod_health: (w) => <ProdHealth data={w.prod_health} />,
  quick_links: (w) => <QuickLinks data={w.quick_links} />,
  health_wellness: (w) => <HealthWellness data={w.health_wellness} />,
  calendar: (w) => <Calendar data={w.calendar} />,
  markets: (w) => <Markets data={w.markets} />,
  media: (w) => <Media data={w.media} />,
  nutrition: (w) => <Nutrition data={w.nutrition} />,
  // Self-fetching widgets pull from their own endpoint — `data` is unused.
  weather: () => <Weather />,
  reminders: () => <Reminders />,
  gmail: () => <Gmail />,
};

function LeadStory({ edition }) {
  const w = edition?.widgets || {};
  const layout = edition?.layout || {};
  const mood = edition?.mood;

  const infra = w.infrastructure || {};
  const down = infra.containers_down ?? 0;
  const total = infra.containers_total ?? 0;
  const up = infra.containers_up ?? 0;

  if (down > 0) {
    const names = (infra.down_names || []).slice(0, 3).join(', ');
    return (
      <Story
        kicker="Breaking · Infrastructure"
        headline={`${down} Container${down === 1 ? '' : 's'} Reported Down This Morning`}
        body={`Of ${total} tracked services, ${up} are running and ${down} require attention${names ? ` — ${names}` : ''}. The newspaper recommends a brief inspection over coffee.`}
      />
    );
  }

  const hw = w.health_wellness || {};
  if (mood === 'morning' && hw.available && hw.sleep_score != null) {
    const score = hw.sleep_score;
    const tone = score >= 85 ? 'restored' : score >= 70 ? 'steady' : 'restless';
    return (
      <Story
        kicker="The Morning Read"
        headline={`A ${cap(tone)} Night — Sleep Scores ${score}`}
        body={`The Ring filed a sleep score of ${score} from ${hw.sleep_hours ?? '—'} hours in bed, an average HRV of ${hw.hrv ?? '—'}ms and a resting pulse of ${hw.resting_hr ?? '—'}bpm. Readiness comes in at ${hw.readiness_score ?? '—'}. The day begins ${tone}.`}
      />
    );
  }

  const cal = w.calendar || {};
  if (mood !== 'morning' && cal.available && cal.count > 0) {
    return (
      <Story
        kicker="The Day's Schedule"
        headline={`${cal.count} Meeting${cal.count === 1 ? '' : 's'} on the Calendar`}
        body={`The first lands at ${formatStart(cal.events?.[0]?.start)} (${cal.events?.[0]?.title || 'a meeting'}). Coffee in hand recommended.`}
      />
    );
  }

  const mkt = w.markets || {};
  const sp = (mkt.tickers || []).find((t) => t.id === 'sp500');
  if (sp && sp.pct_change != null) {
    const up_ = sp.pct_change >= 0;
    return (
      <Story
        kicker="From the Markets Desk"
        headline={`The S&P ${up_ ? 'Climbs' : 'Slides'} ${sp.pct_change.toFixed(2)} % in the Latest Tape`}
        body={`The benchmark prints at ${sp.price?.toLocaleString('en-US', { maximumFractionDigits: 2 })}, ${up_ ? 'building' : 'giving back'} ground from yesterday's close near ${sp.prev_close?.toLocaleString('en-US', { maximumFractionDigits: 2 })}. Treat the move as one day's verse in a much longer poem.`}
      />
    );
  }

  return (
    <Story
      kicker="Operations Desk"
      headline="All Systems Quiet on the Home Front"
      body={`Every one of the ${total} tracked containers reports steady. ${layout.overrides_active ? 'The edition is laid out to your taste.' : "A routine morning at homebase — read on for the day's columns."}`}
    />
  );
}

function Story({ kicker, headline, body }) {
  return (
    <article className="pb-6 mb-6 border-b rule-thick">
      <div className="section-eyebrow mb-2">{kicker}</div>
      <h2 className="headline text-[clamp(1.8rem,4.2vw,2.6rem)] mb-3">{headline}</h2>
      <div className="byline mb-3">By the System · Filed moments ago</div>
      <p className="body-serif dropcap text-[1.02rem] leading-[1.55] max-w-[60ch]">{body}</p>
    </article>
  );
}

function cap(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function formatStart(iso) {
  if (!iso) return 'an unspecified hour';
  try {
    const d = new Date(iso.length === 10 ? iso + 'T09:00:00' : iso);
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  } catch {
    return iso;
  }
}

export default function WidgetGrid({ edition }) {
  const widgets = edition?.widgets || {};
  const columns = edition?.layout?.columns || [[], [], []];

  // If nothing is visible at all, the empty grid would be jarring — show a hint.
  const totalVisible = columns.reduce((n, c) => n + c.length, 0);

  return (
    <section>
      <LeadStory edition={edition} />

      {totalVisible === 0 ? (
        <p className="body-serif italic text-center py-8">
          The newspaper is currently bare. Open the editor's desk and ask to bring sections back.
        </p>
      ) : (
        <div className="broadsheet">
          {columns.map((keys, ci) => {
            const isLast = ci === columns.length - 1;
            return (
              <div
                key={ci}
                className={`flex flex-col gap-6 ${isLast ? '' : 'col-rule-right lg-only'}`}
              >
                {keys.map((k) => {
                  const render = COMPONENT_FOR[k];
                  if (!render) return null;
                  // Fragment (not <div>) keeps null-returning widgets from
                  // leaving an empty flex child that pads the column gap.
                  return <Fragment key={k}>{render(widgets)}</Fragment>;
                })}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
