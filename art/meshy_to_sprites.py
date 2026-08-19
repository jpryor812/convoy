"""Turn a Meshy GLB into 2D sprites for the web map. Run INSIDE Blender.

    exec(open("/Users/justinpryor/Downloads/convoy-main/art/blender_rig.py").read())
    exec(open("/Users/justinpryor/Downloads/convoy-main/art/meshy_to_sprites.py").read())

    inspect("/Users/justinpryor/Downloads/Meshy_AI_Animation_Walking_withSkin.glb")
    sprite_sheet("/Users/justinpryor/Downloads/Meshy_AI_Animation_Walking_withSkin.glb",
                 name="agent-1", frames=8)

NOTHING IS CONVERTED. The GLB stays a 3D model and is untouched; this puts a
fixed camera in front of it and takes photographs. You end up with both files
and use each where it suits -- the GLB in a three.js scene, the PNGs on the 2D
map -- which is why one Meshy library can serve both without duplicated work.

WHY BOTHER, WHEN MESHY CAN RENDER IMAGES ITSELF

Meshy 6 has a 3D-to-Image workspace and it may well be quicker for one-offs. Use
it if it gives you an ORTHOGRAPHIC camera at a FIXED angle with a FIXED frame
size across every asset. If it gives you a perspective "cinematic turntable"
nudged by eye per model, that drift is exactly what this script exists to
prevent: same camera, same sun, same metres-across-frame, mechanically, for
every asset in the library.

THE WALK CYCLE IS THE POINT

A rigged Meshy export carries its animation. Rendering one frame gives a static
sprite; rendering N frames of the walk gives agents that actually walk on the
map instead of sliding along it (VISUALS.md section 7). The animation is
sampled at even intervals and the final frame is dropped, because in a loop it
duplicates the first and would stutter.
"""

import math
import os

import bpy
from mathutils import Vector

# A Meshy character arrives at whatever scale it happened to generate at.
# Everything downstream -- framing, relative size against buildings, the map's
# 27x40 draw box -- assumes metres, so every import is normalised to this.
TARGET_HEIGHT_M = 1.62

# Which way the model faces after import, in degrees about Z. glTF is Y-up and
# Blender is Z-up, so an import usually lands facing -Y, which is toward the
# camera. If a render comes out showing the back of someone's head, change this
# rather than rotating the model by hand.
FACING_OFFSET_DEG = 0.0

# Compass bearings as yaw, with the camera to the south. "S" faces the viewer.
DIRECTIONS = {
    "S": 0.0, "SW": 45.0, "W": 90.0, "NW": 135.0,
    "N": 180.0, "NE": 225.0, "E": 270.0, "SE": 315.0,
}


def inspect(path):
    """Report what a GLB contains without importing it into the scene."""
    import json
    import struct

    with open(path, "rb") as fh:
        blob = fh.read()
    _magic, _ver, total = struct.unpack("<4sII", blob[:12])
    clen, _ctype = struct.unpack("<II", blob[12:20])
    j = json.loads(blob[20:20 + clen])
    tris = sum(
        j["accessors"][pr["indices"]]["count"] // 3
        for m in j.get("meshes", []) for pr in m.get("primitives", [])
        if pr.get("indices") is not None
    )
    print(f"{os.path.basename(path)}")
    print(f"  {total / 1024 / 1024:.2f} MB, {tris:,} triangles")
    print(f"  animations: {[a.get('name') for a in j.get('animations', [])] or 'none'}")
    print(f"  skins: {len(j.get('skins', []))}, images: {len(j.get('images', []))}")
    return j


def import_glb(path):
    """Import a GLB and move everything it brought into the asset collection."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    made = [o for o in bpy.data.objects if o not in before]
    for obj in made:
        add(obj)                                                            # noqa: F821
    return made


def strip_junk(objects):
    """Delete meshes carrying no material, and say which.

    A Meshy export can arrive with extra geometry beside the character. This one
    brought an `Icosphere` -- an untextured 1.2m ball at the origin, presumably a
    proxy or placeholder. It has no material, so it renders flat white, and it
    swamped the frame AND poisoned the scale measurement, because the combined
    bounding box was the sphere's rather than the character's.

    Every real Meshy asset is textured, so "no material" is a reliable tell. It
    is reported rather than dropped silently, because deleting geometry on a
    heuristic should never be invisible.
    """
    junk = [o for o in objects
            if o.type == "MESH" and not o.data.materials]
    for obj in junk:
        print(f"  dropped junk mesh: {obj.name} "
              f"({tuple(round(v, 2) for v in obj.dimensions)}, no material)")
        bpy.data.objects.remove(obj, do_unlink=True)
    return [o for o in objects if o not in junk]


def _world_bounds(objects):
    """Bounds of the EVALUATED mesh, not the rest pose.

    A skinned character's `bound_box` describes its undeformed rest pose, which
    for a walk cycle is the wrong shape and often the wrong height. The
    depsgraph-evaluated copy carries the armature deformation.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(dg)
        pts.extend(ev.matrix_world @ Vector(c) for c in ev.bound_box)
    if not pts:
        return None, None
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def normalise(objects, target_height=TARGET_HEIGHT_M):
    """Scale to a known height and stand it on the ground at the origin.

    Without this every asset invents its own scale and the library stops being
    comparable -- the same failure the sprite rig's ORTHO_SPAN_M contract exists
    to prevent, arriving through a different door.
    """
    roots = [o for o in objects if o.parent is None]
    bpy.context.view_layer.update()
    lo, hi = _world_bounds(objects)
    if lo is None:
        print("  !! no mesh found to normalise")
        return
    height = hi.z - lo.z
    factor = target_height / height if height else 1.0
    for root in roots:
        root.scale = tuple(s * factor for s in root.scale)
    bpy.context.view_layer.update()

    lo, hi = _world_bounds(objects)
    centre_x, centre_y = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
    for root in roots:
        root.location.x -= centre_x
        root.location.y -= centre_y
        root.location.z -= lo.z
    bpy.context.view_layer.update()
    print(f"  normalised {height:.2f}m -> {target_height:.2f}m (x{factor:.3f})")


def _animation_range():
    """Frame range of the imported action, or None for a static model."""
    best = None
    for action in bpy.data.actions:
        start, end = (int(action.frame_range[0]), int(action.frame_range[1]))
        if best is None or (end - start) > (best[1] - best[0]):
            best = (start, end)
    return best


def sprite_sheet(path, name, frames=8, directions=("S",), subdir="characters",
                 resolution=None, outline=True, target_height=TARGET_HEIGHT_M):
    """Render a Meshy GLB to a grid of PNG frames.

    frames=1 gives a single static sprite. frames=8 samples a walk cycle.
    directions defaults to ("S",) -- facing the viewer. Add ("S","N") if agents
    should face their direction of travel on the north-south road, or all eight
    for full RPG-style movement.

    Writes art/generated/<subdir>/<name>/<DIR>_<n>.png, then pack them with
    `python3 art/pack_sheet.py <name>`.
    """
    rig(span=CHARACTER_SPAN_M,                                              # noqa: F821
        elevation=CHARACTER_ELEVATION_DEG,                                  # noqa: F821
        resolution=resolution or CHARACTER_PX)                              # noqa: F821
    bpy.context.scene.render.use_freestyle = bool(outline)
    clear_assets()                                                          # noqa: F821

    made = strip_junk(import_glb(path))
    normalise(made, target_height)
    roots = [o for o in made if o.parent is None]

    rng = _animation_range()
    if rng and frames > 1:
        start, end = rng
        step = (end - start) / frames          # drop the last: it loops to the first
        picks = [int(start + step * i) for i in range(frames)]
        print(f"  animation frames {start}-{end}, sampling {picks}")
    else:
        picks = [bpy.context.scene.frame_current]
        if frames > 1:
            print("  !! no animation found -- rendering a single static frame")

    out = ROOT / "art" / "generated" / subdir / name                        # noqa: F821
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for label in directions:
        yaw = math.radians(DIRECTIONS[label] + FACING_OFFSET_DEG)
        for root in roots:
            root.rotation_euler.z = yaw
        for i, frame in enumerate(picks):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            aim_camera_at_assets()                                          # noqa: F821
            bpy.context.scene.render.filepath = str(out / f"{label}_{i}.png")
            bpy.ops.render.render(write_still=True)
            written += 1

    total = sum(os.path.getsize(out / f) for f in os.listdir(out))
    print(f"  wrote {written} frames to {out.relative_to(ROOT)} "         # noqa: F821
          f"({total / 1024:.0f} KB total)")
    return str(out)
