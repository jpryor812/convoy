#!/bin/sh
# Shrink a Meshy model for the browser: 1024px WebP textures, about half the
# vertices, no geometry compression (the 3D client has no Draco/Meshopt
# decoder). art/Meshy/<name>-meshy.glb -> art/generated/3d/<name>.glb
#   sh scripts/web_model.sh home [ratio]
set -e
name="$1"; ratio="${2:-0.5}"
cd "$(dirname "$0")/.."
npx -y @gltf-transform/cli@4 optimize "art/Meshy/${name}-meshy.glb" "art/generated/3d/${name}.glb" \
  --compress false --texture-compress webp --texture-size 1024 --simplify-ratio "$ratio"
ls -la "art/generated/3d/${name}.glb"
