# Reference builds

Snapshots kept so a later change can be compared against what came before.

## full-valley-map.html

The valley as it stood on 2026-08-20 at the end of the art pass: seven places on
the road, sixteen spurs, both protected zones, 216 building slots and 864 plots.
Pipoya ground and buildings, Kenney people, the land grid with streets, and the
river on the bridge segment.

Rendered pages are gitignored everywhere else (`*.html`) because they are built
artefacts. This one is committed on purpose -- it is the thing to look at when
asking "did the demo map lose something the full one had?", and regenerating it
otherwise means checking the branch out.

## The three worlds

| where | places | spurs | plots | sites | for |
|---|---|---|---|---|---|
| `demo-map` (HEAD) | 3 | 4 | 160 | 40 | **current** -- 20 agents, land binds |
| `demo-map` @ `b74fa49` | 5 | 10 | 308 | 77 | ~50 agents |
| `full-valley-map` | 7 | 16 | 864 | 216 | the full valley |

All three pass their tests and invariants. The differences are entirely in
`convoy/world_map.py` and the place-keyed tables in `convoy/layout.py`; the
economy, the art pipeline and the click-through UI are shared.

Regenerate any of them with `python3 preview_world.py`.
