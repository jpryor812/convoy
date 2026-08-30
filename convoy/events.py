"""Significance-tagged event log.

One log serves three consumers: engine debugging, per-agent memory, and the
daily/rollup report generator (Phase 4). Per the handoff, there is deliberately
no second logging system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterator


class Significance(IntEnum):
    """Routine actions are LOW; story beats are HIGH."""

    LOW = 1       # a mining tick, a wage payment, a routine sale
    MEDIUM = 2    # job change, business founded, notable trade, price change
    HIGH = 3      # bankruptcy, successful heist, passed policy, death, monopoly


# Default significance per event type. Anything unlisted defaults to LOW.
SIGNIFICANCE: dict[str, Significance] = {
    "sim_start": Significance.HIGH,
    "sim_end": Significance.HIGH,
    "business_founded": Significance.HIGH,
    # A robbery is a story beat -- it is the one thing that happens TO an agent
    # on the road rather than because it chose something, and it is what the
    # whole convoy system exists to make legible.
    "robbed": Significance.HIGH,
    "convoy_loss_covered": Significance.MEDIUM,
    "escort_hired": Significance.MEDIUM,
    "business_bankrupt": Significance.HIGH,
    "business_closed": Significance.HIGH,
    "bankruptcy_warning": Significance.MEDIUM,
    "agent_died": Significance.HIGH,
    "starved_to_death": Significance.HIGH,
    "sustenance_starving": Significance.MEDIUM,
    "sustenance_hungry": Significance.MEDIUM,
    "ate": Significance.LOW,
    "policy_enacted": Significance.HIGH,
    "policy_reversed": Significance.HIGH,
    "heist_success": Significance.HIGH,
    "convoy_ambushed": Significance.HIGH,
    "convoy_destroyed": Significance.HIGH,
    "bounty_confirmed": Significance.HIGH,
    "research_tier_unlocked": Significance.HIGH,
    "research_allocated": Significance.HIGH,
    "assets_wiped": Significance.HIGH,
    "chat": Significance.MEDIUM,
    "guild_created": Significance.HIGH,
    "guild_joined": Significance.MEDIUM,
    "guild_invited": Significance.LOW,
    "guild_left": Significance.MEDIUM,
    "guild_removed": Significance.MEDIUM,
    "trade_offered": Significance.MEDIUM,
    "trade_accepted": Significance.HIGH,
    "trade_declined": Significance.LOW,
    "looted": Significance.MEDIUM,
    "stolen_goods_taken": Significance.HIGH,
    "stolen_goods_stashed": Significance.MEDIUM,
    "stolen_goods_laundered": Significance.HIGH,
    "inputs_sourced": Significance.LOW,
    "site_full": Significance.MEDIUM,
    "site_expanded": Significance.MEDIUM,
    "property_upgraded": Significance.MEDIUM,
    "tools_equipped": Significance.MEDIUM,
    "convoy_completed": Significance.MEDIUM,
    "convoy_posted": Significance.MEDIUM,
    "convoy_departed": Significance.MEDIUM,
    "hired": Significance.MEDIUM,
    "fired": Significance.MEDIUM,
    "quit_job": Significance.MEDIUM,
    "job_started": Significance.MEDIUM,
    "vehicle_purchased": Significance.MEDIUM,
    "property_purchased": Significance.MEDIUM,
    "price_set": Significance.MEDIUM,
    "insurance_issued": Significance.MEDIUM,
    "insurance_claim_paid": Significance.HIGH,
    "production": Significance.LOW,
    "wages_paid": Significance.LOW,
    "trade": Significance.LOW,
    "travel": Significance.LOW,
    "decision": Significance.LOW,
    "tax_collected": Significance.LOW,
    "road_tax_collected": Significance.MEDIUM,
    "policy_enacted": Significance.HIGH,
    "diary": Significance.LOW,
}


@dataclass
class Event:
    sim_time: float               # seconds since hour 0
    type: str
    significance: int
    actor: str | None = None      # Agent ID
    subject: str | None = None    # Business/Convoy/Agent ID the action targets
    location: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def sim_hour(self) -> float:
        return self.sim_time / 3600.0

    def format(self) -> str:
        h = int(self.sim_hour)
        m = int((self.sim_time % 3600) // 60)
        who = self.actor or "-"
        bits = " ".join(f"{k}={v}" for k, v in self.detail.items())
        return f"[{h:03d}:{m:02d}] {self.type:<22} {who:<14} {bits}"


class EventLog:
    """Append-only log with a JSONL sink so a 120-hour run survives a VM restart."""

    def __init__(self, path: Path | str | None = None, echo_min: int = Significance.HIGH):
        self.events: list[Event] = []
        self.path = Path(path) if path else None
        self.echo_min = echo_min
        self._fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")

    def replay(self, path: Path | str | None = None) -> int:
        """Load an existing JSONL back into memory, without rewriting it.

        Needed to RESUME a world. `memory_for` answers "what has happened to me
        lately?" by walking `self.events`, so a resumed run whose log started
        empty would give every agent total amnesia at the moment it came back --
        precisely the failure `memory_for` was written to prevent, reintroduced
        by the restart rather than by the observation.

        Returns the number of events loaded. A missing or malformed file is not
        fatal: continuing with a thinner memory beats refusing to resume a run
        that is otherwise perfectly restorable.
        """
        src = Path(path) if path else self.path
        if not src or not src.exists():
            return 0
        loaded = 0
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                self.events.append(Event(
                    sim_time=raw["sim_time"], type=raw["type"],
                    significance=raw.get("significance", Significance.LOW),
                    actor=raw.get("actor"), subject=raw.get("subject"),
                    location=raw.get("location"), detail=raw.get("detail") or {},
                ))
                loaded += 1
            except (ValueError, KeyError, TypeError):
                continue                  # a torn final line from a killed run
        return loaded

    def emit(
        self,
        sim_time: float,
        type: str,
        *,
        actor: str | None = None,
        subject: str | None = None,
        location: str | None = None,
        significance: Significance | None = None,
        **detail: Any,
    ) -> Event:
        sig = significance if significance is not None else SIGNIFICANCE.get(type, Significance.LOW)
        ev = Event(sim_time, type, int(sig), actor, subject, location, detail)
        self.events.append(ev)
        if self._fh:
            self._fh.write(json.dumps(asdict(ev)) + "\n")
        if sig >= self.echo_min:
            print(ev.format())
        return ev

    def flush(self) -> None:
        if self._fh:
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    # -- querying, for the Phase 4 report generator ------------------------

    def since(self, sim_time: float) -> Iterator[Event]:
        return (e for e in self.events if e.sim_time >= sim_time)

    def by_actor(self, agent_id: str) -> Iterator[Event]:
        return (e for e in self.events if e.actor == agent_id)

    def at_least(self, sig: Significance) -> Iterator[Event]:
        return (e for e in self.events if e.significance >= sig)

    def export_csv(self, path: Path | str) -> Path:
        """Flat CSV of every event -- the reviewable Phase 1 deliverable."""
        import csv

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["sim_hour", "sim_time_s", "type", "significance",
                 "actor", "subject", "location", "detail"]
            )
            for e in self.events:
                writer.writerow([
                    f"{e.sim_hour:.4f}", f"{e.sim_time:.0f}", e.type, e.significance,
                    e.actor or "", e.subject or "", e.location or "",
                    json.dumps(e.detail, separators=(",", ":")),
                ])
        return path

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.events:
            out[e.type] = out.get(e.type, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
