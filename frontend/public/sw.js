// Service worker for The Daily Bhavi.
//
// Caches the app shell so the masthead is available on cold load even when
// the network is sleepy. API responses are never cached — /api/* paths are
// passed straight through.
//
// __BUILD_VERSION__ is rewritten at image build time (see Dockerfile +
// deploy.sh) so every deploy produces a fresh cache name and forces clients
// to refetch the shell.
const CACHE = 'daily-bhavi-shell-__BUILD_VERSION__';
const SHELL = ['/', '/manifest.webmanifest'];

// How often to re-probe /api/health once we've decided the backend is down.
// Short enough that recovery feels near-instant; long enough not to hammer
// the backend or the Cloudflare edge.
const HEALTH_CHECK_INTERVAL_MS = 30_000;

// 'unknown' | 'ok' | 'down'. We only broadcast on a transition, so the
// initial 'unknown' state means clients never see a spurious "recovered"
// message on first install.
let backendStatus = 'unknown';
let healthTimer = null;

self.addEventListener('install', (e) => {
  // If the shell can't be pre-cached (e.g. install happened during a
  // tunnel outage), don't fail the install — we still want the SW active
  // so the network-first nav handler can recover on the next online load.
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL).catch(() => null))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (e) => {
  const data = e.data || {};
  if (data.type === 'backend-error') {
    // A page just saw /api/edition fail. Take over the recovery polling
    // from the SW side so we keep checking even if the tab goes idle.
    backendStatus = 'down';
    startHealthPolling();
    checkBackendHealth();
  } else if (data.type === 'check-backend') {
    checkBackendHealth();
  }
});

function startHealthPolling() {
  if (healthTimer) return;
  // The browser may terminate the SW between fetch/message events, which
  // also kills this timer. Pages re-send 'backend-error' on every failed
  // poll, so the loop restarts whenever a client is actively erroring.
  healthTimer = setInterval(checkBackendHealth, HEALTH_CHECK_INTERVAL_MS);
}

function stopHealthPolling() {
  if (!healthTimer) return;
  clearInterval(healthTimer);
  healthTimer = null;
}

async function checkBackendHealth() {
  let nowOk = false;
  try {
    const resp = await fetch('/api/health', {
      cache: 'no-store',
      credentials: 'same-origin',
      // Cloudflare Access can intercept /api/* with a 302 to its login
      // screen if the session cookie has expired. /api/health is exempt
      // in the backend, but the CF edge gates it independently. Use
      // 'manual' redirect handling so an Access bounce shows up as
      // type='opaqueredirect' and we treat it as 'down' — not as a
      // successful HTML response that we'd mistake for "backend ok".
      redirect: 'manual',
    });
    if (resp.type !== 'opaqueredirect' && resp.ok) {
      const ct = resp.headers.get('content-type') || '';
      // Only believe JSON. A 200 HTML page from a misconfigured upstream
      // or a captive portal is not a healthy backend.
      nowOk = ct.includes('application/json');
    }
  } catch {
    nowOk = false;
  }

  const newStatus = nowOk ? 'ok' : 'down';
  const prev = backendStatus;
  backendStatus = newStatus;

  // Broadcast only on transitions — we don't want a steady stream of
  // 'backend-down' messages while the tunnel is out.
  if (prev === 'down' && newStatus === 'ok') {
    await broadcast({ type: 'backend-recovered' });
    // Steady-state 'ok' shouldn't poll. Clients will wake us via
    // 'backend-error' if they start failing again.
    stopHealthPolling();
  } else if (prev !== 'down' && newStatus === 'down') {
    await broadcast({ type: 'backend-down' });
  }
}

async function broadcast(msg) {
  const clients = await self.clients.matchAll({ includeUncontrolled: true });
  clients.forEach((c) => c.postMessage(msg));
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) return; // API is always network-only
  if (e.request.method !== 'GET') return;

  // HTML navigations: network-first with cache fallback. Network-first
  // means that once the backend recovers, the next nav pulls the freshest
  // shell — without it we'd keep serving the snapshot from the moment
  // the tunnel went down. Falls back to cached '/' so the PWA still opens
  // when truly offline.
  if (e.request.mode === 'navigate' || e.request.destination === 'document') {
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          if (resp.ok && resp.type === 'basic') {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return resp;
        })
        .catch(() =>
          caches.match(e.request).then((hit) => hit || caches.match('/'))
        )
    );
    return;
  }

  // Static assets: cache-first, with the network as backfill. Critical:
  // do NOT substitute the index.html shell when a JS/CSS asset fails.
  // A missing JS chunk that returns HTML triggers a SyntaxError in the
  // browser — exactly the "Load failed" state we're trying to escape.
  // Let the failure propagate so the page can re-fetch on its next try.
  e.respondWith(
    caches.match(e.request).then(
      (hit) =>
        hit ||
        fetch(e.request).then((resp) => {
          if (resp.ok && resp.type === 'basic') {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return resp;
        })
    )
  );
});
