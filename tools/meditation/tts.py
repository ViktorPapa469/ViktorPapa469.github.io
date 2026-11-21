"""Minimal Kokoro TTS: espeak-ng phonemes -> Kokoro ONNX -> 24 kHz float audio."""
import json, os, re, subprocess, sys, wave
import numpy as np
import onnxruntime as rt

HERE = os.path.dirname(os.path.abspath(__file__))
PIPER = os.environ.get("FOVEA_PIPER", os.path.join(HERE, "piperdl", "piper"))
KOK = os.environ.get("FOVEA_KOKORO", os.path.join(HERE, "kokoro"))
SR = 24000
VOCAB = json.load(open(os.path.join(HERE, "kokoro_vocab.json")))["vocab"]

_sess = None
_voices = None


def sess():
    global _sess, _voices
    if _sess is None:
        o = rt.SessionOptions()
        o.intra_op_num_threads = int(os.environ.get("KTHREADS", "4"))
        _sess = rt.InferenceSession(os.path.join(KOK, "kokoro-v1.0.onnx"), o, providers=["CPUExecutionProvider"])
        _voices = np.load(os.path.join(KOK, "voices-v1.0.bin"))
    return _sess, _voices


def espeak(text, lang="en-us"):
    env = dict(os.environ, LD_LIBRARY_PATH=PIPER)
    out = subprocess.run([os.path.join(PIPER, "espeak-ng"), "--path=" + PIPER, "-q", "--ipa", "-v", lang, text],
                         capture_output=True, text=True, env=env).stdout
    out = out.replace("\n", " ").replace("_", "").replace("‍", "")
    return re.sub(r"\s+", " ", out).strip()


PUNCT = re.compile(r'([.,!?;:—…])')


def phonemize(text, lang="en-us"):
    text = text.replace("—", ", ").replace("–", ", ").replace("…", ".").strip()
    parts = PUNCT.split(text)
    out = ""
    for p in parts:
        if not p:
            continue
        if PUNCT.fullmatch(p):
            out = out.rstrip() + p + " "
        elif p.strip():
            out += espeak(p.strip(), lang) + " "
    ph = "".join(c for c in out if c in VOCAB)
    return re.sub(r"\s+", " ", ph).strip()


def synth(text, voice="af_heart", speed=0.9, lang="en-us"):
    s, voices = sess()
    ph = phonemize(text, lang)
    toks = [VOCAB[c] for c in ph]
    if len(toks) > 500:
        raise ValueError("too long: %d" % len(toks))
    if isinstance(voice, str):
        vstyle = voices[voice]
    else:  # blend dict name->weight
        vstyle = sum(voices[k] * w for k, w in voice.items()) / sum(voice.values())
    style = vstyle[len(toks)].reshape(1, 256).astype(np.float32)
    names = [i.name for i in s.get_inputs()]
    tok_name = "input_ids" if "input_ids" in names else "tokens"
    audio = s.run(None, {tok_name: np.array([[0, *toks, 0]], dtype=np.int64),
                         "style": style, "speed": np.array([speed], dtype=np.float32)})[0]
    return np.asarray(audio, dtype=np.float32).ravel()


def write_wav(path, audio, sr=SR):
    a = np.clip(audio, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    v = sys.argv[1]; txt = sys.argv[2]; out = sys.argv[3]
    write_wav(out, synth(txt, v))


def speak_np(text, voice="af_heart", speed=0.95, thr=0.004):
    a = synth(text, voice, speed)
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx):
        a = a[max(0, idx[0] - int(0.03 * SR)): idx[-1] + int(0.15 * SR)].copy()
    f = int(0.012 * SR)
    a[:f] *= np.linspace(0, 1, f); a[-f:] *= np.linspace(1, 0, f)
    return a
