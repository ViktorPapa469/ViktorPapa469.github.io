/* Fovea's offline helper.
   - Opening the app shows the copy saved on the device straight away, so a slow or missing signal never leaves a blank screen.
     It then checks the website for a newer version in the background; if there is one, it is saved for next time and the
     app shows an "Update" button.
   - Photos, sounds, climb pictures and clips are saved the first time they are used. Their links carry a version mark (?v=…),
     so a saved file is always the right one, and a changed file gets a new link.
   - Fonts from Google Fonts are saved the same way, so text looks right offline too. */
var CACHE = 'fovea-v4', MEDIA = 'fovea-media-1';
var CORE = ['./', 'manifest.json', 'icon-192.png', 'icon-512.png', 'icon-maskable-192.png', 'icon-maskable-512.png', 'apple-touch-icon.png'];
self.addEventListener('install', function(e){
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(CORE.map(function(u){ return new Request(u, { cache:'reload' }); })); }).catch(function(){}));
});
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k !== CACHE && k !== MEDIA; }).map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});
var newer = false;   // true when a newer page has been saved since the copy now on screen was shown
self.addEventListener('message', function(e){   // the app asks a few seconds after opening, and when it comes back to the screen
  if (e.data && e.data.type === 'fovea-ask' && newer && e.source) e.source.postMessage({ type:'fovea-updated' });
});
function tell(){   // ask open copies of the app to offer the new version
  newer = true;
  self.clients.matchAll({ type:'window' }).then(function(cs){ cs.forEach(function(c){ c.postMessage({ type:'fovea-updated' }); }); });
}
function refreshPage(req, old){
  return fetch(req.url, { cache:'no-cache', credentials:'same-origin' }).then(function(res){
    if (!res || !res.ok) return res;
    var copy = res.clone();
    return caches.open(CACHE).then(function(c){ return c.put('./', copy); }).then(function(){
      if (old){
        var a = old.headers.get('etag') || old.headers.get('last-modified'), b = res.headers.get('etag') || res.headers.get('last-modified');
        if (a && b && a !== b) tell();
      }
      return res;
    });
  });
}
function mediaFirst(req){   // saved copy if there is one, otherwise fetch and save; older versions of the same file are removed
  return caches.open(MEDIA).then(function(c){
    return c.match(req).then(function(hit){
      if (hit) return hit;
      return fetch(req).then(function(res){
        if (res && (res.ok || res.type === 'opaque')){
          var copy = res.clone(), path = new URL(req.url).pathname;
          c.keys().then(function(ks){ ks.forEach(function(k){ var u = new URL(k.url); if (u.pathname === path && k.url !== req.url) c.delete(k); }); });
          c.put(req, copy);
        }
        return res;
      });
    });
  });
}
self.addEventListener('fetch', function(e){
  var r = e.request;
  if (r.method !== 'GET') return;
  var url = new URL(r.url);
  if (url.origin === 'https://fonts.googleapis.com' || url.origin === 'https://fonts.gstatic.com'){ e.respondWith(mediaFirst(r).catch(function(){ return fetch(r); })); return; }
  if (url.origin !== self.location.origin) return;
  if (r.headers.get('range')) return;                        // video players ask for pieces; let the browser handle those directly
  if (r.mode === 'navigate'){
    e.respondWith(caches.open(CACHE).then(function(c){ return c.match('./'); }).then(function(hit){
      var fresh = refreshPage(r, hit);
      if (hit){ newer = false; e.waitUntil(fresh.catch(function(){})); return hit; }
      return fresh.catch(function(){ return caches.match('./'); });
    }));
    return;
  }
  if (url.search.indexOf('v=') >= 0){ e.respondWith(mediaFirst(r).catch(function(){ return fetch(r); })); return; }
  // everything else (manifest, icons, this helper's own files): network first, saved copy when offline
  e.respondWith(fetch(r, { cache:'no-cache' }).then(function(res){
    if (res && res.ok){ var copy = res.clone(); caches.open(CACHE).then(function(c){ return c.put(r, copy); }); }
    return res;
  }).catch(function(){ return caches.match(r).then(function(m){ return m || caches.match('./'); }); }));
});
