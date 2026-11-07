"""Build one guided-meditation MP3 per week from scripts/wNN.txt.

usage: python3 build.py [--voice af_heart] [--only 1,2,3] [--target 1320]
Writes out/wNN.mp3 and out/wNN.json (title, sections, length).
"""
import argparse, hashlib, json, os, re, subprocess, sys
import numpy as np
import tts

HERE = os.path.dirname(os.path.abspath(__file__))
SR = tts.SR
NUMS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "twenty thirty forty fifty".split()


def words(n):
    if n < 20:
        return NUMS[n - 1]
    t, u = divmod(n, 10)
    return TENS[t - 2] + ("-" + NUMS[u - 1] if u else "")


def parse_blocks(text):
    """Return list of ('say', paragraph) | ('pause', secs) | ('tag', name)."""
    out, para = [], []

    def flush():
        if para:
            out.append(("say", " ".join(para)))
            para.clear()
    for raw in text.splitlines():
        line = raw.strip()
        m = re.fullmatch(r"\[pause (\d+)\]", line)
        if m:
            flush(); out.append(("pause", int(m.group(1)))); continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            flush(); out.append(("tag", m.group(1))); continue
        if not line:
            flush(); continue
        para.append(line)
    flush()
    return out


def load_shared():
    txt = open(os.path.join(HERE, "scripts/shared.txt"), encoding="utf-8").read()
    parts = {}
    for chunk in re.split(r"^## ", txt, flags=re.M)[1:]:
        name, body = chunk.split("\n", 1)
        parts[name.strip()] = parse_blocks(body)
    return parts


def load_week(n):
    txt = open(os.path.join(HERE, "scripts/w%02d.txt" % n), encoding="utf-8").read()
    head, body = txt.split("===", 1)
    meta = {}
    for line in head.strip().splitlines():
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta, parse_blocks(body)


def assemble(n, meta, body, shared):
    op = meta.get("opening", "ABCD"[(n - 1) % 4])
    an = meta.get("anchor", "ABC"[(n - 1) % 3])
    cl = meta.get("closing", "ABCD"[n % 4])
    seq = [("section", "Settling"), ("bell", 1)] + shared["opening " + op]
    seq += [("section", "Theme"), ("say", "Week %s. %s." % (words(n), meta["title"])), ("pause", 3)]
    for kind, val in body:
        if kind == "tag" and val == "anchor":
            seq += [("section", "Breath")] + shared["anchor " + an] + [("section", "Practice")]
        elif kind == "tag" and val == "closing":
            seq += [("section", "Closing")] + shared["closing " + cl] + [("bell", 2)]
        elif kind == "tag" and val == "bell":
            seq.append(("bell", 0))
        else:
            seq.append((kind, val))
    return seq


def sentences(par):
    return [s for s in re.split(r"(?<=[.!?])\s+", par.strip()) if s]


CACHE = os.path.join(HERE, "cache")


def speak(sentence, voice, speed):
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(("%s|%s|%s" % (voice, speed, sentence)).encode()).hexdigest()
    p = os.path.join(CACHE, key + ".npy")
    if os.path.exists(p):
        return np.load(p)
    a = tts.synth(sentence, voice, speed)
    a = trim(a)
    np.save(p, a)
    return a


def trim(a, thr=0.004):
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    s = max(0, idx[0] - int(0.03 * SR)); e = min(len(a), idx[-1] + int(0.12 * SR))
    a = a[s:e].copy()
    f = int(0.01 * SR)
    a[:f] *= np.linspace(0, 1, f); a[-f:] *= np.linspace(1, 0, f)
    return a


def bell(kind):
    """Singing-bowl style strike, synthesised. kind 0 = soft, 1 = start, 2 = end (three strikes)."""
    dur = 9.0
    t = np.arange(int(dur * SR)) / SR
    f0 = 196.0
    partials = [(1.0, 1.0, 0.35), (2.71, 0.45, 0.55), (5.15, 0.22, 0.9), (8.4, 0.08, 1.4)]
    tone = np.zeros_like(t)
    for ratio, amp, dec in partials:
        f = f0 * ratio
        beat = 1 + 0.25 * np.sin(2 * np.pi * (0.9 * ratio) * t)
        tone += amp * np.sin(2 * np.pi * f * t) * np.exp(-dec * t) * beat
    att = np.minimum(1, t / 0.004)
    tone *= att
    tone /= np.max(np.abs(tone))
    level = 0.22 if kind == 0 else 0.32
    tone *= level
    if kind == 2:
        out = np.zeros(int((dur + 8) * SR))
        for i, d in enumerate([0, 4, 8]):
            s = int(d * SR)
            out[s:s + len(tone)] += tone * (1.0 if i < 2 else 0.85)
        return out[: int((dur + 8) * SR)]
    return tone


def render(seq, voice, speed, target):
    # synthesise all speech first so we know its length
    pieces = []  # ('audio', arr) | ('pause', secs) | ('section', name)
    for kind, val in seq:
        if kind == "say":
            ss = sentences(val)
            for i, s in enumerate(ss):
                pieces.append(("audio", speak(s, voice, speed)))
                pieces.append(("gap", 0.85 if i < len(ss) - 1 else 2.0))
        elif kind == "pause":
            pieces.append(("pause", float(val)))
        elif kind == "bell":
            b = bell(val)
            pieces.append(("audio", b))
            pieces.append(("gap", 1.0 if val != 2 else 0.0))
        elif kind == "section":
            pieces.append(("section", val))
    fixed = sum(len(v) / SR if k == "audio" else v for k, v in pieces if k in ("audio", "gap"))
    fixed += sum(v for k, v in pieces if k == "pause" and v < 20)
    flex = [v for k, v in pieces if k == "pause" and v >= 20]
    scale = max(0.6, (target - fixed) / sum(flex)) if flex else 1
    out, sections, pos = [], [], 0
    for k, v in pieces:
        if k == "section":
            sections.append({"name": v, "at": round(pos / SR, 1)}); continue
        if k == "audio":
            arr = v
        else:
            secs = v * scale if (k == "pause" and v >= 20) else v
            if k == "pause" and v >= 20:
                secs = min(secs, 200)
            arr = np.zeros(int(secs * SR), dtype=np.float32)
        out.append(arr.astype(np.float32)); pos += len(arr)
    return np.concatenate(out), sections, scale


def encode(audio, path):
    raw = path + ".raw.wav"
    tts.write_wav(raw, audio * 0.9)
    # gentle room reverb on the whole mix, then even loudness, mono 22 kHz VBR mp3
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-af",
                    "highpass=f=60,aecho=0.85:0.55:55|97:0.14|0.08,"
                    "loudnorm=I=-20:TP=-2:LRA=11", "-ar", "22050", "-ac", "1",
                    "-c:a", "libmp3lame", "-q:a", "6", path], check=True)
    os.remove(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=0.85)
    ap.add_argument("--only", default="")
    ap.add_argument("--target", type=float, default=22 * 60)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    shared = load_shared()
    weeks = [int(x) for x in a.only.split(",")] if a.only else range(1, 53)
    for n in weeks:
        if not os.path.exists(os.path.join(HERE, "scripts/w%02d.txt" % n)):
            continue
        meta, body = load_week(n)
        seq = assemble(n, meta, body, shared)
        audio, sections, scale = render(seq, a.voice, a.speed, a.target)
        mp3 = os.path.join(a.out, "w%02d.mp3" % n)
        encode(audio, mp3)
        info = {"week": n, "title": meta["title"], "aspect": meta["aspect"], "line": meta["line"],
                "invite": meta["invite"], "seconds": round(len(audio) / SR), "sections": sections,
                "voice": a.voice, "bytes": os.path.getsize(mp3)}
        json.dump(info, open(os.path.join(a.out, "w%02d.json" % n), "w"), indent=1)
        print("week %d %s: %.1f min, pause scale %.2f, %d KB" % (
            n, meta["title"], len(audio) / SR / 60, scale, os.path.getsize(mp3) // 1024), flush=True)


if __name__ == "__main__":
    main()
