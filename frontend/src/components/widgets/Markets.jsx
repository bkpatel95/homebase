import React from 'react';
import StalenessBadge from '../StalenessBadge.jsx';
import EmptyState from '../EmptyState.jsx';

function fmtPrice(p, sym) {
  if (p == null) return '—';
  if (sym === 'BTC-USD' || (p && p > 1000)) {
    return p.toLocaleString('en-US', { maximumFractionDigits: 0 });
  }
  return p.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function Row({ t }) {
  const up = (t.pct_change ?? 0) >= 0;
  const sign = up ? '+' : '';
  return (
    <li className="grid grid-cols-[1fr_auto_auto] items-baseline gap-3 py-2 border-b rule-thin last:border-b-0">
      <div>
        <div className="headline text-[1.05rem]">{t.label}</div>
        <div className="meta-sans">{t.symbol}</div>
      </div>
      <div className="data-num text-lg tabular text-right">{fmtPrice(t.price, t.symbol)}</div>
      <div
        className={`data-num text-sm tabular text-right ${up ? 'text-[#2f6a3a]' : 'text-[#8a2a1f]'}`}
        style={{ minWidth: '4.5rem' }}
      >
        {t.pct_change != null ? `${sign}${t.pct_change.toFixed(2)}%` : '—'}
      </div>
    </li>
  );
}

function Header({ timestamp }) {
  return (
    <header className="rule-after mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="section-eyebrow">Markets &amp; Finance</div>
          <h3 className="headline text-[1.35rem] mt-1">The Money Pages</h3>
        </div>
        <StalenessBadge timestamp={timestamp} />
      </div>
    </header>
  );
}

export default function Markets({ data }) {
  if (data?.error) {
    return (
      <section>
        <Header timestamp={data.collected_at} />
        <EmptyState source="markets" detail={data.error} />
      </section>
    );
  }

  if (!data?.available) return null;
  const tickers = data.tickers || [];
  if (!tickers.length) return null;

  return (
    <section>
      <Header timestamp={data.collected_at} />

      <ul className="border-t rule-thin">
        {tickers.map((t) => (
          <Row key={t.symbol} t={t} />
        ))}
      </ul>

      <p className="byline mt-3">Indices via Stooq · crypto via CoinGecko · 24-hour windows.</p>
    </section>
  );
}
