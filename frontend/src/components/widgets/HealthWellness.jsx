import React from 'react';
import StalenessBadge from '../StalenessBadge.jsx';
import EmptyState from '../EmptyState.jsx';

function MetricBox({ label, value, unit, tone = 'paper' }) {
  const toneClass =
    {
      paper: 'bg-paperdark text-ink',
      sleep: 'bg-[#e6dfd0] text-ink',
      readiness: 'bg-[#dde2d6] text-ink',
      hrv: 'bg-[#e1d8cb] text-ink',
      hr: 'bg-[#e7d4cf] text-ink',
      activity: 'bg-[#d9d6cb] text-ink',
    }[tone] || 'bg-paperdark';
  return (
    <div className={`${toneClass} border rule-thin p-3 flex flex-col`}>
      <span className="meta-sans uppercase tracking-wider">{label}</span>
      <span className="data-num text-2xl leading-tight mt-1">
        {value != null ? value : '—'}
        {value != null && unit && (
          <span className="text-sm font-normal text-inksoft ml-0.5">{unit}</span>
        )}
      </span>
    </div>
  );
}

function Header({ timestamp }) {
  return (
    <header className="rule-after mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="section-eyebrow">Health &amp; Wellness</div>
          <h3 className="headline text-[1.35rem] mt-1">The Morning Vitals</h3>
        </div>
        <StalenessBadge timestamp={timestamp} />
      </div>
    </header>
  );
}

export default function HealthWellness({ data }) {
  if (data?.error) {
    return (
      <section>
        <Header timestamp={data.collected_at} />
        <EmptyState source="health data" detail={data.error} />
      </section>
    );
  }

  if (!data?.available) return null;

  const fmt1 = (n) => (n == null ? null : Number(n).toFixed(1));
  const fmt0 = (n) => (n == null ? null : Math.round(Number(n)));

  return (
    <section>
      <Header timestamp={data.collected_at} />

      <div className="grid grid-cols-2 gap-2 mb-3">
        <MetricBox label="Sleep score" value={data.sleep_score} tone="sleep" />
        <MetricBox label="Sleep dur." value={fmt1(data.sleep_hours)} unit="h" tone="sleep" />
        <MetricBox label="Readiness" value={data.readiness_score} tone="readiness" />
        <MetricBox label="HRV" value={fmt0(data.hrv)} unit="ms" tone="hrv" />
        <MetricBox label="Resting HR" value={fmt0(data.resting_hr)} unit="bpm" tone="hr" />
        <MetricBox
          label="Active cal."
          value={fmt0(data.activity_calories)}
          unit="kcal"
          tone="activity"
        />
      </div>

      <p className="byline">
        Filed from the Oura Ring · {data.source || 'cached'} · {data.date || 'latest'}
      </p>
    </section>
  );
}
