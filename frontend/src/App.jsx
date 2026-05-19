import React, { useCallback, useEffect, useState } from 'react';
import Masthead from './components/Masthead.jsx';
import Ticker from './components/Ticker.jsx';
import WidgetGrid from './components/WidgetGrid.jsx';
import ChatBar from './components/ChatBar.jsx';
import Toast from './components/Toast.jsx';
import SourcesPanel from './components/SourcesPanel.jsx';
import { useEdition } from './hooks/useEdition.js';
import { useEditionSocket } from './hooks/useEditionSocket.js';

export default function App() {
  const { edition, error, loading, reconnecting, refresh } = useEdition();
  const [user, setUser] = useState(null);
  const [toast, setToast] = useState(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);

  useEffect(() => {
    fetch('/api/whoami', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setUser(d.email))
      .catch(() => {});
  }, []);

  // Server pushes edition_dirty → refetch edition, show a toast.
  const onDirty = useCallback(
    (msg) => {
      refresh();
      setToast(
        msg.reason === 'ticker'
          ? 'Ticker updated'
          : msg.reason === 'layout_reset' || msg.reason === 'reset'
            ? 'Layout reset'
            : msg.reason === 'hide'
              ? `Hidden ${prettyName(msg.widget)}`
              : msg.reason === 'show'
                ? `Showing ${prettyName(msg.widget)}`
                : msg.reason === 'move'
                  ? `Moved ${prettyName(msg.widget)}`
                  : msg.reason === 'sources'
                    ? 'Sources updated'
                    : 'Layout updated'
      );
    },
    [refresh]
  );
  useEditionSocket({ onDirty });

  return (
    <div className="min-h-screen pb-24 md:pb-12">
      <Toast message={toast} onDone={() => setToast(null)} />

      <div className="max-w-[1400px] mx-auto px-4 sm:px-8 pb-16">
        <Masthead user={user} mood={edition?.mood} onOpenSources={() => setSourcesOpen(true)} />
        <Ticker edition={edition} />

        <main className="mt-6">
          {loading && !edition && (
            <p className="ink-loading body-serif text-center py-16">
              Compiling this morning's edition…
            </p>
          )}

          {error && !edition && (
            <p className="body-serif italic text-center py-16">
              {reconnecting
                ? 'Reconnecting to the press…'
                : `The presses are jammed — ${error}. Refreshing shortly.`}
            </p>
          )}

          {edition && <WidgetGrid edition={edition} />}
        </main>

        <footer className="mt-12 pt-4 border-t rule-thin meta-sans flex items-center justify-between flex-wrap gap-2">
          <span>The Daily Bhavi · Phase 4 · Sources & Connectors</span>
          {edition?.compiled_at && (
            <span>Edition compiled {new Date(edition.compiled_at).toLocaleTimeString()}</span>
          )}
        </footer>
      </div>

      <SourcesPanel open={sourcesOpen} onClose={() => setSourcesOpen(false)} onChange={refresh} />

      <ChatBar onLayoutChange={refresh} />
    </div>
  );
}

const PRETTY = {
  health_wellness: 'Health',
  calendar: 'Calendar',
  markets: 'Markets',
  media: 'Media',
  nutrition: 'Nutrition',
  infrastructure: 'Infrastructure',
  system_metrics: 'System',
  prod_health: 'Prod Health',
  quick_links: 'Quick Links',
};

function prettyName(id) {
  return PRETTY[id] || id || '';
}
