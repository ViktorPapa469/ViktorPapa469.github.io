/* Fovea's offline helper.
   - Opening the app shows the copy saved on the device straight away, so a slow or missing signal never leaves a blank screen.
     It then checks the website for a newer version in the background; if there is one, it is saved for next time and the
     app shows an "Update" button.
   - Photos, sounds, climb pictures and clips are saved the first time they are used. Their links carry a version mark (?v=…),
     so a saved file is always the right one, and a changed file gets a new link.
   - Fonts from Google Fonts are saved the same way, so text looks right offline too. */
var CACHE = 'fovea-v4', MEDIA = 'fovea-media-1';
var QUOTES = {"morning":["Good morning. One clear task first, then the rest.","The day is quiet now. Give your first hour to what matters.","Start small, start now: one focused block before the noise.","Fresh mind, fresh page. What deserves your best 25 minutes?","Before the phone, the plan. Before the plan, a breath.","Your attention is the most valuable thing you own today. Spend it well.","Win the morning, and the day follows.","Pick one thing. Do it fully. Let it carry you.","Sunrise rule: depth before distraction.","The best time to focus was yesterday. The next best is this morning.","A calm start beats a fast start.","Set your intention, set your timer, begin.","Today is a blank trail. Light the first stone.","Breathe in the morning. Breathe out the hurry.","One deep session now saves three scattered ones later.","Coffee for the body, focus for the mind.","The world can wait 25 minutes. Your goal can't.","Begin before you feel ready. Readiness follows action.","Clear desk, clear mind, clear morning.","Small steps up the mountain still reach the top.","Make the first hour yours, not your inbox's.","Today's focus is tomorrow's progress.","Wake up, show up, focus up.","Let the first thing you do today be the most important thing.","Your future self is asking for one good hour this morning.","Quiet hands, steady breath, one task.","Morning light is made for clear thinking.","Don't check the world yet. Check in with yourself.","A focused morning is a gift you give the whole day.","Start the climb. The view comes later.","Three slow breaths, then the first block.","Decide what done looks like today, then begin.","Energy is highest now. Point it at what counts.","Your streak is waiting. Keep the lotus growing.","Every expert was once a beginner who kept showing up in the morning.","Plan the day in one line. Live it in focused blocks.","The day bends toward the first thing you choose.","Silence the noise, hear your goal.","Be here. Be now. Begin.","Light one stone on the trail before noon."],"evening":["Evening check-in: what did you finish today? Be proud of it.","Close the day gently. Tomorrow's focus starts with tonight's rest.","One calm session before bed beats an hour of scrolling.","Let the screen go dim and the mind go still.","You showed up today. That counts.","Write tomorrow's first task now, and sleep on a clear plan.","Breathe out the day. Breathe in quiet.","Rest is part of the climb.","The lake is still at night. Let your mind be the same.","Unfinished? That's fine. Choose tomorrow's one thing.","A short focus now, a peaceful mind later.","Put the phone face down. Let the evening be yours.","Reflect, release, rest.","Today's effort becomes tomorrow's ease.","Even 10 quiet minutes can keep the streak alive.","Slow breath, soft light, kind thoughts.","Count what went well, not what went wrong.","Sleep well. Focus grows overnight.","Let go of the day's noise, one breath at a time.","A calm evening is the soil for a focused morning.","Did you light a stone today? There's still time.","Read a few pages, not a few feeds.","End the day the way you want to begin the next: calm.","Notice the quiet. You earned it.","Tomorrow is a new trail. Tonight, rest your legs.","Thoughts racing? Park them, then let them be.","Your mind did a lot today. Thank it with stillness.","One last breath of focus before the lights go out.","Close the tabs, close the day.","Small wins add up. Look how far you climbed.","Let tonight be slow on purpose.","Evenings are for gentle minds.","Plan less, rest more, focus better tomorrow.","The lotus opens a little more with every day you keep.","Set down what you carried today.","Stillness tonight, clarity tomorrow.","Give the last minutes of your day to calm, not clutter.","Tomorrow's focus begins with tonight's sleep.","A quiet mind is a strong mind.","Good night. Same time tomorrow, one block at a time."],"any":["Focus is a muscle. Every session makes it stronger.","Deep work, calm heart.","Where attention goes, energy flows.","One breath, one task, one moment.","Distraction is loud. Focus is quiet. Choose quiet.","Progress, not perfection.","You can do hard things for 25 minutes.","Slow is smooth, smooth is fast.","Notice the urge. Let it pass. Return.","A wandering mind is normal. Bringing it back is the practice.","Your phone can wait. Your goals can't.","Calm mind, clear work.","Little by little, a little becomes a lot.","Be where your feet are.","Focus on the step, not the whole mountain.","The present moment is where the work gets done.","Clarity comes from doing, not from waiting.","Every unbroken minute is a small victory.","Discipline is remembering what you want most.","Breathe. Begin. Repeat.","Attention is love made practical. Give it to your work.","The quieter you become, the more you can hear.","Consistency beats intensity.","Make it simple. Make it now.","The mind settles like water when you stop stirring it.","Do less, but do it with all of you.","Thoughts are clouds. You are the sky.","Focus is saying no to a hundred good things for one great thing.","Peace is a practice, not a place.","Five minutes of focus is better than an hour of worry.","Om. Let the hum steady your mind.","Climb with patience; the summit is not going anywhere.","Each session waters the lotus.","The best productivity tool is a rested mind.","Stay with it a little longer than feels easy.","Calm is a superpower.","You are building a mind that can stay.","Breathe like the tide: slow in, slow out.","When in doubt, start the timer.","Today, be a little more focused than yesterday."]};   // filled in by build.py from push/quotes.json
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
      // Offer an update only when the page itself has changed. Comparing headers was not enough: the website's servers can
      // report different dates or tags for the same page, which showed "A new version is ready" again and again.
      if (old) Promise.all([old.arrayBuffer(), res.clone().arrayBuffer()]).then(function(b){
        if (b[0].byteLength !== b[1].byteLength) return tell();
        return Promise.all([crypto.subtle.digest('SHA-256', b[0]), crypto.subtle.digest('SHA-256', b[1])]).then(function(d){
          var x = new Uint8Array(d[0]), y = new Uint8Array(d[1]), i;
          for (i = 0; i < x.length; i++) if (x[i] !== y[i]) return tell();
        });
      }).catch(function(){});
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
      var fresh = refreshPage(r, hit ? hit.clone() : null);   // a copy: the saved page itself goes to the screen
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
/* Daily reminders: the scheduled sender pushes {kind:'morning'|'evening'}; a random line is chosen here. */
self.addEventListener('push', function(e){
  var d = {}; try { d = e.data ? e.data.json() : {}; } catch(x){}
  var kind = d.kind === 'evening' ? 'evening' : 'morning', pool = (QUOTES[kind] || []).concat(QUOTES.any || []);
  var body = pool.length ? pool[Math.floor(Math.random() * pool.length)] : 'Breathe. Begin. Repeat.';
  e.waitUntil(self.registration.showNotification(kind === 'evening' ? 'Fovea \u00b7 Evening calm' : 'Fovea \u00b7 Morning focus',
    { body:body, icon:'icon-192.png', badge:'icon-maskable-192.png', tag:'fovea-reminder', data:{ url:'./' } }));
});
self.addEventListener('notificationclick', function(e){
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type:'window', includeUncontrolled:true }).then(function(cs){
    for (var i = 0; i < cs.length; i++){ if ('focus' in cs[i]) return cs[i].focus(); }
    return self.clients.openWindow('./');
  }));
});
