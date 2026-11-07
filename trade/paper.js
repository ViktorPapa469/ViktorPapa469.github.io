/* Opening Bell paper trading: works out what happened to a practice trade from published prices.
   Pure functions, no page access, so the same file runs in the app and in tools/trade/tests/paper.test.js.

   A trade: {side:"long"|"short", type:"intraday"|"swing", date:"YYYY-MM-DD", time:"HH:MM", entry, stop,
             target (optional), qty, maxDays (swing, default 10), exit:{price, date, time} (optional, closed by hand)}
   Prices come through two lookups:
     days(): every session date with any data, ascending
     bars(date): that session's 15-minute bars [{t:"HH:MM", o,h,l,c}] when published, otherwise null
     daily(date): that session's daily bar {o,h,l,c} or null
   Rules, applied bar by bar after the entry:
     - a bar that opens beyond the stop (or target) exits at its open (a gap);
     - a bar that touches both stop and target is counted as the stop (the safe assumption);
     - intraday trades end at the session's last bar if neither level is hit;
     - swing trades end at the close of day maxDays after entry if neither level is hit;
     - a trade closed by hand ends at that price, unless the stop or target was hit earlier.
   With only daily bars for a session the result is marked approximate. */
(function (root) {
  "use strict";
  var CLOSE = "15:30";

  function key(date, t) { return date + " " + (t || CLOSE); }
  function addMin(t, m) { var x = +t.slice(0, 2) * 60 + +t.slice(3) + m; return ("0" + Math.floor(x / 60)).slice(-2) + ":" + ("0" + x % 60).slice(-2); }

  function simulate(tr, P, now) {
    var s = tr.side === "short" ? -1 : 1;
    var risk = Math.abs(tr.entry - tr.stop);
    var out = { status: "open", exitPrice: null, exitDate: null, exitTime: null, last: null, lastDate: null, lastTime: null,
                r: null, pct: null, pts: null, mfeR: 0, maeR: 0, approx: false, entryOk: null, notes: [] };
    if (!(risk > 0) || !(tr.entry > 0)) { out.status = "invalid"; out.notes.push("Entry and stop must be different prices."); return out; }
    if (tr.target != null && s * (tr.target - tr.entry) <= 0) tr = Object.assign({}, tr, { target: null });
    var manualKey = tr.exit && tr.exit.price > 0 ? key(tr.exit.date, tr.exit.time) : null;
    var endKey = null;   // time exit for swing trades
    var days = P.days().filter(function (d) { return d >= tr.date; });
    if (!days.length) { out.status = tr.date > now.date ? "waiting" : "nodata"; return out; }

    var done = false, held = 0, lastPx = null, lastD = null, lastT = null;
    function excursion(hi, lo) {
      var best = s === 1 ? hi : lo, worst = s === 1 ? lo : hi;
      out.mfeR = Math.max(out.mfeR, s * (best - tr.entry) / risk);
      out.maeR = Math.min(out.maeR, s * (worst - tr.entry) / risk);
    }
    function close(price, kind, d, t) { out.status = kind; out.exitPrice = price; out.exitDate = d; out.exitTime = t; done = true; }
    // one bar: returns true if the trade ended on it
    function step(b, d, label) {
      if (manualKey && key(d, b.t) >= manualKey) return false;
      var gapStop = s === 1 ? b.o <= tr.stop : b.o >= tr.stop;
      var gapTgt = tr.target != null && (s === 1 ? b.o >= tr.target : b.o <= tr.target);
      var hitStop = s === 1 ? b.l <= tr.stop : b.h >= tr.stop;
      var hitTgt = tr.target != null && (s === 1 ? b.h >= tr.target : b.l <= tr.target);
      if (gapStop) { excursion(b.o, b.o); close(b.o, "stop", d, label); out.notes.push("Opened beyond the stop (gap), so the exit is at the open."); return true; }
      if (gapTgt) { excursion(b.o, b.o); close(b.o, "target", d, label); out.notes.push("Opened beyond the target (gap), so the exit is at the open."); return true; }
      if (hitStop) {   // what happened inside the bar before the stop is unknown, so only its open counts
        if (hitTgt) out.notes.push("Stop and target were both inside one bar; counted as the stop.");
        excursion(b.o, b.o);
        close(tr.stop, "stop", d, label); return true;
      }
      excursion(b.h, b.l);
      if (hitTgt) { close(tr.target, "target", d, label); return true; }
      lastPx = b.c; lastD = d; lastT = label;
      return false;
    }

    for (var i = 0; i < days.length && !done; i++) {
      var d = days[i], intra = P.bars(d), day = P.daily(d);
      if (manualKey && key(d, "00:00") > manualKey) break;
      if (d === tr.date) {
        if (intra && intra.length) {
          var at = intra.filter(function (b) { return b.t <= tr.time && addMin(b.t, 15) > tr.time; })[0];
          var range = at || (tr.time < intra[0].t ? intra[0] : null);
          if (range) out.entryOk = tr.entry >= range.l * 0.998 && tr.entry <= range.h * 1.002;
          var after = intra.filter(function (b) { return b.t > tr.time; });   // bars that start after the entry
          for (var j = 0; j < after.length && !done; j++) step(after[j], d, after[j].t);
          if (!done && lastPx == null) { lastPx = (at || intra[intra.length - 1]).c; lastD = d; lastT = (at || intra[intra.length - 1]).t; }
        } else if (day) {
          out.entryOk = tr.entry >= day.l * 0.998 && tr.entry <= day.h * 1.002;
          out.approx = true;
          if (tr.type === "intraday") {
            out.notes.push("No 15-minute prices for the entry day; judged from the day's high, low and close.");
            step({ t: CLOSE, o: tr.entry, h: day.h, l: day.l, c: day.c }, d, "day");
          } else {
            out.notes.push("No 15-minute prices for the entry day; moves after the entry that day are not checked.");
            lastPx = day.c; lastD = d; lastT = CLOSE;
          }
        }
        if (tr.type === "intraday" && !done) {
          var complete = d < now.date || now.mins >= 930;
          var lastBar = intra && intra.length ? intra[intra.length - 1] : null;
          if (!manualKey && complete && (lastBar || day)) close(lastBar ? lastBar.c : day.c, "eod", d, lastBar ? addMin(lastBar.t, 15) : CLOSE);
          break;
        }
        continue;
      }
      // later sessions (swing trades)
      held++;
      if (intra && intra.length) { for (var k = 0; k < intra.length && !done; k++) step(intra[k], d, intra[k].t); }
      else if (day) step({ t: CLOSE, o: day.o, h: day.h, l: day.l, c: day.c }, d, "day");   // daily bars are normal for later sessions
      if (!done && held >= (tr.maxDays || 10) && !manualKey) {
        var dayDone = d < now.date || now.mins >= 930;
        if (dayDone && lastPx != null) close(lastPx, "time", d, CLOSE);
      }
    }
    if (!done && manualKey) close(tr.exit.price, "manual", tr.exit.date, tr.exit.time);
    if (done) {
      out.pts = s * (out.exitPrice - tr.entry);
    } else {
      out.last = lastPx; out.lastDate = lastD; out.lastTime = lastT;
      if (lastPx == null) { out.status = tr.date > now.date ? "waiting" : "nodata"; return out; }
      out.pts = s * (lastPx - tr.entry);
    }
    out.r = out.pts / risk;
    out.pct = out.pts / tr.entry * 100;
    out.mfeR = Math.max(out.mfeR, out.r);
    out.maeR = Math.min(out.maeR, out.r);
    return out;
  }

  function summarize(results) {
    var closed = results.filter(function (r) { return ["target", "stop", "eod", "time", "manual"].indexOf(r.status) >= 0 && r.r != null; });
    var open = results.filter(function (r) { return r.status === "open"; });
    var wins = closed.filter(function (r) { return r.r > 0; });
    var total = closed.reduce(function (a, r) { return a + r.r; }, 0);
    return {
      closed: closed.length, open: open.length, wins: wins.length,
      winRate: closed.length ? wins.length / closed.length * 100 : null,
      avgR: closed.length ? total / closed.length : null, totalR: closed.length ? total : null,
      best: closed.length ? Math.max.apply(null, closed.map(function (r) { return r.r; })) : null,
      worst: closed.length ? Math.min.apply(null, closed.map(function (r) { return r.r; })) : null,
      openR: open.reduce(function (a, r) { return a + (r.r || 0); }, 0)
    };
  }

  var api = { simulate: simulate, summarize: summarize };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PaperEngine = api;
})(this);
