// Tests for trade/paper.js (the paper-trade result engine).  Run:  node tools/trade/tests/paper.test.js
const assert = require("assert");
const E = require("../../../trade/paper.js");

// helper: prices from compact tables
function prices({ daily = {}, intra = {} }) {
  const all = [...new Set([...Object.keys(daily), ...Object.keys(intra)])].sort();
  return {
    days: () => all,
    daily: (d) => (daily[d] ? { o: daily[d][0], h: daily[d][1], l: daily[d][2], c: daily[d][3] } : null),
    bars: (d) => (intra[d] ? intra[d].map(([t, o, h, l, c]) => ({ t, o, h, l, c })) : null),
  };
}
const AFTER = { date: "2026-10-30", mins: 1000 };
const DURING = (date, mins) => ({ date, mins });
let n = 0;
function test(name, fn) { fn(); n++; console.log("ok -", name); }

const day1 = [
  ["09:15", 100, 101, 99.5, 100.5],
  ["09:30", 100.5, 101.2, 100.2, 101],   // entry 101 at 09:40 is inside this bar
  ["09:45", 101, 102.5, 100.8, 102.2],
  ["10:00", 102.2, 103.2, 102, 103],
  ["10:15", 103, 103.4, 102.6, 102.8],
];

test("long intraday reaches target", () => {
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 103 },
    prices({ intra: { "2026-10-21": day1 } }), AFTER);
  assert.strictEqual(r.status, "target"); assert.strictEqual(r.exitPrice, 103); assert.strictEqual(r.exitTime, "10:00");
  assert.strictEqual(r.r, 2); assert.strictEqual(r.entryOk, true);
});

test("long intraday stopped out", () => {
  const bars = [["09:30", 100.5, 101.2, 100.2, 101], ["09:45", 101, 101.1, 99.8, 100.1]];
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 103 },
    prices({ intra: { "2026-10-21": bars } }), AFTER);
  assert.strictEqual(r.status, "stop"); assert.strictEqual(r.r, -1); assert.strictEqual(r.exitTime, "09:45");
});

test("stop and target in the same bar count as the stop", () => {
  const bars = [["09:30", 100.5, 101.2, 100.2, 101], ["09:45", 101, 103.5, 99.5, 102]];
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 103 },
    prices({ intra: { "2026-10-21": bars } }), AFTER);
  assert.strictEqual(r.status, "stop"); assert.ok(r.notes.some((x) => /both/.test(x)));
});

test("intraday with no hit closes at the session's last bar", () => {
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 110 },
    prices({ intra: { "2026-10-21": day1 } }), AFTER);
  assert.strictEqual(r.status, "eod"); assert.strictEqual(r.exitPrice, 102.8); assert.strictEqual(r.exitTime, "10:30");
  assert.ok(Math.abs(r.r - 1.8) < 1e-9); assert.ok(r.mfeR >= 2.4 - 1e-9);
});

test("intraday still open during the session", () => {
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 110 },
    prices({ intra: { "2026-10-21": day1 } }), DURING("2026-10-21", 640));
  assert.strictEqual(r.status, "open"); assert.strictEqual(r.last, 102.8);
});

test("short side mirrors the rules", () => {
  const bars = [["09:30", 100, 100.3, 99.6, 99.8], ["09:45", 99.8, 99.9, 97.5, 97.8]];
  const r = E.simulate({ side: "short", type: "intraday", date: "2026-10-21", time: "09:35", entry: 99.8, stop: 100.8, target: 97.8 },
    prices({ intra: { "2026-10-21": bars } }), AFTER);
  assert.strictEqual(r.status, "target"); assert.ok(Math.abs(r.r - 2) < 1e-9);
});

test("swing trade gaps through the stop", () => {
  const r = E.simulate({ side: "long", type: "swing", date: "2026-10-21", time: "10:00", entry: 200, stop: 194, target: 212 },
    prices({ daily: { "2026-10-21": [198, 202, 197, 201], "2026-10-22": [203, 206, 202, 205], "2026-10-23": [190, 192, 188, 191] } }), AFTER);
  assert.strictEqual(r.status, "stop"); assert.strictEqual(r.exitPrice, 190); assert.strictEqual(r.exitDate, "2026-10-23");
  assert.ok(r.r < -1); assert.ok(r.notes.some((x) => /gap/.test(x)));
});

test("swing trade ends after its maximum days", () => {
  const daily = { "2026-10-21": [100, 101, 99, 100] };
  ["22", "23", "26"].forEach((d, i) => { daily["2026-10-" + d] = [100 + i, 101.5 + i, 99.5 + i, 101 + i]; });
  const r = E.simulate({ side: "long", type: "swing", date: "2026-10-21", time: "15:00", entry: 100, stop: 95, target: 120, maxDays: 2 },
    prices({ daily }), AFTER);
  assert.strictEqual(r.status, "time"); assert.strictEqual(r.exitDate, "2026-10-23"); assert.strictEqual(r.exitPrice, 102);
});

test("closed by hand before any level is hit", () => {
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 110,
    exit: { price: 102, date: "2026-10-21", time: "09:50" } }, prices({ intra: { "2026-10-21": day1 } }), AFTER);
  assert.strictEqual(r.status, "manual"); assert.strictEqual(r.r, 1);
});

test("a stop hit before the hand-close time wins", () => {
  const bars = [["09:30", 100.5, 101.2, 100.2, 101], ["09:45", 101, 101.1, 99.8, 100.1], ["10:00", 100.1, 104, 100, 103.5]];
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 101, stop: 100, target: 110,
    exit: { price: 103.5, date: "2026-10-21", time: "10:10" } }, prices({ intra: { "2026-10-21": bars } }), AFTER);
  assert.strictEqual(r.status, "stop");
});

test("an entry price that didn't trade is flagged", () => {
  const r = E.simulate({ side: "long", type: "intraday", date: "2026-10-21", time: "09:40", entry: 105, stop: 104, target: 107 },
    prices({ intra: { "2026-10-21": day1 } }), AFTER);
  assert.strictEqual(r.entryOk, false);
});

test("future entries wait; bad stops are invalid", () => {
  const p = prices({ intra: { "2026-10-21": day1 } });
  assert.strictEqual(E.simulate({ side: "long", type: "swing", date: "2026-11-02", time: "09:40", entry: 101, stop: 100 }, p, AFTER).status, "waiting");
  assert.strictEqual(E.simulate({ side: "long", type: "swing", date: "2026-10-21", time: "09:40", entry: 101, stop: 101 }, p, AFTER).status, "invalid");
});

test("summary counts closed trades only", () => {
  const s = E.summarize([{ status: "target", r: 2 }, { status: "stop", r: -1 }, { status: "open", r: 0.5 }]);
  assert.strictEqual(s.closed, 2); assert.strictEqual(s.wins, 1); assert.strictEqual(s.winRate, 50);
  assert.strictEqual(s.totalR, 1); assert.strictEqual(s.avgR, 0.5); assert.strictEqual(s.open, 1);
});

console.log(`\n${n} tests passed`);
