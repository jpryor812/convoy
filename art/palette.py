"""The Kenney Medieval RTS palette, sampled from the pack itself.

Convoy needs art the pack does not ship -- every vehicle, and an icon for each
of the 63 tradeable goods. Anything drawn by hand has to sit beside 259 CC0
sprites without looking bolted on, and the reliable way to do that is to take
the colours from the pack rather than eyeball them:

    for every opaque pixel in PNG/Default size/**/*.png -> Counter(hex)

898 distinct colours, but the top ~25 carry the pack and are what is below.

The style rules, also read off the pack:
  * flat fills, no gradients;
  * every shape outlined in a DARKER SHADE OF ITSELF, never black;
  * one lighter highlight plane per object, suggesting a light from the north;
  * top-down-ish three-quarter view -- you see the roof and a sliver of wall.
"""

from __future__ import annotations

# -- terrain -----------------------------------------------------------------
GRASS = "#27ae60"
GRASS_DARK = "#115f32"
GRASS_MID = "#1b914d"
GRASS_LIGHT = "#29b865"

ROAD = "#d9a24d"
ROAD_DARK = "#bb8044"
DIRT_DARK = "#775029"

SAND = "#ecdcb8"
SAND_DARK = "#e0d1ae"

STONE = "#acb8b8"
STONE_DARK = "#686d6d"
STONE_LIGHT = "#c1d0d0"

WATER = "#a6e1f5"
WATER_LIGHT = "#b0e9fc"
WATER_PALE = "#e7f9ff"

# -- materials ---------------------------------------------------------------
WOOD = "#a6713b"
WOOD_DARK = "#775029"
WOOD_LIGHT = "#c48647"
TERRACOTTA = "#e27952"

# Metals. Not in the pack -- derived to sit inside its value range, which runs
# roughly #115f32 (darkest) to #ecdcb8 (lightest) with heavy mid-tone use.
COPPER = "#c87137"
COPPER_DARK = "#8f4e26"
TIN = "#b8bcc4"
TIN_DARK = "#7f858f"
IRON = "#8a8f99"
IRON_DARK = "#5c626b"
BRONZE = "#cd8f3f"
BRONZE_DARK = "#8f6127"
LEATHER = "#a6713b"
LEATHER_DARK = "#6f4a26"

BREAD = "#d9a24d"
BREAD_DARK = "#a6713b"
BREAD_FINE = "#ecdcb8"
GOLD = "#f0c14b"
GOLD_DARK = "#b8901f"

WHEAT = "#e3c04f"
WHEAT_DARK = "#a8862c"

FIRE = "#e27952"
FIRE_DARK = "#b8512d"

MUD = "#7b7360"
MUD_DARK = "#544e40"

CLOTH = "#e7f9ff"

# Agent/faction colours, taken from the four unit tints in the pack.
FACTIONS = {
    "blue": "#3a97d4",
    "red": "#d4553a",
    "green": "#1e8449",
    "grey": "#9aa5a5",
}
