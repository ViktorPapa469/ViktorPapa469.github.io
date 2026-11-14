/* Opening Bell's offline helper (scope /trade/ only; Fovea has its own at the site root).
   - The app itself: network first, saved copy when offline.
   - Screener data from GitHub: network first, so prices are never stale while online; the last copy is shown offline.
   - Fonts: saved the first time they load.
   - Notifications pushed from GitHub (see tools/trade/push.py). Breakout alerts carry entry and stop; the quantity is
     worked out here from the capital and risk the app saved on this phone, so they never leave it. */
var SHELL = 'ob-shell-1', DATA = 'ob-data-1', PREFS = 'ob-prefs';
var CORE = ['./', 'terms.html', 'paper.js', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];

self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then(function (c) {
    return c.addAll(CORE.map(function (u) { return new Request(u, { cache: 'reload' }); }));
  }).catch(function () {}));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('ob-') === 0 && k !== SHELL && k !== DATA && k !== PREFS; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function networkFirst(req, cacheName, key) {
  return fetch(req).then(function (res) {
    if (res && res.ok) { var copy = res.clone(); caches.open(cacheName).then(function (c) { c.put(key || req, copy); }); }
    return res;
  }).catch(function () {
    return caches.open(cacheName).then(function (c) { return c.match(key || req); }).then(function (hit) {
      if (hit) return hit;
      throw new Error('offline');
    });
  });
}
function cacheFirst(req) {
  return caches.open(SHELL).then(function (c) {
    return c.match(req).then(function (hit) {
      return hit || fetch(req).then(function (res) { if (res && (res.ok || res.type === 'opaque')) c.put(req, res.clone()); return res; });
    });
  });
}

self.addEventListener('fetch', function (e) {
  var r = e.request;
  if (r.method !== 'GET') return;
  var url = new URL(r.url);
  if (url.origin === 'https://fonts.googleapis.com' || url.origin === 'https://fonts.gstatic.com') { e.respondWith(cacheFirst(r)); return; }
  if (url.hostname === 'raw.githubusercontent.com') {
    // data files live under a commit id that changes every run; save them under their file name instead
    var name = url.pathname.split('/').slice(4).join('/');
    e.respondWith(networkFirst(r, DATA, 'https://data.local/' + name));
    return;
  }
  if (url.hostname === 'api.github.com') return;            // the "which commit is latest" check must always be live
  if (url.origin !== self.location.origin) return;
  if (r.mode === 'navigate') { e.respondWith(networkFirst(r, SHELL, './')); return; }
  e.respondWith(networkFirst(r, SHELL));
});

/* ---------------- notifications ---------------- */
var DEF = { capital: 500000, risk: 0.5, maxpos: 100 };
var NOT_ADVICE = 'For study only, not investment advice.';
function settings() {
  return caches.open(PREFS).then(function (c) { return c.match('https://data.local/settings.json'); })
    .then(function (r) { return r ? r.json() : {}; }).catch(function () { return {}; })
    .then(function (s) { return Object.assign({}, DEF, s || {}); });
}
function inr(x) { return '\u20b9' + Number(x).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function qtyFor(s, d) {
  var per = Math.abs(d.entry - d.stop);
  if (!(per > 0) || !(d.entry > 0)) return 0;
  var q = Math.floor(s.capital * s.risk / 100 * (d.size_mult || 1) / per), cap = Math.floor(s.capital * s.maxpos / 100 / d.entry);
  return Math.max(0, Math.min(q, cap));
}
self.addEventListener('push', function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { title: 'Opening Bell', body: e.data ? e.data.text() : '' }; }
  var tab = d.tab || 'plan';
  var p = (d.kind === 'breakouts' && d.entry) ? settings().then(function (s) {
    var long = d.side === 'long', q = qtyFor(s, d), lots = d.lot > 0 && q >= d.lot ? ' (' + (q / d.lot).toFixed(1) + ' lots)' : '';
    return {
      title: d.symbol + (long ? ' long' : ' short') + ' setup triggered' + (d.time ? ' ' + d.time : ''),
      body: (long ? 'Long setup above ' : 'Short setup below ') + inr(d.entry) + ', stop ' + inr(d.stop) + ', suggested position ' + q + lots +
            (d.t1 ? ', target ' + inr(d.t1) : '') + '.' + (d.extended ? ' Already past 1R.' : '') + ' ' + NOT_ADVICE
    };
  }) : Promise.resolve({ title: d.title || 'Opening Bell', body: (d.body || '') + (d.kind === 'squareoff' || !d.kind ? '' : ' ' + NOT_ADVICE) });
  e.waitUntil(p.then(function (m) {
    return self.registration.showNotification(m.title, {
      body: m.body, icon: 'icon-192.png', badge: 'badge-96.png', tag: d.tag || 'ob', renotify: d.kind === 'breakouts',
      vibrate: d.kind === 'breakouts' ? [150, 80, 150] : undefined, data: { url: './?tab=' + tab, tab: tab }
    });
  }).then(function () {   // an open app refreshes so the new data is on screen
    return self.clients.matchAll({ type: 'window' }).then(function (cs) { cs.forEach(function (c) { c.postMessage({ type: 'ob-push', kind: d.kind }); }); });
  }));
});
self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var data = e.notification.data || {}, url = new URL(data.url || './', self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (cs) {
    for (var i = 0; i < cs.length; i++) {
      if (cs[i].url.indexOf(self.registration.scope) === 0 && 'focus' in cs[i]) {
        cs[i].postMessage({ type: 'ob-open', tab: data.tab });
        return cs[i].focus();
      }
    }
    return self.clients.openWindow(url);
  }));
});
