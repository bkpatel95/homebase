import React from 'react';

// Subtle placeholder card for widgets whose data source isn't wired up yet.
// Different from EmptyState: this is an *expected* state (no token, no OAuth,
// no data file) and should read as an invitation, not a failure.
//
//   <NotConfigured label="Sleep" hint="connect Oura to enable" />
//
// Rendering matches the newspaper aesthetic: a faint rule on top + bottom,
// italic serif body. No retry button — the fix is in /sources, not here.
export default function NotConfigured({ label, hint, reason }) {
  return (
    <section className="opacity-70">
      <header className="rule-after mb-3">
        <div className="section-eyebrow">{label} — not configured</div>
      </header>
      <p className="body-serif italic text-inksoft text-[14px]">
        {hint || 'Connect this source to bring the section back.'}
      </p>
      {reason && <p className="meta-sans not-italic text-[11px] mt-2 text-inksoft">{reason}</p>}
    </section>
  );
}
