"""State checkpointing, so a VM restart does not cost 100 hours of a run.

The whole World is plain dataclasses, so a structural dump round-trips without
custom serializers. Writes are atomic (temp file + rename) so a crash mid-write
cannot leave a truncated checkpoint behind.
"""

from __future__ import annotations

import json
import os
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from . import state as _state
from .state import (
    Activity,
    Agent,
    Bounty,
    Business,
    ChatMessage,
    Consignment,
    Convoy,
    ConvoyMember,
    Employment,
    Government,
    Guild,
    JobPosting,
    Market,
    Plot,
    Property,
    Proposal,
    Reasoning,
    Recommendation,
    ResearchState,
    Snapshot,
    StolenStack,
    TradeOffer,
    Transaction,
    VehicleInstance,
    World,
)

_CLASSES = {
    c.__name__: c
    for c in (
        Activity, Agent, Bounty, Business, ChatMessage, Consignment, Convoy,
        ConvoyMember, Employment, Government, Guild, JobPosting, Market, Plot, Property,
        Proposal, Reasoning, Recommendation, ResearchState, Snapshot, StolenStack,
        TradeOffer, Transaction, VehicleInstance, World,
    )
}


def check() -> list[str]:
    """Every dataclass in `state` must be restorable. Returns the ones that are not.

    THIS EXISTS BECAUSE CHECKPOINTING WAS WRITE-ONLY FOR THREE PHASES.

    `save` walks the object graph generically and will happily encode a type it
    cannot decode; `load` needs the name in `_CLASSES`. So a dataclass added to
    `state.py` and not added here produces checkpoints that write cleanly, look
    right on disk, and raise `KeyError` the moment anyone tries to restore one.
    Nothing in the codebase called `load` in anger, so four types accumulated --
    `ChatMessage`, `JobPosting`, `StolenStack`, `TradeOffer` -- and every
    checkpoint written since chat landed was unrestorable. Found on 2026-08-18
    by the first code that actually tried to read one back.

    Run from `run_phase1.py` beside the economic invariants and the sprite
    check, for the same reason those are: it is cheap, it depends on a file
    people edit often, and its failure mode is losing a twelve-hour run.
    """
    import dataclasses
    import inspect

    declared = {
        name for name, obj in inspect.getmembers(_state, inspect.isclass)
        if dataclasses.is_dataclass(obj) and obj.__module__ == _state.__name__
    }
    return sorted(declared - set(_CLASSES))


def _encode(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            "__type__": type(obj).__name__,
            **{f.name: _encode(getattr(obj, f.name)) for f in fields(obj)},
        }
    if isinstance(obj, dict):
        return {"__dict__": [[_encode(k), _encode(v)] for k, v in obj.items()]}
    if isinstance(obj, (list, tuple)):
        return {"__seq__": [_encode(v) for v in obj], "__tuple__": isinstance(obj, tuple)}
    return obj


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "__type__" in obj:
            cls = _CLASSES[obj["__type__"]]
            kwargs = {k: _decode(v) for k, v in obj.items() if k != "__type__"}
            return cls(**kwargs)
        if "__dict__" in obj:
            return {_decode(k): _decode(v) for k, v in obj["__dict__"]}
        if "__seq__" in obj:
            seq = [_decode(v) for v in obj["__seq__"]]
            return tuple(seq) if obj.get("__tuple__") else seq
    return obj


def save(world: World, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_encode(world)), encoding="utf-8")
    os.replace(tmp, path)


def load(path: Path | str) -> World:
    return _decode(json.loads(Path(path).read_text(encoding="utf-8")))
