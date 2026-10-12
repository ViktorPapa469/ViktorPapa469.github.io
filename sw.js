/* Fovea's offline helper. It always asks the website for the newest version first, so updates show the next time
   the app opens, and falls back to the copy saved on the device when there is no internet. */
var CACHE = 'fovea-v2';
self.addEventListener('install', function(e){
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(['./', 'manifest.json', 'IMG_20261012_091011_094.jpg', 'IMG_20261012_091017_331.jpg']); }).catch(function(){}));
});
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(keys){ return Promise.all(keys.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); })); }).then(function(){ return self.clients.claim(); }));
});
self.addEventListener('fetch', function(e){
  var r = e.request;
  if (r.method !== 'GET' || new URL(r.url).origin !== self.location.origin) return;
  var key = r.mode === 'navigate' ? './' : r;
  var net = r.mode === 'navigate' ? fetch(r.url, { cache:'no-cache', credentials:'same-origin' }) : fetch(r, { cache:'no-cache' });
  e.respondWith(net.then(function(res){
    if (res && res.ok){ var copy = res.clone(); caches.open(CACHE).then(function(c){ return c.put(key, copy); }); }
    return res;
  }).catch(function(){ return caches.match(key).then(function(m){ return m || caches.match('./'); }); }));
});
