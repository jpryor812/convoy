# Reference builds

Snapshots kept so a later change can be compared against what came before.

## full-valley-map.html

The valley as it stood on 2026-08-20, at the end of the art pass: seven places
on the road, sixteen spurs, both protected zones, 216 building slots and 864
plots. Pipoya ground and buildings, Kenney people, the land grid with streets,
and the river on the bridge segment.

Rendered pages are gitignored everywhere else (`*.html`) because they are built
artefacts. This one is committed on purpose -- it is the thing to look at when
asking "did the demo map lose something the full one had?", and regenerating it
means checking out the branch below.

Regenerate with `python3 preview_world.py`.

## Branches

  * `full-valley-map` -- the full seven-place world, complete and passing.
  * `demo-map`        -- the smaller world built from it for 20-agent runs.
