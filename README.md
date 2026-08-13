# Convoy — Agent Sandbox Validation Build

A **headless economic simulation** of a Bronze & Iron Age trading-and-piracy
economy. No rendering, no game client, no human players: 75 AI agents (15 each
across 5 models, via OpenRouter) live in the economy for 120 real hours, each
trying to maximise its own Net Worth. The run exists to validate that the
designed economic rules produce interesting, legible behaviour **before** any
visual build, and to generate unscripted material for a later human-facing game.

The economy is fully specified in [`convoy_bronze_age_economy.xlsx`](convoy_bronze_age_economy.xlsx)
(19 tabs) — the source of truth. [`convoy_reference.md`](convoy_reference.md) is a
flattened, searchable snapshot of it. [`claude_code_handoff_prompt.md`](claude_code_handoff_prompt.md)
is the build brief.

## Status

| Phase | State |
|---|---|
| 1 — Core engine, zero LLM calls | **Complete.** See [PHASE1.md](PHASE1.md). |
| 2 — One model, 2–3 agents | Not started (needs `OPENROUTER_API_KEY`) |
| 3 — Full 75-agent roster | Not started |
| 4 — Memory & reporting layer | Not started |
| 5 — The real 120-hour run | Not started |

Phase 1 builds the whole economy and drives it with deterministic rule-based
agents. The world (one dangerous road, seven places, eight spur roads), the
production chain, staffing/output math, sustenance, taxes, research, chat,
guilds, player-to-player trade, and land are all live and tested. The observation
layer, OpenRouter client, and action schemas that Phase 2 needs do not exist yet.

## Requirements

Python 3.11+. **No third-party dependencies** — the package is pure standard
library. (`openpyxl` is only needed to read the spreadsheet directly, which the
simulation never does.)

## Running it

```bash
python3 run_phase1.py                    # 48 game-hours, 10 agents
python3 run_phase1.py --hours 120 --agents 75
```

Output lands in `runs/phase1/` (git-ignored): a raw timestamped event log as
both JSONL and CSV, plus a `state.json` checkpoint. The run is deterministic for
a given `--seed`, prints a summary, and exits non-zero if any invariant is
violated.

## Tests

```bash
python3 tests/test_conformance.py        # implementation vs. the spreadsheet's worked examples
python3 tests/test_staffing_load.py      # live-engine output vs. the diminishing-returns curve
python3 tests/test_social.py             # chat isolation, invite-only guilds, P2P trade
python3 tests/test_property_and_tools.py # property upgrades, Upgraded Tools
python3 tests/test_safehouse.py          # stolen-goods laundering, weekly property tax
```

Every conformance test asserts a number the workbook states explicitly, so a
spreadsheet rebalance that isn't mirrored in code fails loudly.

## Layout

```
convoy/
  data.py          static game data, transcribed from the workbook
  world_map.py     the road, its segments and danger, the spur roads, land
  state.py         the 10 World State Schema entities
  economy.py       pricing, output math, wages, taxes, sustenance, net worth
  actions.py       the executable action layer agents resolve onto
  engine.py        clock, continuous processes, decision scheduling
  rule_agents.py   Phase 1 deterministic policies (throwaway test tools)
  events.py        significance-tagged event log
  checkpoint.py    atomic state save/load
  world_setup.py   government businesses + agent spawning
run_phase1.py      the Phase 1 runner and invariant checks
tests/             conformance and behavioural tests
PHASE1.md          full Phase 1 write-up and design-decision log
```

## Design decisions

The workbook left some rules ambiguous or unspecified, and a number of balance
and design choices were made during the build. Every one is recorded in
[PHASE1.md](PHASE1.md) — including the ones the spreadsheet itself should be
updated to match, so the two don't drift.
