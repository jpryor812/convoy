"""Model builders, one function per Convoy asset. Run INSIDE Blender.

Assumes `blender_rig.py` has already been exec'd -- these use its `add()`,
`flat_material()` and palette bindings.

    exec(open(".../art/blender_rig.py").read());   rig()
    exec(open(".../art/blender_assets.py").read()); build("refinery")
    render_asset("refinery")

Everything is built from primitives and explicit meshes rather than sculpted.
That is deliberate: modular hard-surface geometry is what can be described
precisely in code, reviewed in a diff, and adjusted by a number rather than by
redoing it. It is also, per its own documentation, what Blender-MCP is good at.

SCALE CONTRACT: 1 Blender unit = 1 metre, and the rig frames 11m -- sized to the
largest asset (the refinery, 9.4m). Buildings run 4.4m (a home) to 9.4m, and
they are MEANT to differ: relative size is information about the economy.
Changing dimensions here changes an asset's apparent size on the map; changing
the frame changes everyone's. Adjust `ORTHO_SPAN_M` in the rig, not these.
"""

import math

import bpy


def box(name, size, loc, hex_colour, mat_name=None):
    """An axis-aligned box. `size` is full extent, `loc` is the CENTRE."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0], size[1], size[2])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(flat_material(mat_name or name, hex_colour))  # noqa: F821
    add(obj)                                                                # noqa: F821
    return obj


def gable_roof(name, width, depth, wall_top, rise, hex_colour, mat_name=None,
               ridge_frac=0.45):
    """A pitched roof, ridge running east-west.

    `ridge_frac` is the ridge length as a fraction of the building width:
    1.0 gives a gable (vertical triangular ends), 0.0 a pyramid, and anything
    between a hip roof. Default 0.45 -- a hip.

    That default matters more than it looks. The first pass used a full-width
    gable and the roof rendered as a flat green band; Kenney's buildings are
    dominated by a big hipped roof mass, and matching that one property closed
    most of the remaining stylistic gap in a single change.

    The camera sits to the south, so the ridge must run ACROSS the view. Run it
    along the view instead and the roof shows as one flat quad with no shape.
    """
    w, d = width / 2.0, depth / 2.0
    rw = w * max(0.0, min(1.0, ridge_frac))
    verts = [
        (-w, -d, wall_top), (w, -d, wall_top),          # south eave
        (w, d, wall_top), (-w, d, wall_top),            # north eave
        (-rw, 0.0, wall_top + rise), (rw, 0.0, wall_top + rise),   # ridge
    ]
    faces = [
        (0, 1, 5, 4),        # south slope
        (2, 3, 4, 5),        # north slope
        (0, 4, 3),           # west hip
        (1, 2, 5),           # east hip
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(flat_material(mat_name or name, hex_colour))  # noqa: F821
    bpy.context.scene.collection.objects.link(obj)
    add(obj)                                                                # noqa: F821
    return obj


# NO GROUND PAD. The first version gave every building a dark octagonal patch of
# earth on the theory that it stopped the sprite floating. Held against
# medievalStructure_20 that was simply wrong -- Kenney's buildings sit directly
# on transparency and let the map's own tile show through. The pad read as a
# muddy halo and was the loudest thing in the sprite at 31px.


def cyl(name, radius, height, loc, hex_colour, mat_name=None, sides=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=sides, radius=radius,
                                        depth=height, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(flat_material(mat_name or name, hex_colour))  # noqa: F821
    add(obj)                                                                # noqa: F821
    return obj


def blade(name, size, loc, angle_deg, hex_colour, mat_name=None):
    """A flat plank rotated in the XZ plane -- windmill sails, fence rails."""
    obj = box(name, size, loc, hex_colour, mat_name)
    obj.rotation_euler = (0.0, math.radians(angle_deg), 0.0)
    return obj


def sign(name, x, hex_colour=None):
    """A hanging shop sign on a post. Kenney uses these to say 'this is a shop'
    without any interior detail, and at 31px it is a surprisingly strong cue."""
    box(f"{name}Post", (0.16, 0.16, 2.6), (x, -2.6, 1.3), P.WOOD_DARK, "wood_dark")   # noqa: F821
    box(f"{name}Arm", (0.9, 0.14, 0.16), (x + 0.4, -2.6, 2.5), P.WOOD_DARK, "wood_dark")  # noqa: F821
    box(f"{name}Board", (0.8, 0.1, 0.7), (x + 0.75, -2.6, 1.95),
        hex_colour or P.WOOD_LIGHT, "wood_light")


# ---------------------------------------------------------------------------
# BUILDINGS -- one identifying feature each
# ---------------------------------------------------------------------------
# At 31px a building gets ONE readable idea. Everything else is texture. So each
# of these is designed around a single silhouette cue, listed in its docstring,
# and the rest exists only to stop that cue floating in space.

def refinery():
    """TWO TALL STACKS on a wide low hall.

    Widened from 5.0m to 9.4m and given a second chimney at the owner's request,
    matching the edit made directly in Blender. The stacks are deliberately out
    of proportion -- at 31px they are the only part that survives, and a
    refinery that reads as a cottage is worse than an ugly refinery.
    """
    box("RefineryWalls", (9.4, 4.2, 2.7), (0, 0, 1.35), P.SAND, "wall_sand")     # noqa: F821
    gable_roof("RefineryRoof", 9.9, 4.6, 2.7, 2.1, P.GRASS_MID, "roof_green",    # noqa: F821
               ridge_frac=0.62)
    for i, sx in enumerate((-3.1, 3.1)):
        box(f"RefineryStack{i}", (1.4, 1.6, 5.0), (sx, 0.3, 3.4), P.STONE, "stone")  # noqa: F821
        box(f"RefineryStackCap{i}", (1.75, 1.95, 0.4), (sx, 0.3, 6.1),
            P.STONE_DARK, "stone_dark")
    box("RefineryFurnace", (2.4, 0.18, 1.15), (-1.35, -2.17, 0.62), P.FIRE, "fire")   # noqa: F821
    box("RefineryFurnaceArch", (2.97, 0.12, 1.5), (-1.35, -2.13, 0.78),
        P.STONE_DARK, "stone_dark")
    box("RefineryDoor", (1.05, 0.18, 1.7), (1.5, -2.17, 0.85), P.WOOD_DARK, "wood_dark")  # noqa: F821


def player_home():
    """A COTTAGE. Small, one chimney, nothing industrial.

    This is the original refinery design, reassigned. It was always a house --
    that is exactly why it made a poor refinery, and why it makes a good home.
    Smallest asset in the set, which is the point: a home should read as modest
    beside the businesses an agent builds.
    """
    box("HomeWalls", (4.4, 3.6, 2.5), (0, 0, 1.25), P.SAND, "wall_sand")         # noqa: F821
    gable_roof("HomeRoof", 4.9, 4.0, 2.5, 1.8, P.TERRACOTTA, "roof_terracotta")  # noqa: F821
    box("HomeStack", (0.9, 1.0, 3.0), (1.5, 0.3, 2.6), P.STONE, "stone")         # noqa: F821
    box("HomeStackCap", (1.15, 1.25, 0.3), (1.5, 0.3, 4.2), P.STONE_DARK, "stone_dark")  # noqa: F821
    box("HomeDoor", (0.95, 0.16, 1.6), (-0.6, -1.87, 0.8), P.WOOD_DARK, "wood_dark")     # noqa: F821
    box("HomeWindow", (0.8, 0.12, 0.75), (1.1, -1.85, 1.55), P.WATER, "glass")   # noqa: F821


def farm():
    """A BARN AND SILO over ploughed rows.

    First attempt was a windmill, following Kenney's medievalStructure_14. It
    failed: four sails rotated about the hub rendered as an overlapping asterisk
    and at 31px the whole asset was noise. Kenney gets away with sails because
    they are ALL the sprite is -- no tower, no barn competing for the silhouette.

    Barn plus silo is the replacement. The silo gives the vertical cue the sails
    were supposed to give, without the self-overlap, and crop rows say farm even
    when the building is ambiguous.
    """
    box("FarmBarn", (5.4, 4.0, 2.6), (-1.1, 0.6, 1.3), P.TERRACOTTA, "roof_terracotta")  # noqa: F821
    gable_roof("FarmBarnRoof", 5.9, 4.4, 2.6, 1.9, P.WOOD, "wood",             # noqa: F821
               ridge_frac=0.5)
    # Big barn doors, the second cue after the silo.
    box("FarmDoor", (2.4, 0.18, 2.0), (-1.1, -1.55, 1.0), P.WOOD_DARK, "wood_dark")  # noqa: F821
    box("FarmDoorSplit", (0.14, 0.22, 2.0), (-1.1, -1.6, 1.0), P.WOOD_LIGHT, "wood_light")  # noqa: F821
    # Silo: one clean vertical, no moving parts to overlap.
    cyl("FarmSilo", 1.3, 6.0, (3.1, 0.9, 3.0), P.SAND, "wall_sand", sides=12)  # noqa: F821
    bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=1.45, depth=1.1,
                                    location=(3.1, 0.9, 6.55))
    cap = bpy.context.active_object
    cap.name = "FarmSiloCap"
    cap.data.materials.append(flat_material("roof_green", P.GRASS_MID))         # noqa: F821
    add(cap)                                                                    # noqa: F821
    # Ploughed rows running toward the camera, so they read as rows not stripes.
    for i, cx in enumerate((-3.4, -2.4, -1.4, -0.4, 0.6)):
        box(f"FarmCrop{i}", (0.62, 2.6, 0.32), (cx, -3.2, 0.16), P.WHEAT, "wheat")  # noqa: F821


def mining_operation():
    """A DARK MOUTH in a rock face. Deliberately not a walls-and-roof building.

    Everything else in the set is a building, so making extraction a hole in the
    ground separates the primary tier at a glance -- the tier the whole supply
    chain starts from.

    THREE ATTEMPTS, and the reason the first two failed is worth keeping:

      1. A-frame pithead winder -- angled legs with a drum on top is a catapult.
      2. Pale rock slab with a lip -- a big light basin form lit from above is a
         bathtub.
      3. A black BOX in front of the rock face. A cube is a cube: lit at 48
         degrees it shows its own top face and reads as a crate, not a cavity.

    A hole has to be built as a GAP between masses, never as a dark object. The
    opening here is empty space between two pillars and a lintel, with an unlit
    back wall recessed behind them. That is what makes it read as depth.
    """
    # The arch, built as three separate rock masses with a gap between them.
    box("MineRockL", (2.4, 3.0, 4.2), (-2.9, 1.4, 2.1), P.STONE_DARK, "stone_dark")  # noqa: F821
    box("MineRockR", (2.4, 3.0, 4.2), (2.9, 1.4, 2.1), P.STONE_DARK, "stone_dark")   # noqa: F821
    box("MineRockTop", (7.6, 3.0, 1.5), (0, 1.4, 4.95), P.STONE_DARK, "stone_dark")  # noqa: F821
    box("MineRockCrest", (6.4, 2.2, 0.9), (0, 1.7, 6.1), P.STONE, "stone")           # noqa: F821
    # Back wall, set well behind the opening and never lit -- this is the depth.
    box("MineBack", (3.6, 0.4, 4.2), (0, 2.7, 2.1), "#141414", "pit_black")          # noqa: F821
    box("MineFloor", (3.6, 3.0, 0.2), (0, 1.4, 0.1), "#1e1a16", "pit_floor")         # noqa: F821
    # Timber portal, dark so it frames the gap instead of competing with it. The
    # pale version read as a gold bar sitting across the front.
    for side in (-1, 1):
        box(f"MinePost{side}", (0.45, 0.45, 3.4), (side * 1.95, -0.4, 1.7),
            P.WOOD_DARK, "wood_dark")
    box("MineLintel", (4.6, 0.5, 0.55), (0, -0.4, 3.6), P.WOOD_DARK, "wood_dark")    # noqa: F821
    # A loaded ore cart coming out, which says extraction the way a hole cannot.
    box("MineCart", (1.5, 1.2, 0.85), (0, -2.9, 0.55), P.WOOD_DARK, "wood_dark")   # noqa: F821
    box("MineCartOre", (1.2, 0.95, 0.35), (0, -2.9, 1.1), P.COPPER, "copper")      # noqa: F821
    for side in (-1, 1):
        cyl(f"MineWheel{side}", 0.3, 0.16, (side * 0.75, -2.9, 0.3), P.IRON_DARK,
            "iron_dark", sides=8)


def tavern_inn():
    """A STRIPED AWNING and barrels. Warm where everything else is cool.

    The tavern is where most agents eat, so it has to be findable instantly.
    Colour does that work: it is the only warm-roofed building in the set apart
    from a player's own home.
    """
    box("TavernWalls", (6.2, 4.0, 2.9), (0, 0, 1.45), P.SAND, "wall_sand")      # noqa: F821
    gable_roof("TavernRoof", 6.8, 4.4, 2.9, 1.9, P.TERRACOTTA, "roof_terracotta")  # noqa: F821
    # Awning over the door, striped by alternating two boards.
    for i in range(5):
        colour = P.CLOTH if i % 2 == 0 else P.FIRE
        box(f"TavernAwning{i}", (0.62, 1.5, 0.16), (-1.55 + i * 0.63, -2.6, 2.35),
            colour, "cloth" if i % 2 == 0 else "fire")
    box("TavernDoor", (1.2, 0.18, 1.9), (0, -2.05, 0.95), P.WOOD_DARK, "wood_dark")  # noqa: F821
    for i, bx in enumerate((-2.6, 2.5, 3.2)):
        cyl(f"TavernBarrel{i}", 0.42, 0.95, (bx, -2.5 + (i % 2) * 0.7, 0.47),
            P.WOOD, "wood", sides=8)
    sign("Tavern", 2.9, P.WHEAT)


def weaponsmith_armory():
    """A BIG GLOWING FORGE ARCH and an anvil. One squat stack, not two tall ones.

    Has to stay distinct from the refinery, which is the other fire building.
    The refinery is wide with two tall chimneys; this is compact with one squat
    chimney and a forge mouth that takes up most of the front wall.
    """
    box("SmithWalls", (5.4, 4.0, 2.8), (0, 0, 1.4), P.STONE, "stone")          # noqa: F821
    gable_roof("SmithRoof", 5.9, 4.4, 2.8, 1.7, P.STONE_DARK, "stone_dark",    # noqa: F821
               ridge_frac=0.5)
    box("SmithStack", (1.6, 1.6, 2.2), (-1.9, 0.4, 3.9), P.STONE_DARK, "stone_dark")  # noqa: F821
    # Forge mouth: the identifying feature, so it is huge.
    box("SmithArch", (3.2, 0.16, 2.2), (0.4, -2.02, 1.1), P.WOOD_DARK, "wood_dark")   # noqa: F821
    box("SmithFire", (2.7, 0.14, 1.7), (0.4, -2.06, 0.95), P.FIRE, "fire")     # noqa: F821
    box("SmithEmber", (2.0, 0.12, 0.9), (0.4, -2.1, 0.7), P.GOLD, "gold")      # noqa: F821
    # Anvil on a block outside -- a small thing that says smithy immediately.
    box("SmithBlock", (0.7, 0.7, 0.55), (-2.6, -2.7, 0.28), P.WOOD_DARK, "wood_dark")  # noqa: F821
    box("SmithAnvil", (1.0, 0.42, 0.34), (-2.6, -2.7, 0.72), P.IRON_DARK, "iron_dark")  # noqa: F821


def vehicle_dealer_stable():
    """A WIDE OPEN FRONT -- a dark bay you could drive a cart into.

    Kenney's stand-in (medievalStructure_16) is an open-fronted barn and that is
    right: the opening is the feature. Reinforced with a paddock rail, which
    reads as 'animals' without modelling any.
    """
    box("StableWalls", (7.0, 4.0, 2.9), (0, 0.3, 1.45), P.WOOD, "wood")        # noqa: F821
    gable_roof("StableRoof", 7.6, 4.6, 2.9, 1.9, P.GRASS_DARK, "roof_green_dark")  # noqa: F821
    # The bay: a dark recess, not a door.
    box("StableBay", (4.2, 0.5, 2.3), (0, -1.8, 1.15), "#2b241c", "bay_dark")  # noqa: F821
    box("StableLintel", (4.8, 0.3, 0.4), (0, -1.85, 2.5), P.WOOD_DARK, "wood_dark")  # noqa: F821
    # Paddock rail along the front.
    for i, rx in enumerate((-3.2, -1.1, 1.1, 3.2)):
        box(f"StablePost{i}", (0.22, 0.22, 1.2), (rx, -3.2, 0.6), P.WOOD_DARK, "wood_dark")  # noqa: F821
    box("StableRail", (6.6, 0.16, 0.18), (0, -3.2, 1.0), P.WOOD_DARK, "wood_dark")  # noqa: F821
    for i, hx in enumerate((-2.4, 2.6)):
        box(f"StableHay{i}", (1.0, 0.9, 0.7), (hx, -2.7, 0.35), P.WHEAT, "wheat")  # noqa: F821


def home_improvement_store():
    """STACKED TIMBER under a lean-to. A yard, not a shop.

    Sells Property Upgrades, so the cue is building material in bulk: neat piles
    of cut lumber, which nothing else in the set has.
    """
    box("HIWalls", (4.6, 3.6, 2.7), (-1.3, 0.2, 1.35), P.SAND, "wall_sand")    # noqa: F821
    gable_roof("HIRoof", 5.1, 4.0, 2.7, 1.7, P.GRASS_MID, "roof_green")        # noqa: F821
    box("HIDoor", (1.0, 0.16, 1.7), (-1.3, -1.67, 0.85), P.WOOD_DARK, "wood_dark")  # noqa: F821
    # Lean-to over the timber yard.
    box("HIShedRoof", (4.0, 3.4, 0.22), (2.6, 0.2, 2.35), P.WOOD_DARK, "wood_dark")  # noqa: F821
    for i, px in enumerate((1.0, 4.2)):
        box(f"HIShedPost{i}", (0.24, 0.24, 2.3), (px, -1.3, 1.15), P.WOOD_DARK, "wood_dark")  # noqa: F821
    for row in range(3):
        for i in range(3):
            box(f"HITimber{row}{i}", (2.6, 0.34, 0.32),
                (2.6, -0.9 + i * 0.42, 0.18 + row * 0.36),
                P.WOOD_LIGHT if row % 2 else P.WOOD, "wood_light" if row % 2 else "wood")


def mining_farming_equipment_store():
    """A MARKET STALL with a striped awning and a tool rack.

    Kenney's stand-in is the awninged stall (medievalStructure_22). Kept as a
    stall rather than promoted to a building, because the set needs a small
    open trader to contrast with the walled shops.
    """
    # A SHOPFRONT with a striped awning, not a free-standing stall. The first
    # attempt was an open stall on four posts and it rendered as a fence: with
    # nothing solid behind it, the outline pass drew a row of uprights and the
    # eye read barrier, not shop. It needs mass behind the counter.
    box("EqWalls", (5.6, 3.4, 2.8), (0, 1.0, 1.4), P.SAND, "wall_sand")        # noqa: F821
    gable_roof("EqRoof", 6.1, 3.8, 2.8, 1.6, P.GRASS_DARK, "roof_green_dark",  # noqa: F821
               ridge_frac=0.55)
    box("EqCounter", (5.0, 0.9, 1.1), (0, -1.0, 0.55), P.WOOD, "wood")         # noqa: F821
    box("EqCounterTop", (5.4, 1.3, 0.2), (0, -1.05, 1.2), P.WOOD_LIGHT, "wood_light")  # noqa: F821
    for i in range(6):
        colour = P.CLOTH if i % 2 == 0 else P.FIRE
        box(f"EqAwning{i}", (0.9, 1.6, 0.16), (-2.25 + i * 0.9, -1.7, 2.45),
            colour, "cloth" if i % 2 == 0 else "fire")
    # Tools racked against the wall above the counter -- the identifying detail.
    for i, tx in enumerate((-1.9, -0.65, 0.6, 1.85)):
        blade(f"EqHandle{i}", (0.16, 0.16, 1.9), (tx, -0.55, 1.9), 10 - i * 7,
              P.WOOD, "wood")
        box(f"EqHead{i}", (0.66, 0.28, 0.34), (tx + 0.2, -0.55, 2.75), P.IRON, "iron")  # noqa: F821


# ---------------------------------------------------------------------------
# CHARACTERS -- adult proportions, one trade each
# ---------------------------------------------------------------------------
# REBUILT from chibi. The first set was ~3 heads tall with a big round head,
# which is what makes a 24px figure legible; this set is ~7.5 heads and adult,
# matching a reference of detailed pixel-art tradespeople.
#
# That is a real trade and it is worth being honest about: at 27px on the map a
# 7.5-head figure has a 3px head, and every bit of this detail is invisible.
# These are built to be SEEN LARGER -- rendered into a 96x160 portrait canvas at
# a near-eye-level camera, and drawn bigger on the map to suit. Sprite size and
# figure proportion are the same decision, and this set chose detail.
#
# Each variant is a TRADE, not a palette swap: the reference's characters are
# readable because a smith has bare arms and a hammer and an apron-wearer holds
# a mug. Clothing and props do the identifying work that a 3px face cannot.

BODY_H = 1.78          # as BUILT, metres; LEG_SQUASH shortens it to ~1.52
TURN_DEG = -28.0       # yaw, for a three-quarter view rather than flat-on

# Legs compressed to 72% after building, everything above the hip dropped to
# match. Shortening the legs rather than scaling the whole figure is what makes
# a sprite read as stocky-and-old-school instead of merely small: the head keeps
# its size, so the head-to-body ratio falls from about 6.4 to 5.4, which is the
# classic 16-bit RPG build.
#
# Applied as a transform after the fact rather than by rewriting forty hardcoded
# z-coordinates, which would have been forty chances to put an elbow through a
# ribcage.
LEG_SQUASH = 0.72
HIP_H = 0.92           # top of the thigh in the as-built figure
_LEG_PARTS = ("Thigh", "Shin", "Boot", "Skirt", "Panel")

PERSON_VARIANTS = [
    dict(key="smith",  skin="#c98f63", hair="#d8d4cc", style="short", beard="full",
         shirt="#8a7a68", trousers="#3f4a5a", garment="none", bare_arms=True,
         prop="hammer"),
    dict(key="server", skin="#e8bb92", hair="#c2622a", style="long", beard="none",
         shirt="#d9b8a0", trousers="#5a2740", garment="dress", bare_arms=True,
         prop="tray"),
    dict(key="keeper", skin="#b57a4d", hair="#a8451f", style="bald", beard="full",
         shirt="#3f6b62", trousers="#4a3a2c", garment="apron", bare_arms=False,
         prop="mug", pose="cross"),
    dict(key="ranger", skin="#8a5a33", hair="#2e2118", style="short", beard="none",
         shirt="#cbc0ad", trousers="#5c4a33", garment="vest", bare_arms=False,
         prop="none", pose="hip"),
    dict(key="miner",  skin="#5e3a22", hair="#3a2d1f", style="short", beard="stubble",
         shirt="#7a6a54", trousers="#43382c", garment="belt", bare_arms=True,
         prop="pick"),
]


def _rotate(objects, degrees):
    """Yaw the GIVEN objects about the world Z axis.

    Built facing the camera, then turned. A figure square-on reads as a mugshot;
    the reference's characters are all at three-quarters, which shows both the
    chest and the profile of the face.

    Takes an explicit object list, because the first version rotated everything
    in the collection. Rendering hid it -- the scene is cleared before each
    asset, so there was only ever one figure to rotate. It only surfaced in
    `showcase_all()`, where every new person re-rotated all the buildings and
    vehicles already placed and flung the scene across 100 metres.
    """
    import mathutils
    rot = mathutils.Matrix.Rotation(math.radians(degrees), 4, "Z")
    for obj in objects:
        obj.location = rot @ obj.location
        obj.rotation_euler.z += math.radians(degrees)


def person(variant=0, owner=False):
    """One adult figure, facing the camera before the yaw is applied.

    `owner` adds a hat and cloak. The rendered set MUST carry this: the map
    distinguishes a business owner from an employee, and rebuilding the
    characters without it would have left owners silently falling back to Kenney
    sprites -- a map showing two art styles at once, with nothing failing.
    """
    v = PERSON_VARIANTS[variant % len(PERSON_VARIANTS)]
    k = v["key"]
    _before = set(assets_collection().objects)                              # noqa: F821
    skin, hair = v["skin"], v["hair"]
    shirt, trousers = v["shirt"], v["trousers"]
    dark_shirt = "#2e2620"

    # -- legs ------------------------------------------------------------
    for side in (-1, 1):
        x = side * 0.115
        box(f"{k}Thigh{side}", (0.17, 0.19, 0.44), (x, 0, 0.70), trousers, f"trs{k}")
        box(f"{k}Shin{side}", (0.13, 0.15, 0.40), (x, 0, 0.32), trousers, f"trs{k}")
        box(f"{k}Boot{side}", (0.16, 0.17, 0.17), (x, 0, 0.09), "#3a2a1e", "boot_dark")
        box(f"{k}BootToe{side}", (0.15, 0.11, 0.11), (x, -0.11, 0.06), "#3a2a1e", "boot_dark")

    # -- torso -----------------------------------------------------------
    box(f"{k}Hips", (0.34, 0.22, 0.16), (0, 0, 0.98), trousers, f"trs{k}")
    # A distinct shoulder mass above a narrower waist. The first pass ran one
    # even box from hip to neck and every figure read as a rectangle; the
    # reference's characters are legible mostly by that shoulder-to-waist taper,
    # which survives even when the face does not.
    _ellipsoid(f"{k}Chest", (0, 0, 1.26), (0.20, 0.125, 0.20), shirt, f"shirt{k}")
    _ellipsoid(f"{k}Shoulders", (0, 0, 1.375), (0.245, 0.13, 0.105), shirt, f"shirt{k}")
    box(f"{k}Waist", (0.26, 0.185, 0.22), (0, 0, 1.06), shirt, f"shirt{k}")
    box(f"{k}Belt", (0.36, 0.23, 0.07), (0, 0, 0.98), "#4a3320", "belt_dark")
    box(f"{k}Buckle", (0.08, 0.05, 0.07), (0, -0.12, 0.98), P.GOLD, "gold")

    # -- arms ------------------------------------------------------------
    # ARMS. Straight down on both sides made every figure a shop mannequin; the
    # reference's characters all have at least one arm doing something. A pose
    # is only two numbers -- where the forearm sits and how far it is turned --
    # and it buys more character than any amount of extra geometry.
    sleeve = skin if v["bare_arms"] else shirt
    pose = v.get("pose", "down")
    for side in (-1, 1):
        x = side * 0.235
        bent = (pose == "hip" and side == 1) or pose == "cross"
        ua = box(f"{k}Upper{side}", (0.105, 0.12, 0.32), (x, 0, 1.24), sleeve,
                 f"sleeve{k}")
        ua.rotation_euler = (0.0, math.radians(side * (-14 if bent else -5)), 0.0)
        if pose == "cross":
            fa = box(f"{k}Fore{side}", (0.30, 0.11, 0.095),
                     (side * 0.06, -0.16, 1.14), skin, f"skin{k}")
            fa.rotation_euler = (0.0, 0.0, math.radians(side * -8))
            box(f"{k}Hand{side}", (0.10, 0.11, 0.11), (-side * 0.11, -0.17, 1.14),
                skin, f"skin{k}")
        elif bent:
            fa = box(f"{k}Fore{side}", (0.095, 0.11, 0.30), (x - side * 0.03, -0.02, 0.99),
                     skin, f"skin{k}")
            fa.rotation_euler = (0.0, math.radians(side * 34), 0.0)
            box(f"{k}Hand{side}", (0.10, 0.11, 0.11), (side * 0.155, -0.02, 0.90),
                skin, f"skin{k}")
        else:
            box(f"{k}Fore{side}", (0.095, 0.11, 0.30), (x + side * 0.02, -0.01, 0.94),
                skin, f"skin{k}")
            box(f"{k}Hand{side}", (0.10, 0.11, 0.11), (x + side * 0.03, -0.01, 0.76),
                skin, f"skin{k}")
        if not v["bare_arms"]:
            box(f"{k}Cuff{side}", (0.115, 0.13, 0.07), (x, 0, 1.09), shirt,
                f"shirt{k}")

    # -- garment ---------------------------------------------------------
    g = v["garment"]
    if g == "apron":
        box(f"{k}Apron", (0.34, 0.05, 0.62), (0, -0.135, 0.82), "#7a3b2c", f"apron{k}")
        box(f"{k}ApronBib", (0.22, 0.05, 0.26), (0, -0.135, 1.24), "#7a3b2c", f"apron{k}")
        for side in (-1, 1):
            box(f"{k}ApronStrap{side}", (0.05, 0.06, 0.26), (side * 0.10, -0.10, 1.34),
                "#7a3b2c", f"apron{k}")
    elif g == "vest":
        for side in (-1, 1):
            box(f"{k}Vest{side}", (0.11, 0.06, 0.38), (side * 0.115, -0.12, 1.22),
                "#3f5233", f"vest{k}")
        box(f"{k}VestBack", (0.30, 0.05, 0.38), (0, 0.11, 1.22), "#3f5233", f"vest{k}")
    elif g == "dress":
        bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=0.40, radius2=0.17,
                                        depth=0.92, location=(0, 0, 0.50))
        skirt = bpy.context.active_object
        skirt.name = f"{k}Skirt"
        skirt.data.materials.append(flat_material(f"trs{k}", trousers))     # noqa: F821
        add(skirt)                                                          # noqa: F821
        box(f"{k}Bodice", (0.30, 0.22, 0.30), (0, 0, 1.14), "#3a1c2a", f"bodice{k}")
        box(f"{k}Panel", (0.10, 0.06, 0.60), (0, -0.19, 0.55), "#8f2f3a", f"panel{k}")
    elif g == "belt":
        box(f"{k}Strap", (0.34, 0.06, 0.09), (0, -0.11, 1.22), "#4a3320", "belt_dark")

    # -- head ------------------------------------------------------------
    box(f"{k}Neck", (0.095, 0.095, 0.09), (0, 0, 1.445), skin, f"skin{k}")
    _ellipsoid(f"{k}Head", (0, 0, 1.605), (0.117, 0.113, 0.140), skin, f"skin{k}")
    if v["beard"] == "full":
        # Lower and shallower than the first attempt, which sat so high and so
        # far forward that it covered the eyes and rendered as a pale mask.
        _ellipsoid(f"{k}Beard", (0, -0.042, 1.518), (0.084, 0.070, 0.062), hair,
                   f"hair{k}")
    elif v["beard"] == "stubble":
        _ellipsoid(f"{k}Beard", (0, -0.055, 1.535), (0.080, 0.062, 0.046), hair,
                   f"hair{k}")

    if v["style"] != "bald":
        _ellipsoid(f"{k}Hair", (0, 0.022, 1.648), (0.124, 0.118, 0.116), hair,
                   f"hair{k}")
    if v["style"] == "long":
        _ellipsoid(f"{k}HairBack", (0, 0.062, 1.495), (0.126, 0.092, 0.175), hair,
                   f"hair{k}")
        for side in (-1, 1):
            _ellipsoid(f"{k}HairSide{side}", (side * 0.105, 0.012, 1.525),
                       (0.048, 0.082, 0.145), hair, f"hair{k}")
    # FACE. The first version put two 2cm dots on a 21cm head -- about 1.6px at
    # render size, which is nothing. Bigger eyes, a brow line and a nose, all
    # sitting proud of the skull so the outline pass catches them as shapes.
    for side in (-1, 1):
        box(f"{k}Eye{side}", (0.026, 0.036, 0.030), (side * 0.045, -0.102, 1.622),
            "#241a12", "eye")
    box(f"{k}Nose", (0.024, 0.032, 0.034), (0, -0.113, 1.592), skin, f"skin{k}")

    # -- prop: what the character is FOR ---------------------------------
    prop = v["prop"]
    if prop == "hammer":
        box(f"{k}Haft", (0.035, 0.035, 0.34), (0.27, -0.05, 0.62), P.WOOD, "wood")
        box(f"{k}Head2", (0.10, 0.09, 0.13), (0.27, -0.05, 0.44), P.IRON_DARK,
            "iron_dark")
    elif prop == "tray":
        box(f"{k}Tray", (0.30, 0.22, 0.025), (0.30, -0.10, 0.80), P.WOOD, "wood")
        box(f"{k}Loaf", (0.10, 0.09, 0.07), (0.24, -0.10, 0.84), P.BREAD, "bread")
        cyl(f"{k}Jug", 0.045, 0.11, (0.37, -0.10, 0.86), "#5a3a2a", "jug")
    elif prop == "mug":
        cyl(f"{k}Mug", 0.05, 0.12, (0.27, -0.09, 0.80), "#6b4a32", "jug")
        box(f"{k}MugFoam", (0.09, 0.09, 0.025), (0.27, -0.09, 0.865), P.CLOTH, "cloth")
    elif prop == "pick":
        box(f"{k}PickHaft", (0.035, 0.035, 0.46), (0.28, -0.05, 0.70), P.WOOD, "wood")
        box(f"{k}PickHead", (0.26, 0.05, 0.045), (0.28, -0.05, 0.94), P.IRON_DARK,
            "iron_dark")

    if owner:
        # A brimmed hat and a shoulder cloak: someone who employs people rather
        # than someone who is employed.
        cyl(f"{k}HatBrim", 0.185, 0.022, (0, 0.01, 1.745), "#4a3320", "hat_dark")
        cyl(f"{k}HatCrown", 0.105, 0.115, (0, 0.01, 1.805), "#4a3320", "hat_dark")
        box(f"{k}HatBand", (0.22, 0.22, 0.030), (0, 0.01, 1.762), P.GOLD, "gold")
        box(f"{k}Cloak", (0.40, 0.10, 0.40), (0, 0.115, 1.24), "#5a2a2a", f"cloak{k}")
        for side in (-1, 1):
            box(f"{k}Clasp{side}", (0.055, 0.055, 0.055),
                (side * 0.16, -0.06, 1.385), P.GOLD, "gold")

    made = [o for o in assets_collection().objects if o not in _before]      # noqa: F821
    drop = HIP_H * (1.0 - LEG_SQUASH)
    for obj in made:
        if any(part in obj.name for part in _LEG_PARTS):
            obj.location.z *= LEG_SQUASH
            obj.scale.z *= LEG_SQUASH
        else:
            obj.location.z -= drop
    _rotate(made, TURN_DEG)


def render_people():
    """Five tradespeople -> art/generated/characters/."""
    rig(span=CHARACTER_SPAN_M, elevation=CHARACTER_ELEVATION_DEG,              # noqa: F821
        resolution=CHARACTER_PX)                                               # noqa: F821
    for i, v in enumerate(PERSON_VARIANTS):
        for owner in (False, True):
            clear_assets()                                                     # noqa: F821
            person(i, owner=owner)
            name = f"agent-{i + 1}" + ("-owner" if owner else "")
            render_asset(name, subdir="characters")                            # noqa: F821


# ---------------------------------------------------------------------------
# VEHICLES -- profile, and far more detailed than anything else
# ---------------------------------------------------------------------------
# Rebuilt against a side-on pixel-art reference wagon. The first version was
# nine boxes per animal and a plain crate on two cylinders; held against the
# reference it was a toy. What the reference actually carries, and what had to
# be modelled, is:
#
#   * SPOKED wheels -- a disc reads as a barrel lid, spokes read as a wheel
#   * plank sides with vertical posts, not a smooth box
#   * a horse with an arched neck, a sloping shoulder and JOINTED legs
#   * a long shaft from the wagon to the harness
#
# These render at 14 degrees rather than 48, because every one of those features
# is a profile feature that a high camera destroys.

def spoked_wheel(prefix, cx, cz, radius, s=1.0, spokes=6, tyre=None, hub=None):
    """A wheel seen edge-on: rim, hub and spokes.

    The single largest upgrade over the first version. A cylinder at this angle
    is a featureless disc; the spokes are what say cart rather than barrel, and
    they are cheap -- eight thin boxes on a rotation.
    """
    tyre = tyre or P.WOOD_DARK
    hub = hub or P.SAND
    r = radius * s
    bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=0.10 * s,
                                     major_segments=20, minor_segments=6,
                                     location=(cx, 0, cz),
                                     rotation=(math.radians(90), 0, 0))
    rim = bpy.context.active_object
    rim.name = f"{prefix}Rim"
    rim.data.materials.append(flat_material("tyre", tyre))                  # noqa: F821
    add(rim)                                                                # noqa: F821
    for i in range(spokes):
        a = math.pi * i / spokes
        sp = box(f"{prefix}Spoke{i}", (2 * r * 0.88, 0.10 * s, 0.13 * s),
                 (cx, 0, cz), hub, "spoke")
        sp.rotation_euler = (0.0, a, 0.0)
    cyl(f"{prefix}Hub", 0.20 * s, 0.21 * s, (cx, 0, cz), hub, "spoke", sides=10)
    cyl(f"{prefix}HubCap", 0.075 * s, 0.23 * s, (cx, 0, cz), tyre, "tyre", sides=8)


def wagon(prefix, ox=0.0, s=1.0, length=2.3, coat=None):
    """A plank-sided wagon on four spoked wheels, with a shaft reaching forward.

    Sides are built as separate horizontal planks with vertical posts between,
    because the reference's whole character is in that carpentry. A single box
    with a stripe painted on renders as a crate.
    """
    coat = coat or P.WOOD
    L = length * s

    def at(x, y, z):
        return (ox + x * s, y * s, z * s)

    def sz(x, y, z):
        return (x * s, y * s, z * s)

    box(f"{prefix}Floor", sz(length, 1.05, 0.14), at(0, 0, 0.95), P.WOOD_DARK, "wood_dark")
    # Three planks a side, with a gap between each so the outline pass draws them.
    for side, y in ((0, 0.50), (1, -0.50)):
        for k, z in enumerate((1.10, 1.32, 1.54)):
            box(f"{prefix}Plank{side}{k}", sz(length, 0.09, 0.19), at(0, y, z),
                P.WOOD if k % 2 == 0 else P.WOOD_LIGHT, "wood" if k % 2 == 0 else "wood_light")
    # Vertical posts, taller than the planks, as in the reference.
    posts = [-0.48, -0.16, 0.16, 0.48]
    for side, y in ((0, 0.52), (1, -0.52)):
        for k, f in enumerate(posts):
            box(f"{prefix}Post{side}{k}", sz(0.10, 0.14, 0.72), at(f * length, y, 1.34),
                P.WOOD_DARK, "wood_dark")
    for k, f in enumerate((-0.5, 0.5)):     # corner stanchions, proud of the rail
        for side, y in ((0, 0.52), (1, -0.52)):
            box(f"{prefix}Corner{side}{k}", sz(0.13, 0.16, 0.95),
                at(f * length, y, 1.44), P.WOOD_DARK, "wood_dark")
    box(f"{prefix}Tail", sz(0.11, 1.06, 0.62), at(-length / 2, 0, 1.30),
        P.WOOD, "wood")
    # Axles and four wheels -- rear pair larger, as on the reference.
    for i, (wx, r) in enumerate(((-length * 0.34, 0.64), (length * 0.32, 0.58))):
        box(f"{prefix}Axle{i}", sz(0.10, 1.20, 0.10), at(wx, 0, r), P.WOOD_DARK, "wood_dark")
        for j, wy in enumerate((0.56, -0.56)):
            bpy.ops.object.select_all(action="DESELECT")
            spoked_wheel(f"{prefix}W{i}{j}", ox + wx * s, r * s, r, s=s)
            for obj in list(assets_collection().objects):                   # noqa: F821
                if obj.name.startswith(f"{prefix}W{i}{j}"):
                    obj.location.y += wy * s
    # The shaft: long, thin, and the thing that links cart to animal.
    box(f"{prefix}Shaft", sz(1.5, 0.10, 0.09), at(length * 0.5 + 0.68, 0, 0.92),
        P.WOOD, "wood")
    box(f"{prefix}ShaftBrace", sz(0.14, 0.55, 0.09), at(length * 0.5 + 0.08, 0, 0.92),
        P.WOOD_DARK, "wood_dark")


def _ellipsoid(name, loc, scale, hex_colour, mat_name):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=18, ring_count=12, radius=1.0,
                                         location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(flat_material(mat_name, hex_colour))          # noqa: F821
    add(obj)                                                                # noqa: F821
    return obj


def draught_animal(prefix, ox=0.0, s=1.0, coat=None, dark=None, mane=None,
                   humps=0, harness=True):
    """A horse in profile: barrel, sloping shoulder, arched neck, jointed legs.

    The old version was nine axis-aligned boxes and read as livestock-shaped
    luggage. An animal in profile is recognised by its OUTLINE, and the outline
    is made of curves -- so the body is ellipsoids, the neck is angled, and each
    leg bends at the knee instead of being one straight post.
    """
    coat = coat or "#a06a38"
    dark = dark or "#6e4522"
    mane = mane or "#3a2413"

    def at(x, y, z):
        return (ox + x * s, y * s, z * s)

    def sc(x, y, z):
        return (x * s, y * s, z * s)

    # Legs first so the barrel overlaps their tops. Each is thigh + cannon +
    # hoof, with the cannon angled -- that bend is most of what says "leg".
    for i, (lx, lean) in enumerate(((0.62, -8), (0.50, 6), (-0.60, 8), (-0.72, -6))):
        for j, ly in enumerate((0.20, -0.20)):
            th = box(f"{prefix}Thigh{i}{j}", sc(0.20, 0.17, 0.52), at(lx, ly, 0.78),
                     coat, "coat")
            th.rotation_euler = (0.0, math.radians(lean * 0.5), 0.0)
            cn = box(f"{prefix}Cannon{i}{j}", sc(0.13, 0.13, 0.50),
                     at(lx + lean * 0.006, ly, 0.32), coat, "coat")
            cn.rotation_euler = (0.0, math.radians(lean), 0.0)
            box(f"{prefix}Hoof{i}{j}", sc(0.17, 0.15, 0.13),
                at(lx + lean * 0.012, ly, 0.07), "#2e2118", "hoof")

    _ellipsoid(f"{prefix}Barrel", at(-0.05, 0, 1.06), sc(0.78, 0.36, 0.40), coat, "coat")
    _ellipsoid(f"{prefix}Rump", at(-0.70, 0, 1.10), sc(0.40, 0.35, 0.40), coat, "coat")
    _ellipsoid(f"{prefix}Shoulder", at(0.58, 0, 1.12), sc(0.36, 0.33, 0.38), coat, "coat")
    if humps:
        for i in range(humps):
            _ellipsoid(f"{prefix}Hump{i}", at(-0.30 + i * 0.55, 0, 1.44),
                       sc(0.28, 0.26, 0.26), coat, "coat")

    # NECK AND HEAD. The first profile version made the neck a short stub and
    # the head a flat horizontal slab, so the head read as a separate box
    # floating beside the animal. In the reference the neck is long and arched
    # and the head hangs off the END of it, angled down and forward -- that
    # continuous line from withers to muzzle is what makes a horse a horse.
    neck = box(f"{prefix}Neck", sc(0.38, 0.32, 1.02), at(0.84, 0, 1.58), coat, "coat")
    neck.rotation_euler = (0.0, math.radians(-24), 0.0)
    m = box(f"{prefix}Mane", sc(0.13, 0.22, 1.06), at(0.68, 0, 1.62), mane, "mane")
    m.rotation_euler = (0.0, math.radians(-24), 0.0)
    # Cheek, so the head has mass where it joins the neck instead of a hinge.
    _ellipsoid(f"{prefix}Cheek", at(1.09, 0, 1.99), sc(0.25, 0.17, 0.24), coat, "coat")
    head = box(f"{prefix}Head", sc(0.58, 0.24, 0.28), at(1.24, 0, 1.94), coat, "coat")
    head.rotation_euler = (0.0, math.radians(34), 0.0)
    box(f"{prefix}Muzzle", sc(0.21, 0.21, 0.19), at(1.48, 0, 1.75), dark, "coat_dark")
    for i, ey in enumerate((0.10, -0.10)):
        e = box(f"{prefix}Ear{i}", sc(0.10, 0.08, 0.22), at(1.03, ey, 2.16), coat, "coat")
        e.rotation_euler = (0.0, math.radians(10), 0.0)
    # A small eye. The first one was a 0.26m-wide slab that rendered as a black
    # domino stuck to the side of the skull.
    box(f"{prefix}Eye", sc(0.055, 0.28, 0.055), at(1.15, 0, 2.03), "#241a12", "eye")

    tail = box(f"{prefix}Tail", sc(0.16, 0.16, 0.72), at(-1.02, 0, 0.94), mane, "mane")
    tail.rotation_euler = (0.0, math.radians(-18), 0.0)

    if harness:
        for i, hz in enumerate((1.18,)):
            box(f"{prefix}Girth{i}", sc(0.09, 0.38, 0.44), at(0.36, 0, hz),
                P.LEATHER_DARK, "leather_dark")
        box(f"{prefix}Collar", sc(0.12, 0.34, 0.52), at(0.74, 0, 1.34),
            P.LEATHER_DARK, "leather_dark")


def veh_horse():
    draught_animal("Horse", ox=0.0, s=1.0, coat="#a06a38", dark="#6e4522",
                   mane="#3a2413", harness=False)


def veh_camel():
    """LARGER and YELLOWER than the horse, with two humps -- per the brief. Its
    size difference is real, not implied: the camel is scaled 1.15."""
    draught_animal("Camel", ox=0.0, s=1.15, coat="#e2bd68", dark="#b08c46",
                   mane="#7a5a24", humps=2, harness=False)


def veh_donkey_cart():
    """SMALLER and GREY -- per the brief. A donkey is scaled 0.78 against the
    horse's 1.0, so a cart-and-donkey reads as the modest option it is."""
    wagon("DC", ox=-1.30, s=0.78, length=2.2)
    draught_animal("DCDonkey", ox=1.55, s=0.78, coat="#9aa0a0", dark="#6b7272",
                   mane="#4a5050")


def veh_2_horse_chariot():
    wagon("C2", ox=-1.45, s=0.86, length=2.3)
    for i, (dy, dx) in enumerate(((0.46, 0.0), (-0.46, -0.40))):
        coat = "#a06a38" if i == 0 else "#b87c44"
        draught_animal(f"C2H{i}", ox=1.55 + dx, s=0.86, coat=coat, dark="#6e4522",
                       mane="#3a2413")
        for obj in list(assets_collection().objects):                       # noqa: F821
            if obj.name.startswith(f"C2H{i}"):
                obj.location.y += dy


def veh_4_horse_chariot():
    wagon("C4", ox=-1.70, s=0.82, length=2.5)
    # Four staggered in two ranks, so the team reads as four and not as one.
    for i, (dy, dx) in enumerate(((0.74, 0.0), (0.26, -0.46),
                                  (-0.26, -0.92), (-0.74, -1.38))):
        coat = "#a06a38" if i % 2 == 0 else "#c8934e"
        draught_animal(f"C4H{i}", ox=1.72 + dx, s=0.78, coat=coat,
                       dark="#6e4522", mane="#3a2413")
        for obj in list(assets_collection().objects):                       # noqa: F821
            if obj.name.startswith(f"C4H{i}"):
                obj.location.y += dy


# NO "on-foot" BUILDER. "On Foot" is the absence of a vehicle, not a vehicle, and
# two rendered boots said less than the hand-drawn SVG already did.
# `sprites.vehicle_sprite()` falls back to art/generated/vehicles/on-foot.svg,
# so the entry in D.VEHICLES still resolves and `check()` still passes.
VEHICLE_BUILDERS = {
    "horse": veh_horse,
    "camel": veh_camel,
    "donkey-cart": veh_donkey_cart,
    "2-horse-chariot": veh_2_horse_chariot,
    "4-horse-chariot": veh_4_horse_chariot,
}


BUILDERS = {
    "refinery": refinery,
    "farm": farm,
    "mining-operation": mining_operation,
    "tavern-inn": tavern_inn,
    "weaponsmith-armory": weaponsmith_armory,
    "vehicle-dealer-stable": vehicle_dealer_stable,
    "home-improvement-store": home_improvement_store,
    "mining-farming-equipment-store": mining_farming_equipment_store,
    "player-home": player_home,
}

# Private Security Contractor and Insurance Brokerage are deliberately absent.
# Both are state classes with zero actions -- combat, theft and insurance claims
# are not built yet (PHASE4 section 12), so there is nothing for a player to do
# at either. `sprites.structure_for()` keeps serving the Kenney stand-in until
# there is.


def build(name):
    clear_assets()                                                          # noqa: F821
    BUILDERS[name]()
    print(f"built {name}: {len(assets_collection().objects)} objects")      # noqa: F821


def build_all():
    for name in BUILDERS:
        build(name)
        render_asset(name)                                                  # noqa: F821


def render_vehicles():
    """The six vehicle types -> art/generated/vehicles/, overwriting the SVGs."""
    rig(span=VEHICLE_SPAN_M, elevation=VEHICLE_ELEVATION_DEG,
        resolution=VEHICLE_PX)                                              # noqa: F821
    for name, fn in VEHICLE_BUILDERS.items():
        clear_assets()                                                      # noqa: F821
        fn()
        render_asset(name, subdir="vehicles-3d")                            # noqa: F821


def showcase(spacing=14.0, cols=3):
    """Lay every asset out in a grid, for LOOKING AT -- not for rendering.

    `build()` clears the scene first so a render can never pick up stray
    geometry from the previous asset, which means the viewport only ever shows
    one building and the rest appear to have vanished. They have not: they are
    finished PNGs in art/generated/buildings/, and the scene is a workbench.

    This puts them all out at once so proportions can be compared and edits made
    side by side. Press Home in the viewport to frame them all, and switch the
    viewport to Material Preview -- Solid shading renders everything grey and
    hides every colour decision.

    Rendering after this would capture the whole grid into one sprite, so call
    `build("<name>")` to go back to single-asset mode before `render_asset`.
    """
    clear_assets()                                                          # noqa: F821
    coll = assets_collection()                                              # noqa: F821
    for i, (name, fn) in enumerate(BUILDERS.items()):
        before = set(coll.objects)
        fn()
        dx = (i % cols - (cols - 1) / 2.0) * spacing
        dy = -(i // cols) * spacing
        for obj in coll.objects:
            if obj not in before:
                obj.location.x += dx
                obj.location.y += dy
    print(f"showcase: {len(BUILDERS)} assets in a {cols}-wide grid. "
          f"Home to frame all; Material Preview for colour. "
          f"build('<name>') before rendering again.")


def showcase_all(building_gap=14.0, vehicle_gap=8.0, character_gap=3.0):
    """EVERYTHING in one scene, grouped by category. For looking at, not rendering.

    `build()`, `render_vehicles()` and `render_people()` all clear the scene
    between assets so a render can never pick up stray geometry from the last
    one. The cost is that the viewport only ever shows whatever was made last,
    and the other 24 assets look like they were never built. They were -- they
    are PNGs under art/generated/.

    Laid out in bands rather than one grid because the categories are genuinely
    different sizes: a refinery is 9.4m and a character is 1.3m. Seeing them at
    honest relative scale is useful once, and unreadable as a working layout, so
    each band gets its own spacing.

    Rendering from here would capture the whole scene into one sprite. Call
    `build('<name>')`, `render_vehicles()` or `render_people()` to go back
    to single-asset mode.
    """
    clear_assets()                                                          # noqa: F821
    coll = assets_collection()                                              # noqa: F821

    def place(fn, dx, dy):
        before = set(coll.objects)
        fn()
        for obj in coll.objects:
            if obj not in before:
                obj.location.x += dx
                obj.location.y += dy

    # Buildings: 3 x 3, at the top.
    for i, (name, fn) in enumerate(BUILDERS.items()):
        place(fn, (i % 3 - 1) * building_gap, -(i // 3) * building_gap)

    # Vehicles: one row underneath.
    vy = -3 * building_gap - 4.0
    for i, (name, fn) in enumerate(VEHICLE_BUILDERS.items()):
        place(fn, (i - (len(VEHICLE_BUILDERS) - 1) / 2.0) * vehicle_gap, vy)

    # People: plain row, then owners, at the bottom.
    for row, owner in enumerate((False, True)):
        cy = vy - 9.0 - row * 3.2
        for i in range(len(PERSON_VARIANTS)):
            place(lambda i=i, owner=owner: person(i, owner=owner),
                  (i - (len(PERSON_VARIANTS) - 1) / 2.0) * character_gap, cy)

    total = len(BUILDERS) + len(VEHICLE_BUILDERS) + 2 * len(PERSON_VARIANTS)
    print(f"showcase_all: {total} assets. Home to frame all; Material Preview "
          f"for colour. build('<name>') / render_vehicles() / render_people() "
          f"to return to single-asset mode.")
