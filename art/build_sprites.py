"""Render every Meshy GLB to a high-resolution PNG. Runs INSIDE Blender.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        --python art/build_sprites.py

STAGE ONE OF TWO. This writes big, clean, full-colour renders to
`art/generated/raw/`; `art/pixelate.py` then reduces them to the sprites the map
actually loads. Splitting it that way is deliberate -- a render costs seconds per
model and the reduction costs milliseconds, so the look can be re-tuned twenty
times without paying Blender again. It also keeps Pillow out of Blender, which
does not ship it.

THREE THINGS LEARNED THE HARD WAY, 2026-08-20
-----------------------------------------------------------------------------
FREESTYLE MUST BE OFF. `blender_rig` turns it on because Kenney outlines
everything, and that is right for the low-poly procedural assets it was written
for. A Meshy mesh has tens of thousands of creases, and Freestyle draws every
one: the first farm render came out as a solid brown silhouette with no building
visible inside it. The outline is added in `pixelate.py` instead, from the alpha
channel, where it is one clean keyline like the pack's.

BUILDINGS SHARE ONE FRAME. Every building renders through the same ortho span,
so a refinery comes out of it bigger than a farm without anybody scaling sprites
by hand afterwards. Framing them individually would have normalised away the one
size relationship the map should be telling the truth about.

CHARACTERS DO NOT. People are drawn deliberately oversized -- see CHARACTER_M.
"""

from __future__ import annotations

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

exec(open(os.path.join(ROOT, "art", "blender_rig.py")).read())        # noqa: F821
exec(open(os.path.join(ROOT, "art", "meshy_to_sprites.py")).read())   # noqa: F821

import bpy  # noqa: E402

MESHY = os.path.join(ROOT, "art", "Meshy")
RAW = os.path.join("raw", "buildings")
RAW_CHAR = os.path.join("raw", "characters")

# One frame for every building, wide enough for the largest.
#
# 22m, NOT 13m-plus-a-bit. A building seen from 48 degrees projects taller than
# it stands, because you are looking at its depth as well as its height: the 13m
# refinery needs 18.2m of frame and the 11m mine needs 16.4m. Both were cropped
# at the first attempt and `check_fit()` said so, which is exactly what it is
# for -- a cropped sprite still renders and still writes a PNG.
BUILDING_FRAME_M = 22.0
BUILDING_PX = 512

# Real heights in metres, which is what makes the refinery tower over the farm
# on the map. Eyeballed against the models rather than measured off anything --
# the GLBs arrive at arbitrary scale, so SOMETHING has to assign them a size, and
# a plausible height per building type is the most defensible something.
BUILDINGS: dict[str, tuple[str, float]] = {
    "farm-meshy.glb":                                  ("farm", 8.0),
    "Meshy_AI_Cliffside_Chapel_Mine_0819174741_texture.glb":
                                                       ("mining-operation", 11.0),
    "refinery.glb":                                    ("refinery", 13.0),
    "tavern-meshy.glb":                                ("tavern-inn", 9.0),
    # NOT a person. The Weaponsmith's building -- the one file in the folder
    # whose contents are not obvious from its name.
    "blacksmith-meshy.glb":                            ("weaponsmith-armory", 7.5),
    "stable-meshy.glb":                                ("vehicle-dealer-stable", 7.0),
}

# PEOPLE ARE DRAWN OUT OF SCALE, ON PURPOSE. A 1.7m figure beside an 8m farm is
# a fifth of its height, and at map zoom that is a smudge you cannot tell from a
# rock. Every game of this kind draws people two to three times oversized -- the
# reference screenshot has characters at about a third of a house -- because the
# map exists to be read, and the agents are the thing being read. So characters
# get their own frame and their own reduction target, and the honest size
# relationship is the one BETWEEN buildings.
CHARACTER_FRAME_M = 2.1
CHARACTER_PX_RENDER = 288
CHARACTER_M = 1.72

CHARACTERS: dict[str, str] = {
    "african-man-meshy.glb":     "african-man",
    "african-woman-meshy.glb":   "african-woman",
    "asian-girl.glb":            "asian-girl",
    "asian-man-meshy.glb":       "asian-man",
    "indian-man-meshy.glb":      "indian-man",
    "indian-woman-meshy.glb":    "indian-woman",
    "persian-girl-meshy.glb":    "persian-girl",
    "persian-man-meshy.glb":     "persian-man",
    "viking-girl-meshy.glb":     "viking-girl",
    "Meshy_AI_Redbeard_Ironfoot_0819024807_texture.glb": "redbeard",
}

# Four facings, so an agent turns to face the way it is walking. Yaw about Z,
# with the camera to the south: "S" faces the viewer.
FACINGS: dict[str, float] = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}


# HARD KEY, LOW FILL. `blender_rig` lights for a low-poly asset that has no
# surface detail of its own: a soft sun and heavy ambient keep its flat faces
# from going black. A photographed Meshy model needs the opposite. Under that
# soft light every plane of a building lands on a similar value, and once the
# render is reduced to eighteen colours the roof, the walls and the shadow side
# all quantise into the same brown -- which is why the first pass came out as
# featureless blobs.
#
# A strong directional key with a small angle carves the model into distinct
# light and shadow planes BEFORE quantisation, so the reduction has something to
# preserve. This is the same reason the pack itself paints one lighter highlight
# plane per object: flat regions of clearly different value are what reads at
# map size.
SUN_ENERGY = 6.0
SUN_ANGLE_DEG = 6.0          # small: crisp terminator, not a soft gradient
AMBIENT_STRENGTH = 0.35


def _light_for_pixel_art() -> None:
    """Re-light the rigged scene for reduction. Call after every `rig()`."""
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            obj.data.energy = SUN_ENERGY
            obj.data.angle = math.radians(SUN_ANGLE_DEG)
    world = bpy.context.scene.world
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = (
        AMBIENT_STRENGTH
    )


def _face(yaw: float, elevation: float) -> None:
    """Walk the camera and the sun round the model to `yaw` degrees.

    THE MODEL IS NOT TURNED; THE CAMERA IS. Rotating the imported objects is the
    obvious way and it silently did nothing here: a Meshy character is a skinned
    mesh parented to an armature, so the usual `for o in objects if o.parent is
    None` finds nothing to turn and all four facings render byte-identical. That
    is a bug with no symptom other than four files of exactly the same size,
    which is worth knowing about.

    Moving the camera cannot fail that way, and it fixes something else for free:
    THE SUN COMES WITH IT. With a fixed world sun, a character photographed from
    behind would be lit from the far side, so its four facings would not look
    like the same person in the same daylight. Keeping the sun at a constant
    angle RELATIVE TO THE VIEWER is what makes a highlight always fall up and to
    the left, which is the pack's rule and half of why its sprites cohere.
    """
    elev = math.radians(elevation)
    azim = math.radians(yaw)
    cam = bpy.context.scene.camera
    cam.location = (
        CAMERA_DISTANCE_M * math.cos(elev) * math.sin(azim),          # noqa: F821
        -CAMERA_DISTANCE_M * math.cos(elev) * math.cos(azim),         # noqa: F821
        CAMERA_DISTANCE_M * math.sin(elev),                           # noqa: F821
    )
    cam.rotation_euler = (math.radians(90.0 - elevation), 0.0, azim)
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            obj.rotation_euler = (
                math.radians(90.0 - SUN_ELEVATION_DEG),               # noqa: F821
                0.0,
                math.radians(SUN_AZIMUTH_DEG + yaw),                  # noqa: F821
            )
    bpy.context.view_layer.update()


def build_buildings() -> None:
    print("\n=== BUILDINGS ===")
    for filename, (name, height) in BUILDINGS.items():
        path = os.path.join(MESHY, filename)
        if not os.path.exists(path):
            print(f"  !! missing {filename}")
            continue
        rig(span=BUILDING_FRAME_M,                                    # noqa: F821
            elevation=CAMERA_ELEVATION_DEG,                           # noqa: F821
            resolution=(BUILDING_PX, BUILDING_PX))
        bpy.context.scene.render.use_freestyle = False       # see module header
        _light_for_pixel_art()
        clear_assets()                                                # noqa: F821
        made = strip_junk(import_glb(path))                           # noqa: F821
        normalise(made, height)                                       # noqa: F821
        render_asset(name, subdir=RAW)                                # noqa: F821


def build_characters() -> None:
    print("\n=== CHARACTERS ===")
    for filename, name in CHARACTERS.items():
        path = os.path.join(MESHY, filename)
        if not os.path.exists(path):
            print(f"  !! missing {filename}")
            continue
        rig(span=CHARACTER_FRAME_M,                                   # noqa: F821
            elevation=CHARACTER_ELEVATION_DEG,                        # noqa: F821
            resolution=(CHARACTER_PX_RENDER, CHARACTER_PX_RENDER))
        bpy.context.scene.render.use_freestyle = False
        _light_for_pixel_art()
        clear_assets()                                                # noqa: F821
        made = strip_junk(import_glb(path))                           # noqa: F821
        normalise(made, CHARACTER_M)                                  # noqa: F821
        for facing, yaw in FACINGS.items():
            _face(yaw, CHARACTER_ELEVATION_DEG)                        # noqa: F821
            render_asset(f"{name}-{facing}", subdir=RAW_CHAR)          # noqa: F821


if __name__ == "__main__":
    build_buildings()
    build_characters()
    print("\nDONE -- now run:  .venv-art/bin/python art/pixelate.py")
