"""Hourly and daily digests of what the world is actually doing.

TWO REGISTERS, ON PURPOSE

  HOURLY  deterministic. Facts and deltas, no network. It fires 72 times in an
          unattended half-day run, so it must cost nothing and must not have a
          way to fail.

  DAILY   narrated by a model, from the deterministic digest. Three calls in a
          72-hour run, a fraction of a cent.

The daily narrator is given the assembled FACTS and asked only to tell their
story -- it never sees the raw log and is told not to invent. That keeps it a
writing task rather than an analysis task, which is the difference between a
chronicle and a hallucination. If the call fails for any reason the day still
gets its deterministic digest, because a 14-hour run must not lose its report
to one HTTP timeout.

What makes a line interesting is CHANGE, so everything is a delta against the
previous digest rather than a running total. A wealth leaderboard that says the
same thing twelve times is noise; "three agents quit the General Store" is a
story.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from .events import EventLog
from .state import World

NARRATOR_MODEL = "openai/gpt-5.6-luna"
NARRATOR_MAX_TOKENS = 1400
NARRATOR_TIMEOUT_S = 120.0

_NARRATOR_SYSTEM = (
    "You are the chronicler of Convoy, a Bronze Age valley economy inhabited by "
    "independent agents. You will be given the factual digest of one simulated "
    "day. Write it up as several paragraphs of flowing narrative -- who rose, "
    "who struggled, where people worked, what they wanted and could not have, "
    "and how the day differed from the one before.\n\n"
    "Rules. Use ONLY facts present in the digest; never invent an event, a name, "
    "or a number. Refer to agents by their given names. Where the digest shows "
    "agents repeatedly attempting something the world refused, say so plainly -- "
    "that is the most interesting thing in any day. Do not use bullet points or "
    "headings. Do not moralise or give advice. Write as a historian describing "
    "what happened, in past tense."
)

# Event types that say something happened to the world, as opposed to the
# engine's own bookkeeping or an agent narrating itself.
_NOTABLE = (
    "hired", "fired", "quit", "business_founded", "business_closed",
    "property_bought", "vehicle_bought", "died", "starved", "robbed",
    "theft", "combat", "bounty_posted", "guild_formed", "proposal_passed",
    "loan_taken", "insurance_claim_paid",
)


def _wealth(world: World) -> list[tuple[str, float]]:
    return sorted(
        ((a.name, a.net_worth(world)) for a in world.agents.values() if a.alive),
        key=lambda kv: -kv[1],
    )


def _since(log: EventLog, from_time: float) -> list:
    return [e for e in log.events if e.sim_time > from_time]


def hourly(world: World, log: EventLog, from_time: float) -> str:
    """A few sentences on the last simulated hour."""
    evs = _since(log, from_time)
    hour = world.sim_time / 3600.0
    lines = [f"## hour {hour:.0f}"]

    alive = [a for a in world.agents.values() if a.alive]
    wealth = _wealth(world)
    if wealth:
        median = wealth[len(wealth) // 2][1]
        lines.append(
            f"{len(alive)} alive. Richest {wealth[0][0]} at {wealth[0][1]:,.0f}, "
            f"poorest {wealth[-1][0]} at {wealth[-1][1]:,.0f}, median {median:,.0f}."
        )

    hungry = [a.name for a in alive if a.sustenance_stage != "Normal"]
    if hungry:
        lines.append(f"Not fed: {', '.join(hungry[:6])}.")

    notable = [e for e in evs if e.type in _NOTABLE]
    if notable:
        seen = Counter(e.type for e in notable)
        lines.append("Happened: " + ", ".join(f"{n}x {t}" for t, n in seen.most_common(6)) + ".")

    # What the world refused is the most useful signal in the whole log: it is
    # an agent stating an intention the simulation could not satisfy.
    refused = Counter(
        e.detail.get("detail_text", "?") for e in evs
        if e.type == "action_call" and not e.detail.get("ok", True)
    )
    if refused:
        lines.append(
            "Refused: " + "; ".join(f"{r} (x{n})" for r, n in refused.most_common(3)) + "."
        )

    working = sum(1 for a in alive if a.activity.kind == "work")
    idle = sum(1 for a in alive if a.activity.kind == "idle")
    lines.append(f"{working} working, {idle} idle, treasury {world.government.treasury:,.0f}.")
    return "\n".join(lines)


def daily(world: World, log: EventLog, from_time: float, day: int | None = None) -> str:
    """A fuller digest, once per simulated day."""
    evs = _since(log, from_time)
    # Counted, not derived from the clock: with a custom --day-hours the two
    # disagree, and a digest headed "DAY 0" next to a chronicle headed "DAY 1"
    # is just confusing.
    n = day if day is not None else int(world.sim_time // 86400) + 1
    lines = ["", "=" * 60, f"# DAY {n}", "=" * 60]

    wealth = _wealth(world)
    lines.append("\nWealth:")
    for name, nw in wealth[:8]:
        lines.append(f"  {name:<24}{nw:>12,.1f}")
    if len(wealth) > 8:
        lines.append(f"  ... and {len(wealth) - 8} more")

    owners = [a for a in world.agents.values() if a.owned_businesses]
    if owners:
        lines.append("\nBusiness owners:")
        for a in owners:
            names = ", ".join(
                world.businesses[b].name for b in a.owned_businesses
                if b in world.businesses
            )
            lines.append(f"  {a.name}: {names}")

    employed = Counter(
        world.businesses[a.current_job[0]].name
        for a in world.agents.values()
        if a.current_job and a.current_job[0] in world.businesses
    )
    if employed:
        lines.append("\nEmployment:")
        for biz, n in employed.most_common():
            lines.append(f"  {n:>3}  {biz}")

    tried = Counter(
        e.detail.get("action") for e in evs if e.type == "action_call"
    )
    if tried:
        lines.append("\nWhat agents tried today:")
        for act, n in tried.most_common(10):
            lines.append(f"  {n:>4}  {act}")

    refused = Counter(
        e.detail.get("detail_text", "?") for e in evs
        if e.type == "action_call" and not e.detail.get("ok", True)
    )
    if refused:
        lines.append("\nWhat the world refused today:")
        for reason, n in refused.most_common(10):
            lines.append(f"  {n:>4}  {reason}")

    lines.append(f"\nTreasury: {world.government.treasury:,.1f}")
    lines.append("=" * 60)
    return "\n".join(lines)


def narrate(facts: str, api_key: str | None, model: str = NARRATOR_MODEL) -> str | None:
    """Turn the day's factual digest into prose. None if it cannot."""
    if not api_key:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _NARRATOR_SYSTEM},
            {"role": "user", "content": facts},
        ],
        "max_tokens": NARRATOR_MAX_TOKENS,
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Convoy",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=NARRATOR_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None
    choices = data.get("choices") or []
    if not choices:
        return None
    return ((choices[0].get("message") or {}).get("content") or "").strip() or None


class Chronicler:
    """Stateful hook for `Engine(on_checkpoint=...)`.

    Holds the previous digest's sim_time so every report is a delta, and writes
    to a file as well as stdout -- stdout scrolls, the file is what you read the
    next morning.
    """

    def __init__(
        self, world: World, log: EventLog, path: Path, day_hours: float = 24.0,
        api_key: str | None = None, narrate_days: bool = True,
    ):
        self.log = log
        self.path = Path(path)
        self.day_hours = day_hours
        self.narrate_days = narrate_days
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._last_hourly = world.sim_time
        self._last_daily = world.sim_time
        self.day = 0
        self.path.write_text("# Convoy chronicle\n", encoding="utf-8")

    def __call__(self, world: World) -> None:
        chunks = [hourly(world, self.log, self._last_hourly)]
        self._last_hourly = world.sim_time

        if (world.sim_time - self._last_daily) >= self.day_hours * 3600.0:
            self.day += 1
            facts = daily(world, self.log, self._last_daily, self.day)
            self._last_daily = world.sim_time
            story = narrate(facts, self.api_key) if self.narrate_days else None
            if story:
                chunks.append(
                    f"\n{'=' * 60}\n# DAY {self.day} — THE CHRONICLE\n{'=' * 60}\n\n{story}\n"
                )
            # The facts go in either way: the narration is a reading of them,
            # not a replacement, and if the call failed this is the whole report.
            chunks.append(facts)

        text = "\n".join(chunks)
        print(text, flush=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
