"""Render weekly meditations in the approved style (the samples4 settings the owner chose on 13 Oct 2026).

Voice: phrase-by-phrase at model speed 0.88, 0.95 s after commas, 2.6 s after sentences, 4 s after paragraphs,
gentle EQ, no reverb. Opening singing bowl. Faint background about 24 dB under the voice.

Outputs per week:
  out2/<voice>/wNN.mp3        full mix to listen to (voice + background)
  app/<voice>/wNN.mp3         voice only, for the app (background plays from its own file)
  app/wNN.json                title, sections, length
usage: python3 build2.py --voice asha --bg forest --only 1 [--seconds 150]
"""
import argparse, hashlib, json, os, subprocess
import numpy as np
import build, voice, ambience, fx, tts

SR = fx.SR
HERE = os.path.dirname(os.path.abspath(__file__))
SPEECH_RMS = 0.118     # matched to the approved sample
BG_RMS = 0.0072
CACHE = os.path.join(HERE, "cache2")


def cached(phrase, v):
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(("%s|%s|%s" % (v, voice.SPEED, phrase)).encode()).hexdigest()
    p = os.path.join(CACHE, key + ".npy")
    if os.path.exists(p):
        return np.load(p)
    a = tts.speak_np(phrase, v, voice.SPEED)
    np.save(p, a)
    return a


def bowl_track(kind):
    b = ambience.bowl()
    if kind == 2:  # closing: three strikes
        out = np.zeros(len(b) + int(8 * SR))
        for i, d in enumerate([0, 4, 8]):
            s = int(d * SR); out[s:s + len(b)] += b * (0.35 if i < 2 else 0.28)
        return out[: len(b) + int(8 * SR)]
    return b * (0.35 if kind == 1 else 0.25)


def render(seq, vname, target, limit=0):
    pieces = []
    for kind, val in seq:
        if limit and sum(len(v) / SR if k in ('voice', 'bell') else (v if k in ('gap', 'pause') else 0) for k, v in pieces) > limit + 10:
            break
        if kind == "say":
            a, m = voice.say(val, vname, cache=cached)
            pieces += [("voice", a), ("gap", voice.GAP_PARA)]
        elif kind == "pause":
            pieces.append(("pause", float(val)))
        elif kind == "bell":
            pieces += [("bell", bowl_track(val)), ("gap", 2.5 if val != 2 else 0)]
        elif kind == "section":
            pieces.append(("section", val))
    fixed = sum(len(v) / SR if k in ("voice", "bell") else v for k, v in pieces if k in ("voice", "bell", "gap"))
    fixed += sum(v for k, v in pieces if k == "pause" and v < 20)
    flex = sum(v for k, v in pieces if k == "pause" and v >= 20)
    scale = max(0.5, (target - fixed) / flex) if flex else 1.0
    if limit:
        scale = 1.4  # short sample: typical full-week pause length
    vtrack, btrack, sections, pos = [], [], [], 0
    for k, v in pieces:
        if k == "section":
            sections.append({"name": v, "at": round(pos / SR, 1)}); continue
        if k == "voice":
            arr_v, arr_b = v, np.zeros(len(v))
        elif k == "bell":
            arr_v, arr_b = np.zeros(len(v)), v
        else:
            secs = min(v * scale, 210) if (k == "pause" and v >= 20) else v
            arr_v = arr_b = np.zeros(int(secs * SR))
        vtrack.append(arr_v.astype(np.float32)); btrack.append(arr_b.astype(np.float32)); pos += len(arr_v)
    return np.concatenate(vtrack), np.concatenate(btrack), sections


def level_voice(v):
    v = voice.gentle(v)
    w = int(0.05 * SR); n = len(v) // w
    e = np.sqrt(np.mean(v[: n * w].reshape(n, w) ** 2, 1))
    return v * (SPEECH_RMS / np.median(e[e > 0.25 * e.max()]))


def mp3(x, path, sr_out=44100, q=3):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = path + ".wav"
    tts.write_wav(raw, np.clip(x, -0.98, 0.98), SR)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-ar", str(sr_out), "-ac", "1",
                    "-c:a", "libmp3lame", "-q:a", str(q), path], check=True)
    os.remove(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="asha")
    ap.add_argument("--bg", default="forest")
    ap.add_argument("--only", default="")
    ap.add_argument("--target", type=float, default=22 * 60)
    ap.add_argument("--seconds", type=float, default=0, help="cut a short sample of this length")
    ap.add_argument("--no-app", action="store_true")
    ap.add_argument("--app-only", action="store_true", help="only the voice track for the app, no full mix")
    ap.add_argument("--outdir", default=os.path.join(HERE, "app"))
    a = ap.parse_args()
    shared = build.load_shared()
    weeks = [int(x) for x in a.only.split(",")] if a.only else range(1, 53)
    for n in weeks:
        if not os.path.exists(os.path.join(HERE, "scripts/w%02d.txt" % n)):
            continue
        meta, body = build.load_week(n)
        seq = build.assemble(n, meta, body, shared)
        v, bells, sections = render(seq, a.voice, a.target, a.seconds)
        v = level_voice(v)
        fg = v + bells * 0.9
        if a.seconds:
            k = int(a.seconds * SR); fg = fg[:k].copy(); f = int(3 * SR); fg[-f:] *= np.linspace(1, 0, f)
        name = "w%02d%s.mp3" % (n, "-sample" if a.seconds else "")
        if not a.app_only:
            bg = ambience.bed(a.bg, len(fg) / SR + 0.1, seed=n)[: len(fg)] * BG_RMS
            mp3(fg + bg, os.path.join(HERE, "out2", a.voice + "-" + a.bg, name))
        if not a.seconds and not a.no_app:
            os.makedirs(os.path.join(a.outdir, a.voice), exist_ok=True)
            mp3(fg, os.path.join(a.outdir, a.voice, name), sr_out=24000, q=5)
            info = {"week": n, "title": meta["title"], "aspect": meta["aspect"], "line": meta["line"],
                    "invite": meta["invite"], "seconds": round(len(fg) / SR), "sections": sections}
            json.dump(info, open(os.path.join(a.outdir, a.voice, "w%02d.json" % n), "w"), indent=1)
        print("week %d %s: %.1f min" % (n, meta["title"], len(fg) / SR / 60), flush=True)


if __name__ == "__main__":
    main()
