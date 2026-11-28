/* Riyaz's own offline helper. It covers only /riyaz/, so this app never shows another app's page
   and no other app on this site answers for it. Newest copy from the network first; the saved copy when offline. */
var CACHE = 'riyaz-v1';
var CORE = ['./', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];
self.addEventListener('install', function(e){
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(CORE.map(function(u){ return new Request(u, { cache:'reload' }); })); }).catch(function(){}));
});
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k.indexOf('riyaz') === 0 && k !== CACHE; }).map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});
self.addEventListener('fetch', function(e){
  var r = e.request;
  if (r.method !== 'GET' || r.headers.get('range')) return;
  var url = new URL(r.url), fonts = url.origin === 'https://fonts.googleapis.com' || url.origin === 'https://fonts.gstatic.com';
  if (fonts){
    e.respondWith(caches.open(CACHE).then(function(c){ return c.match(r).then(function(hit){
      return hit || fetch(r).then(function(res){ if (res && (res.ok || res.type === 'opaque')) c.put(r, res.clone()); return res; });
    }); }));
    return;
  }
  if (url.origin !== self.location.origin || url.pathname.indexOf('/riyaz/') !== 0) return;
  var key = r.mode === 'navigate' ? './' : r;
  e.respondWith(fetch(r, { cache:'no-cache' }).then(function(res){
    if (res && res.ok){ var copy = res.clone(); caches.open(CACHE).then(function(c){ return c.put(key, copy); }); }
    return res;
  }).catch(function(){ return caches.open(CACHE).then(function(c){ return c.match(key); }).then(function(m){ return m || Response.error(); }); }));
});
