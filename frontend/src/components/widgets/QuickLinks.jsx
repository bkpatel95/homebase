import React from 'react';

const FALLBACK_LINKS = [
  { name: 'Grafana', href: 'https://grafana.lebcp.com', blurb: 'Dashboards & drilldowns' },
  { name: 'Airflow', href: 'https://airflow.lebcp.com', blurb: 'Data pipelines' },
  { name: 'Superset', href: 'https://superset.lebcp.com', blurb: 'Analytics' },
  { name: 'Plex', href: 'https://plex.lebcp.com', blurb: 'Media library' },
  { name: 'Requests', href: 'https://requests.lebcp.com', blurb: 'Overseerr' },
];

export default function QuickLinks({ data }) {
  const links = data && data.links && data.links.length ? data.links : FALLBACK_LINKS;

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">Classifieds</div>
        <h3 className="headline text-[1.35rem] mt-1">Around the Estate</h3>
      </header>

      <ul className="divide-y rule-thin border-t rule-thin border-b">
        {links.map((l) => (
          <li key={l.href} className="py-2">
            <a href={l.href} className="block">
              <div className="flex items-baseline justify-between">
                <span className="headline text-[1.05rem]">{l.name}</span>
                <span className="meta-sans">{hostFromUrl(l.href)}</span>
              </div>
              {l.blurb && <div className="meta-sans italic">{l.blurb}</div>}
            </a>
          </li>
        ))}
      </ul>

      <p className="byline mt-3">All services routed through Cloudflare Access.</p>
    </section>
  );
}

function hostFromUrl(u) {
  try {
    return new URL(u).host;
  } catch {
    return u;
  }
}
