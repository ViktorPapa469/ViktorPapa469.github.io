/* Event Run Sheet helper (scope /events/).
   - Opening the app loads the newest page from the website; with no signal it shows the copy saved last time.
   - Phone notifications: the scheduled sender on GitHub (.github/workflows/events-push.yml) pushes
     {title, body, tag, urgent}; this shows them, and tapping one opens the app. */
var CACHE = 'runsheet-v1';
var CORE = ['./', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'badge-96.png', 'apple-touch-icon.png'];
self.addEventListener('install', function(e){
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(CORE); }).catch(function(){}));
});
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(ks){
    return Promise.all(ks.filter(function(k){ return k.indexOf('runsheet-') === 0 && k !== CACHE; }).map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});
self.addEventListener('fetch', function(e){
  var r = e.request, url = new URL(r.url);
  if (r.method !== 'GET' || url.origin !== self.location.origin) return;   // Firebase and fonts go straight to the network
  var key = r.mode === 'navigate' ? './' : r;
  e.respondWith(fetch(r, { cache:'no-cache' }).then(function(res){
    if (res && res.ok){ var copy = res.clone(); caches.open(CACHE).then(function(c){ return c.put(key, copy); }); }
    return res;
  }).catch(function(){ return caches.match(key).then(function(m){ return m || Response.error(); }); }));
});
self.addEventListener('push', function(e){
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch(x){ d = { body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Event Run Sheet', {
    body: d.body || '', tag: d.tag || undefined, renotify: !!d.tag, icon: 'icon-192.png', badge: 'badge-96.png',
    requireInteraction: !!d.urgent, vibrate: d.urgent ? [300, 100, 300, 100, 300] : [200, 100, 200], data: { url: './' }
  }));
});
self.addEventListener('notificationclick', function(e){
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type:'window', includeUncontrolled:true }).then(function(cs){
    for (var i = 0; i < cs.length; i++){ if (cs[i].url.indexOf('/events/') >= 0 && 'focus' in cs[i]) return cs[i].focus(); }
    return self.clients.openWindow('./');
  }));
});
