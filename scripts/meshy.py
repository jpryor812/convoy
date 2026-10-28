"""Make 3D models with Meshy's text-to-3D API, for the 3D client.

    python3 scripts/meshy.py balance
    python3 scripts/meshy.py make <name> "<prompt>" [--polys 30000]
    python3 scripts/meshy.py character <name> "<prompt>"

`character` makes a person in an A-pose, rigs it, and bakes the animations the
game uses (idle, walk, run, hammer swing, block, attack) into one GLB.

`make` runs a preview, then a textured (PBR) refine, and saves the GLB to
art/Meshy/<name>-meshy.glb plus the task ids to art/Meshy/<name>.json, so a
model can be traced to the prompt that made it. The key is MESHY_API_KEY in
.env, sent only to api.meshy.ai.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "art" / "Meshy"
API = "https://api.meshy.ai/openapi"
STYLE = ("muted, weathered, realistic 1840s American frontier, Red Dead Redemption 2 style, "
         "worn wood and stone, earthy desaturated colours, game asset, single object, no ground plane")


def _key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("MESHY_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("MESHY_API_KEY is not in .env")


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Meshy {method} {path}: {e.code} {e.read().decode()[:400]}")


def _wait(task: str, kind: str = "/v2/text-to-3d") -> dict:
    while True:
        t = _call("GET", f"{kind}/{task}")
        st = t.get("status")
        print(f"  {task[:8]} {st} {t.get('progress', 0)}%", flush=True)
        if st == "SUCCEEDED":
            return t
        if st in ("FAILED", "CANCELED", "EXPIRED"):
            raise SystemExit(f"task {task} {st}: {t.get('task_error')}")
        time.sleep(10)


def make(name: str, prompt: str, polys: int = 30000, extra: dict | None = None, style: str = STYLE) -> Path:
    full = f"{prompt}. {style}"
    body = {"mode": "preview", "prompt": full[:600], "art_style": "realistic",
            "should_remesh": True, "topology": "triangle", "target_polycount": polys, **(extra or {})}
    pre = _call("POST", "/v2/text-to-3d", body)["result"]
    print(f"{name}: preview {pre}", flush=True)
    _wait(pre)
    ref = _call("POST", "/v2/text-to-3d", {"mode": "refine", "preview_task_id": pre, "enable_pbr": True})["result"]
    print(f"{name}: refine {ref}", flush=True)
    t = _wait(ref)
    url = t["model_urls"]["glb"]
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{name}-meshy.glb"
    if dest.exists():                       # never overwrite a source model: keep the old one beside it
        dest.rename(OUT / f"{name}-meshy-{time.strftime('%Y%m%d-%H%M%S')}.glb")
    urllib.request.urlretrieve(url, dest)
    (OUT / f"{name}.json").write_text(json.dumps({"prompt": full, "preview": pre, "refine": ref,
                                                   "thumbnail": t.get("thumbnail_url")}, indent=2))
    print(f"{name}: saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
    return dest


PERSON = ("rugged realistic 1840s American frontier person, Red Dead Redemption 2 style, weathered worn clothes, "
          "earthy desaturated colours, full body, standing in an A-pose with arms slightly away from the body, "
          "facing forward, game character")
# Idle, Casual Walk, Run Fast, Heavy Hammer Swing, Block1, Attack -- the
# client finds them by name (walk / run / swing / block / idle).
ACTIONS = [0, 30, 16, 128, 138, 4]


def character(name: str, prompt: str) -> Path:
    make(name + "-static", prompt, 30000, {"pose_mode": "a-pose"}, PERSON)
    ref = json.loads((OUT / f"{name}-static.json").read_text())["refine"]
    rig = _call("POST", "/v1/rigging", {"input_task_id": ref, "height_meters": 1.75})["result"]
    print(f"{name}: rig {rig}", flush=True)
    _wait(rig, "/v1/rigging")
    anim = _call("POST", "/v1/animations", {"rig_task_id": rig, "action_ids": ACTIONS})["result"]
    print(f"{name}: animations {anim}", flush=True)
    t = _wait(anim, "/v1/animations")
    url = (t.get("result") or {}).get("animation_glb_url") or t.get("animation_glb_url")
    dest = OUT / f"{name}-meshy.glb"
    if dest.exists():
        dest.rename(OUT / f"{name}-meshy-{time.strftime('%Y%m%d-%H%M%S')}.glb")
    urllib.request.urlretrieve(url, dest)
    meta = json.loads((OUT / f"{name}-static.json").read_text())
    meta.update({"rig": rig, "animations": anim, "actions": ACTIONS})
    (OUT / f"{name}.json").write_text(json.dumps(meta, indent=2))
    print(f"{name}: saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
    return dest


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "balance":
        print(_call("GET", "/v1/balance"))
    elif len(sys.argv) >= 4 and sys.argv[1] == "character":
        character(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "make":
        polys = int(sys.argv[sys.argv.index("--polys") + 1]) if "--polys" in sys.argv else 30000
        make(sys.argv[2], sys.argv[3], polys)
    else:
        print(__doc__)
