"""Faint nature / temple beds, looped seamlessly from the Moodist recordings (Pixabay licence or CC0)."""
import os
import numpy as np
import fx

SR = fx.SR
M = os.environ.get("FOVEA_MOODIST", os.path.join(os.path.dirname(os.path.abspath(__file__)), "moodist/public/sounds"))
RECIPES = {
    "forest": [("animals/birds.mp3", 0.75), ("nature/wind-in-trees.mp3", 0.55)],
    "temple": [("places/temple.mp3", 1.0)],
    "river": [("nature/river.mp3", 1.0)],
    "grassland": [("nature/wind.mp3", 0.6, "lowpass=f=1800"), ("animals/crickets.mp3", 0.35), ("animals/birds.mp3", 0.18)],
}
_c = {}


def src(path, af=None):
    k = (path, af)
    if k not in _c:
        a = fx.load(os.path.join(M, path))
        if af:
            a = fx.ffilter(a, SR, af)
        a = a / (np.sqrt(np.mean(a ** 2)) + 1e-9)
        _c[k] = a
    return _c[k]


def loop(a, n, xf=4.0, offset=0):
    x = int(xf * SR)
    out = np.zeros(n + len(a))
    pos = 0
    a = np.roll(a, -int(offset * SR))
    up, down = np.linspace(0, 1, x) ** 0.5, np.linspace(1, 0, x) ** 0.5  # equal-power crossfade
    while pos < n:
        s = a.copy()
        if pos:
            s[:x] *= up
        s[-x:] *= down
        out[pos:pos + len(s)] += s
        pos += len(s) - x
    return out[:n]


def bed(name, seconds, seed=0):
    n = int(seconds * SR)
    rng = np.random.default_rng(seed)
    mix = np.zeros(n)
    for item in RECIPES[name]:
        path, g = item[0], item[1]
        a = src(path, item[2] if len(item) > 2 else None)
        mix += g * loop(a, n, offset=rng.uniform(0, len(a) / SR - 8))
    mix /= np.sqrt(np.mean(mix ** 2)) + 1e-9
    f = int(3 * SR)
    mix[:f] *= np.linspace(0, 1, f); mix[-f:] *= np.linspace(1, 0, f)
    return mix.astype(np.float32)  # RMS 1.0; caller sets the level


def bowl():
    a = fx.load(os.path.join(M, "things/singing-bowl.mp3"))
    idx = np.where(np.abs(a) > 0.2 * np.max(np.abs(a)))[0][0]
    s = max(0, idx - int(0.05 * SR))
    seg = a[s:s + int(11 * SR)].copy()
    f = int(3 * SR)
    seg[-f:] *= np.linspace(1, 0, f) ** 2
    return seg / np.max(np.abs(seg))
