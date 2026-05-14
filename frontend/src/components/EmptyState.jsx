import React from 'react';

// Small inline failure notice for a widget. Renders nothing if `source` is
// missing — callers should pass a label so the message reads naturally
// ("Unable to load weather"). When `onRetry` is supplied a retry control is
// shown.
export default function EmptyState({ source, detail, onRetry }) {
  if (!source) return null;
  return (
    <div className="body-serif italic text-inksoft text-[14px] flex items-baseline gap-3 flex-wrap">
      <span>Unable to load {source}.</span>
      {detail && <span className="meta-sans not-italic text-[11px]">{detail}</span>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="meta-sans not-italic underline decoration-dotted underline-offset-2 hover:text-[var(--accent)] cursor-pointer"
        >
          retry
        </button>
      )}
    </div>
  );
}
