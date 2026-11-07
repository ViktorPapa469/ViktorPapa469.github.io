"""Slow, gentle guided voice: phrases spoken separately with unhurried gaps, warm EQ, no reverb."""
import re
import numpy as np
from scipy.signal import resample_poly
import tts, fx

SR = fx.SR
SPEED = 0.88          # synthesis rate; slower than this makes the voice buzz
GAP_PHRASE = 0.95     # after a comma
GAP_SENT = 2.6        # after a full stop
GAP_PARA = 4.0

GENTLE_EQ = ("highpass=f=85,"
             "equalizer=f=220:t=q:w=1.0:g=2,"
             "equalizer=f=2600:t=q:w=1.2:g=-3,"
             "equalizer=f=4800:t=q:w=1.5:g=-6,"
             "lowpass=f=7200,"
             "acompressor=threshold=-24dB:ratio=1.8:attack=20:release=300:makeup=1")

VOICES = {
    "asha": "af_heart",
    "nira": "af_nicole",
    "emma": "bf_emma",
    "george": "bm_george",
    "michael": "am_michael",
    "asha-gentle": {"af_heart": 0.55, "af_nicole": 0.45},
}


def phrases(sentence):
    """Split a sentence at commas/semicolons/colons, keeping the mark with the phrase."""
    bits = re.split(r"(?<=[,;:])\s+", sentence.strip())
    out = []
    for b in bits:  # don't leave tiny one-word fragments on their own
        if out and len(b.split()) <= 1:
            out[-1] += " " + b
        else:
            out.append(b)
    return out


def sentences(par):
    return [s for s in re.split(r"(?<=[.!?])\s+", par.strip()) if s]


def say(par, voice, cache=None):
    """Return (audio 44.1k, speech mask) for one paragraph."""
    v = VOICES.get(voice, voice)
    parts, mask = [], []
    ss = sentences(par)
    for i, s in enumerate(ss):
        ps = phrases(s)
        for j, p in enumerate(ps):
            a = cache(p, v) if cache else tts.speak_np(p, v, SPEED)
            a = resample_poly(a, 147, 80).astype(np.float32)
            parts.append(a); mask.append(np.ones(len(a), np.float32))
            gap = GAP_PHRASE if j < len(ps) - 1 else (GAP_SENT if i < len(ss) - 1 else 0)
            if gap:
                parts.append(np.zeros(int(gap * SR), np.float32)); mask.append(np.zeros(int(gap * SR), np.float32))
    a = np.concatenate(parts)
    return a, np.concatenate(mask)


def gentle(x):
    return fx.ffilter(x, SR, GENTLE_EQ)
