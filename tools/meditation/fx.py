"""Audio helpers: smooth convolution reverb, voice polish, sample loading."""
import os, subprocess
import numpy as np
from scipy.signal import fftconvolve, butter, sosfilt

SR = 44100


def load(path, sr=SR):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def ffilter(x, sr, af):
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
                        "-af", af, "-f", "f32le", "-ar", str(sr), "-ac", "1", "-"],
                       input=x.astype(np.float32).tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(p, dtype=np.float32).copy()


def impulse(sr, rt60=1.0, predelay=0.012, bright=4500, seed=3):
    """Dense, smooth reverb tail: decaying noise that darkens over time. No discrete echoes."""
    rng = np.random.default_rng(seed)
    n = int(sr * rt60 * 1.3)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    env = np.exp(-6.9 * t / rt60)
    # two bands: highs die faster than lows -> warm tail
    lo = sosfilt(butter(2, 900, "low", fs=sr, output="sos"), noise)
    hi = sosfilt(butter(2, [900, bright], "band", fs=sr, output="sos"), noise)
    ir = lo * env + hi * np.exp(-6.9 * t / (rt60 * 0.55))
    fade = np.minimum(1, t / 0.008)  # soft onset, avoids a click-like first reflection
    ir *= fade
    ir = np.concatenate([np.zeros(int(predelay * sr)), ir])
    return ir / np.sqrt(np.sum(ir ** 2))


def reverb(x, sr, rt60=1.0, wet=0.12, predelay=0.012, bright=4500):
    ir = impulse(sr, rt60, predelay, bright)
    w = fftconvolve(x, ir)
    y = np.concatenate([x, np.zeros(len(w) - len(x))])
    return (1 - wet) * y + wet * w


VOICE_EQ = ("highpass=f=75,"
            "equalizer=f=190:t=q:w=1.1:g=2.5,"      # warmth
            "equalizer=f=2900:t=q:w=1.4:g=-2.5,"   # take the edge off
            "equalizer=f=5600:t=q:w=1.8:g=-5,"     # buzz / sibilance region
            "lowpass=f=8500,"
            "acompressor=threshold=-22dB:ratio=2:attack=15:release=250:makeup=1")


def polish_voice(x, sr):
    y = ffilter(x, sr, VOICE_EQ)
    return reverb(y, sr, rt60=0.8, wet=0.07, predelay=0.010, bright=3500)[: len(y) + int(0.6 * sr)]
