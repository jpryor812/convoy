"""The sprite render rig. Run this INSIDE Blender.

This file, not any model, is the deliverable of the art pipeline. Consistency
across 80-odd assets comes from every one of them passing through the same
camera, the same sun and the same scale -- not from anyone remembering to set
those the same way twice.

    exec(open("/Users/justinpryor/Downloads/convoy-main/art/blender_rig.py").read())
    rig()                      # build camera, lights, render settings
    render_asset("refinery")   # -> art/generated/buildings/refinery.png

WHY THESE NUMBERS

  view transform     Blender 5.x defaults to AgX, which tonemaps and desaturates.
                     Flat sprite colours come out muddy and nothing matches the
                     Kenney palette any more. Forced to Standard.
  camera             Orthographic, 48 degrees above horizontal. NOT the 30-degree
                     RollerCoaster Tycoon angle, and not the 60 this started at
                     either -- 60 was set by eye and the first render against
                     medievalStructure_20 showed the roof swallowing the walls.
                     Mixing projections reads as a mistake even to people who
                     cannot name it, so the angle was measured, not chosen.
  128 px             4x the 31px the map currently draws buildings at, so it
                     stays sharp on retina and downsamples cleanly.
  ortho span         Fixed metres-across-frame. This is what makes a refinery and
                     an ore cart come out at honest relative sizes; if it is set
                     per-asset, every asset silently invents its own scale.
  lighting           Sun from the north-west plus heavy ambient. Kenney's sprites
                     are nearly flat with one lighter plane, so the sun is there
                     to pick out form, not to cast drama.
"""

import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# Blender exec() has no __file__, so the root is explicit.
ROOT = Path("/Users/justinpryor/Downloads/convoy-main")
if str(ROOT / "art") not in sys.path:
    sys.path.append(str(ROOT / "art"))

import palette as P                                    # noqa: E402

OUT_DIR = ROOT / "art" / "generated" / "buildings"

SPRITE_PX = 128
# Vehicles render into a 2:1 canvas, not a square one. A wagon-and-team is about
# 5.2m long and 1.8m tall; squeezed into a square frame it used 81% of the width
# and 28% of the height, so roughly two thirds of every vehicle sprite was empty
# alpha and the actual art was rendering at well under half the resolution it
# should. Matching the canvas to the subject's aspect is free detail.
VEHICLE_PX = (192, 96)
# Characters go PORTRAIT for the same reason vehicles went landscape: a standing
# figure is roughly 1:1.7, and a square canvas throws away most of the pixels.
#
# 48x80, deliberately small. Pixel art looks pixellated because there are FEWER
# PIXELS, not because a filter was run over it -- rendering at 96x160 and then
# scaling down just produces a smooth small picture. Rendering at 48x80 and
# displaying at 48x80 gives real, chunky, deliberate pixels.
# 54 wide, not 48: the server's skirt plus her tray span 1.08m and hit the edge
# of a 48-wide frame exactly. Widening the canvas fixes her without shrinking
# everyone else, which raising the span would have done.
CHARACTER_PX = (54, 80)
# 48 degrees, not 60. Measured against medievalStructure_20 rather than guessed:
# at 60 the roof swallows the building and the walls vanish, where the Kenney
# sprite shows a deep band of wall with door and windows on it. Those walls are
# where a building's identity lives -- a forge mouth, a shop counter, a stable
# opening are all wall features, and none of them survive a top-down camera.
CAMERA_ELEVATION_DEG = 48.0
# Vehicles get their own, much lower angle. The reference for them is a pure
# side-on pixel-art wagon, and the things that make it read -- spoked wheels,
# plank sides, the line of a horse's back and legs -- are all profile features
# that a 48-degree camera flattens into nothing. 14 degrees keeps a sliver of
# top surface so the sprite is not a flat cut-out, and shows everything else.
VEHICLE_ELEVATION_DEG = 14.0
# Characters at 10 degrees -- near eye level, matching a reference of standing
# tradespeople. At the 48 used for buildings an adult figure is mostly scalp.
CHARACTER_ELEVATION_DEG = 10.0
CAMERA_AZIMUTH_DEG = 0.0         # looking north up the road
CAMERA_DISTANCE_M = 40.0         # irrelevant to framing under ortho; keeps clipping sane
# ONE SPAN PER CATEGORY, sized to the largest member of that category.
#
# Within a category the span is fixed and shared, so relative size is honest: a
# refinery really is bigger than a cottage, and giving each asset its own
# framing would make them all arrive at the map the same size and quietly lie
# about the economy.
#
# Across categories it cannot be shared. The map draws buildings into a 31px box
# and agents into a 22x27 one -- they are separate visual channels, not the same
# scene. A 1.5m person rendered inside the 11m building frame would be about
# 20px of a 128px sprite: correct in metres, useless as art.
#
# 11m: buildings. Started at 12, tightened to 8.5, widened again when the
#      refinery grew to 9.4m after a hand-edit and began rendering cropped.
# 5.8m: vehicles. 5.0 cropped the 4-horse chariot at 5.24m -- caught by
#      check_fit(), which is the entire reason it exists.
# 2m:  characters, sized to a figure with a hat on.
BUILDING_SPAN_M = 11.0
VEHICLE_SPAN_M = 6.4
CHARACTER_SPAN_M = 1.80      # a ~1.52m figure with headroom
ORTHO_SPAN_M = BUILDING_SPAN_M       # default; `rig(span=...)` overrides
SUN_ELEVATION_DEG = 55.0
SUN_AZIMUTH_DEG = 315.0          # north-west, so highlights land up and left
ASSETS_COLLECTION = "ConvoyAssets"

# Kenney outlines every sprite in a dark line. It is the single strongest marker
# of the style and a rendered asset without one reads as soft and foreign next
# to the pack, however good the geometry is.
OUTLINE = True
OUTLINE_COLOUR = "#3a2d1f"
OUTLINE_THICKNESS = 3.0


def hex_to_rgba(value: str, alpha: float = 1.0):
    """Palette hex -> linear RGBA.

    Blender works in linear light; the palette is sRGB hex read off PNGs. Feeding
    sRGB straight in makes every colour too bright, which is subtle enough to
    survive a long way before anyone notices the whole set drifted pale.
    """
    value = value.lstrip("#")
    srgb = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in srgb
    ]
    return (*lin, alpha)


def flat_material(name: str, hex_colour: str):
    """A flat, matte material, cached by NAME AND COLOUR.

    Caching on the name alone was a silent correctness bug. Every draught animal
    asked for a material called "coat"; the first one rendered created it, and
    every animal after that got handed the same object -- so the grey donkey and
    the yellow camel both came out the colour of the first horse. Nothing
    errored, the render just quietly ignored two thirds of the palette.

    Including the colour in the key keeps the sharing that matters (80 assets
    still share one Bronze) while making a colour change produce a new material
    instead of being dropped on the floor.
    """
    key = f"{name}__{hex_colour.lstrip('#')}"
    existing = bpy.data.materials.get(key)
    if existing:
        return existing
    mat = bpy.data.materials.new(key)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = hex_to_rgba(hex_colour)
    bsdf.inputs["Roughness"].default_value = 1.0
    # Specular off: a highlight on a 128px roof reads as a rendering artefact,
    # and the Kenney pack has none.
    for key in ("Specular IOR Level", "Specular"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
    return mat


def _clear(keep_assets: bool = False) -> None:
    for obj in list(bpy.data.objects):
        if keep_assets and obj.users_collection and \
                obj.users_collection[0].name == ASSETS_COLLECTION:
            continue
        bpy.data.objects.remove(obj, do_unlink=True)


def assets_collection():
    coll = bpy.data.collections.get(ASSETS_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(ASSETS_COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    return coll


def rig(clear: bool = True, span: float | None = None,
        elevation: float | None = None,
        resolution: tuple[int, int] | None = None) -> None:
    """Build camera, lights and render settings. Idempotent.

    `span` picks the framing: BUILDING_SPAN_M, VEHICLE_SPAN_M or
    CHARACTER_SPAN_M. Everything else -- angle, sun, outline, colour management
    -- stays identical across categories, which is what keeps a cart and a
    refinery looking like they belong in the same world.
    """
    span = BUILDING_SPAN_M if span is None else span
    elevation = CAMERA_ELEVATION_DEG if elevation is None else elevation
    res_x, res_y = resolution or (SPRITE_PX, SPRITE_PX)
    scn = bpy.context.scene
    if clear:
        _clear(keep_assets=True)
    assets_collection()

    scn.render.engine = "BLENDER_EEVEE"
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = True
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGBA"
    scn.view_settings.view_transform = "Standard"      # never AgX -- see header
    scn.view_settings.look = "None"
    scn.view_settings.exposure = 0.0

    # Camera on a polar position, aimed at the origin by construction rather
    # than by a Track To constraint, so the angle is readable in the numbers.
    elev = math.radians(elevation)
    azim = math.radians(CAMERA_AZIMUTH_DEG)
    cam_data = bpy.data.cameras.new("SpriteCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span
    cam_data.clip_start = 0.1
    cam_data.clip_end = CAMERA_DISTANCE_M * 4
    cam = bpy.data.objects.new("SpriteCam", cam_data)
    cam.location = (
        CAMERA_DISTANCE_M * math.cos(elev) * math.sin(azim),
        -CAMERA_DISTANCE_M * math.cos(elev) * math.cos(azim),
        CAMERA_DISTANCE_M * math.sin(elev),
    )
    cam.rotation_euler = (math.radians(90.0 - elevation), 0.0, azim)
    bpy.context.scene.collection.objects.link(cam)
    scn.camera = cam

    sun_elev = math.radians(SUN_ELEVATION_DEG)
    sun_azim = math.radians(SUN_AZIMUTH_DEG)
    sun_data = bpy.data.lights.new("KeySun", type="SUN")
    sun_data.energy = 2.6
    sun_data.angle = math.radians(20.0)         # soft edges; hard shadows read as dirt
    sun = bpy.data.objects.new("KeySun", sun_data)
    sun.rotation_euler = (math.radians(90.0 - SUN_ELEVATION_DEG), 0.0, sun_azim)
    sun.location = (0.0, 0.0, 20.0)
    bpy.context.scene.collection.objects.link(sun)

    # Heavy ambient. Without it the shaded side of every roof goes black and the
    # sprites stop matching a pack whose darkest tone is a mid green.
    world = bpy.data.worlds.get("ConvoyWorld") or bpy.data.worlds.new("ConvoyWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = hex_to_rgba("#e8f0e8")
    bg.inputs["Strength"].default_value = 1.15
    scn.world = world

    _setup_outline(scn)

    print(f"rig ready: {res_x}x{res_y}px, ortho {span}m, "
          f"cam {elevation}deg, outline {scn.render.use_freestyle}, "
          f"transform {scn.view_settings.view_transform}")


def _setup_outline(scn) -> None:
    """Freestyle silhouette pass, so sprites carry Kenney's dark outline.

    Reports rather than raises if unavailable: an asset without an outline is
    worth having, and a rig that dies on a missing feature is not.
    """
    scn.render.use_freestyle = bool(OUTLINE)
    if not OUTLINE:
        return
    try:
        view_layer = scn.view_layers[0]
        view_layer.use_freestyle = True
        settings = view_layer.freestyle_settings
        for old in list(settings.linesets):
            settings.linesets.remove(old)
        lineset = settings.linesets.new("ConvoyOutline")
        # Silhouette and border only. Crease lines would draw every roof panel
        # edge, which at 128px turns a building into a wireframe.
        lineset.select_silhouette = True
        lineset.select_border = True
        lineset.select_crease = False
        style = lineset.linestyle
        style.color = hex_to_rgba(OUTLINE_COLOUR)[:3]
        style.thickness = OUTLINE_THICKNESS
    except Exception as exc:                                  # noqa: BLE001
        scn.render.use_freestyle = False
        print(f"  outline unavailable ({type(exc).__name__}: {exc}) -- continuing without")


def aim_camera_at_assets() -> None:
    """Re-centre the camera on whatever is in the asset collection.

    The camera is positioned by angle and aimed at the WORLD ORIGIN, but models
    are built standing on the ground plane -- they occupy z from 0 upward, not
    z centred on 0. With a big square frame the slack hid it. The moment
    vehicles moved to a 2:1 canvas the vertical window shrank to 3.2m and every
    animal lost its head off the top of the frame.

    Aiming at the asset's own bounding-box centre fixes it for every category at
    once, and means a model can be built wherever is convenient rather than
    having to be balanced around the origin by hand.
    """
    cam = bpy.context.scene.camera
    pts = [obj.matrix_world @ Vector(corner)
           for obj in assets_collection().objects if obj.type == "MESH"
           for corner in obj.bound_box]
    if not pts:
        return
    centre = Vector((
        (min(p.x for p in pts) + max(p.x for p in pts)) / 2,
        (min(p.y for p in pts) + max(p.y for p in pts)) / 2,
        (min(p.z for p in pts) + max(p.z for p in pts)) / 2,
    ))
    forward = cam.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    cam.location = centre - forward * CAMERA_DISTANCE_M


def check_fit() -> tuple[float, float]:
    """Projected size of the current asset, in metres, as the camera sees it.

    Cropping is the failure mode that hides: a model that overflows the frame
    still renders, still writes a PNG, and only looks *slightly* wrong until
    someone puts it beside a sprite that fits. This turns that into a printed
    warning at the moment it happens. It caught the refinery growing to 9.4m
    inside an 8.5m frame.
    """
    cam = bpy.context.scene.camera
    inv = cam.matrix_world.inverted()
    xs, ys = [], []
    for obj in assets_collection().objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            local = inv @ (obj.matrix_world @ Vector(corner))
            xs.append(local.x)
            ys.append(local.y)
    if not xs:
        return (0.0, 0.0)
    scn = bpy.context.scene
    span = cam.data.ortho_scale
    # ortho_scale applies to the LONGER side; the other follows the pixel aspect.
    rx, ry = scn.render.resolution_x, scn.render.resolution_y
    span_x = span if rx >= ry else span * rx / ry
    span_y = span if ry >= rx else span * ry / rx
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    if width > span_x or height > span_y:
        print(f"  !! CROPPED: needs {width:.2f}x{height:.2f}m, frame is "
              f"{span_x:.2f}x{span_y:.2f}m -- widen the span or shrink the model")
    return (width, height)


def render_asset(name: str, subdir: str = "buildings") -> str:
    """Render whatever is in the assets collection to <subdir>/<name>.png."""
    out = ROOT / "art" / "generated" / subdir
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    # Flush pending transforms before anything reads matrix_world. Blender caches
    # object matrices until the dependency graph re-evaluates, so a model that
    # was moved or scaled in Python still reports its OLD world position. The
    # render itself triggers an evaluation and comes out right, which is what
    # makes this nasty: the picture is correct while the framing and the CROPPED
    # check are both computed against a figure that no longer exists.
    bpy.context.view_layer.update()
    aim_camera_at_assets()
    w, h = check_fit()
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    size = os.path.getsize(path)
    span = bpy.context.scene.camera.data.ortho_scale
    print(f"rendered {path.relative_to(ROOT)} "
          f"({size:,} bytes, {w:.1f}x{h:.1f}m of {span}m)")
    return str(path)


def clear_assets() -> None:
    """Empty the asset collection between models."""
    coll = assets_collection()
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def add(obj) -> None:
    """Move a freshly created object into the asset collection."""
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    assets_collection().objects.link(obj)
