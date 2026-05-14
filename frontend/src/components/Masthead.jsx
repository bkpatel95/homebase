import React from 'react';

const EPOCH = new Date('2026-05-12T00:00:00Z');

function editionNumber(now = new Date()) {
  const days = Math.max(1, Math.floor((now - EPOCH) / 86400000) + 1);
  return days;
}

function formatDate(d = new Date()) {
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
}

function weekdayMotto(d = new Date()) {
  const wd = d.getDay();
  return [
    'The Quiet Edition', // Sun
    'Morning Briefing', // Mon
    'The Working Edition', // Tue
    'Midweek Dispatch', // Wed
    'The Thursday Review', // Thu
    'The Weekend Preview', // Fri
    'The Saturday Leisure', // Sat
  ][wd];
}

const MOOD_LABEL = {
  morning: 'Morning Edition',
  midday: 'Midday Edition',
  evening: 'Evening Edition',
};

export default function Masthead({ user, mood, onOpenSources }) {
  const now = new Date();
  const moodLabel = MOOD_LABEL[mood] || weekdayMotto(now);
  return (
    <header className="pt-6 pb-3">
      <div className="flex items-baseline justify-between meta-sans uppercase tracking-widest text-[10px] mb-2">
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenSources}
            aria-label="Open Sources panel"
            title="Manage data sources"
            className="masthead-gear"
          >
            <span aria-hidden="true">⚙</span>
          </button>
          <span>Vol. I · No. {editionNumber(now)}</span>
        </span>
        <span className="hidden sm:inline">{moodLabel}</span>
        <span>{user ? `For ${user.split('@')[0]}` : 'Personal Edition'}</span>
      </div>

      <h1 className="masthead-title text-center text-[clamp(2.6rem,7vw,4.5rem)]">
        The Daily Bhavi
      </h1>

      <div className="double-rule mt-3" />

      <div className="flex items-baseline justify-between mt-2 dateline">
        <span>{formatDate(now)}</span>
        <span className="hidden md:inline">homebase.lebcp.com</span>
        <span>Price: Curiosity</span>
      </div>
    </header>
  );
}
