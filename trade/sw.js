/* Opening Bell's offline helper (scope /trade/ only; Fovea has its own at the site root).
   - The app itself: network first, saved copy when offline.
   - Screener data from GitHub: network first, so prices are never stale while online; the last copy is shown offline.
   - Fonts: saved the first time they load. */
var SHELL = 'ob-shell-1', DATA = 'ob-data-1';
var CORE = ['./', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];

self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then(function (c) {
    return c.addAll(CORE.map(function (u) { return new Request(u, { cache: 'reload' }); }));
  }).catch(function () {}));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('ob-') === 0 && k !== SHELL && k !== DATA; })
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

self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (cs) {
    for (var i = 0; i < cs.length; i++) { if ('focus' in cs[i]) return cs[i].focus(); }
    return self.clients.openWindow('./');
  }));
});
