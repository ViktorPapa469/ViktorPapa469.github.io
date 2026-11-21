"""Cloud publishing for the weekly meditations.

Copies freshly rendered weeks from <rendered>/<voice>/wNN.{mp3,json} into the site (med/<voice>/wNN.mp3) and
tools/meditation/timing/<voice>/wNN.json, then rewrites the <script id="medData"> block in index.html from every
week that has both audio and timing. Translations (medI18n) are left as they are.
usage: python3 publish_ci.py <rendered dir>
"""
import hashlib, json, os, re, shutil, sys
import build

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.abspath(os.path.join(HERE, "..", ".."))
VOICES = [("asha", "Asha"), ("nira", "Nira"), ("emma", "Emma"), ("george", "George"), ("michael", "Michael")]
BGS = ["forest", "temple", "river", "grassland"]


def h(p):
    return hashlib.sha1(open(p, "rb").read()).hexdigest()[:10]


def main(rendered):
    new = 0
    for vid, _ in VOICES:
        src_dir = os.path.join(rendered, vid)
        if not os.path.isdir(src_dir):
            continue
        for f in sorted(os.listdir(src_dir)):
            if not f.endswith(".mp3"):
                continue
            j = f[:-4] + ".json"
            if not os.path.exists(os.path.join(src_dir, j)):
                continue
            os.makedirs(os.path.join(SITE, "med", vid), exist_ok=True)
            os.makedirs(os.path.join(HERE, "timing", vid), exist_ok=True)
            shutil.copyfile(os.path.join(src_dir, f), os.path.join(SITE, "med", vid, f))
            shutil.copyfile(os.path.join(src_dir, j), os.path.join(HERE, "timing", vid, j))
            new += 1
    data = {"free": 52, "weeks": [], "voices": [], "bg": {}}
    for b in BGS:
        p = os.path.join(SITE, "med", "bg-%s.mp3" % b)
        data["bg"][b] = "med/bg-%s.mp3?v=%s" % (b, h(p))
    for n in range(1, 53):
        m, _ = build.load_week(n)
        data["weeks"].append({"t": m["title"], "a": m["aspect"], "l": m["line"], "i": m["invite"]})
    for vid, vname in VOICES:
        files = {}
        for n in range(1, 53):
            mp3 = os.path.join(SITE, "med", vid, "w%02d.mp3" % n)
            meta = os.path.join(HERE, "timing", vid, "w%02d.json" % n)
            if not (os.path.exists(mp3) and os.path.exists(meta)):
                continue
            info = json.load(open(meta))
            files[n] = {"u": "med/%s/w%02d.mp3?v=%s" % (vid, n, h(mp3)), "s": info["seconds"],
                        "p": [[x["name"], x["at"]] for x in info["sections"]]}
        if files:
            data["voices"].append({"id": vid, "name": vname, "w": files})
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    p = os.path.join(SITE, "index.html")
    html = open(p, encoding="utf-8").read()
    block = '<script id="medData">window.FOVEA_MED=%s;</script>' % blob
    html, k = re.subn(r'<script id="medData">.*?</script>', lambda _: block, html, flags=re.S)
    assert k == 1
    open(p, "w", encoding="utf-8").write(html)
    print("new weeks:", new, "| voices:", {v["id"]: len(v["w"]) for v in data["voices"]})


if __name__ == "__main__":
    main(sys.argv[1])
