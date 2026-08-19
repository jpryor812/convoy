"""What people have said to an agent, and what it said back.

WHY THIS IS NOT WORLD STATE

Advice changes the simulation on purpose: it enters `Agent.inbox`, reaches the
model at a decision, and the agent may act differently because of it. A QUESTION
must not. "Why did you buy charcoal?" is an observer looking in, and if asking it
perturbed the world then no answer about that world could be trusted afterwards
-- you would be measuring the interview.

So conversations live beside a run rather than inside it, in `conversations.json`
in the run directory. Three things follow, all of them wanted:

  * asking is free of consequence, and provably so -- nothing here is reachable
    from `World`;
  * a run that is still going can be questioned WHILE it goes, with no risk of
    two writers racing over `checkpoint.json` (the engine rewrites it every
    simulated hour);
  * the history survives a resume, because it is keyed to the run directory
    rather than to a world object that gets replaced on reload.

WHAT IT IS FOR

An agent that cannot remember you asked it something is not having a
conversation, it is answering a form. History is fed back into the answering
prompt so a follow-up ("what about the second one?") lands, and so a returning
student is recognised rather than met from scratch.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Per agent, per run. Generous -- these are small and a classroom session is
# finite -- but bounded, because the file is rewritten whole on every turn.
MAX_EXCHANGES_KEPT = 200

# How much history goes back into the answering prompt. Small: the retrieved
# DECISIONS are the substance of an answer, and history is there for continuity
# of the conversation, not as a second source of facts. Letting it grow would
# crowd out the record it is meant to be discussed against -- PHASE4 §9's
# argument for keeping reasoning out of `memory_for`, one level up.
DEFAULT_HISTORY_LIMIT = 6


@dataclass
class Exchange:
    """One question and one answer."""

    hour: float                    # the sim hour the run stood at
    who: str                       # who asked
    question: str
    answer: str
    kind: str = "recall"           # recall | synthesis | nothing
    model_called: bool = False


@dataclass
class ConversationStore:
    """Every conversation held about one run, on disk.

    Rewritten whole on each turn rather than appended to, because it is small
    and a valid JSON document is worth more here than a fast write. The write is
    atomic (temp file, then rename) for the same reason `checkpoint.save` is:
    a classroom laptop closing its lid mid-write must not destroy the session.
    """

    path: Path
    by_agent: dict[str, list[Exchange]] = field(default_factory=dict)

    @classmethod
    def load(cls, run_dir: Path | str) -> "ConversationStore":
        path = Path(run_dir) / "conversations.json"
        store = cls(path=path)
        if not path.exists():
            return store
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt history is a lost conversation, not a lost run. Starting
            # empty beats refusing to answer anything.
            return store
        for agent_id, rows in (raw.get("by_agent") or {}).items():
            store.by_agent[agent_id] = [
                Exchange(**{k: v for k, v in row.items() if k in Exchange.__annotations__})
                for row in rows if isinstance(row, dict)
            ]
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"by_agent": {
                    a: [asdict(e) for e in rows] for a, rows in self.by_agent.items()
                }},
                indent=1,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def add(self, agent_id: str, exchange: Exchange) -> None:
        rows = self.by_agent.setdefault(agent_id, [])
        rows.append(exchange)
        if len(rows) > MAX_EXCHANGES_KEPT:
            del rows[:-MAX_EXCHANGES_KEPT]
        self.save()

    def history(
        self, agent_id: str, who: str | None = None, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> list[Exchange]:
        """Recent turns, oldest first.

        Filtered by speaker when one is named, so thirty students questioning the
        same agent do not each inherit the others' conversation -- which would
        be both confusing and a small privacy leak in a classroom.
        """
        rows = self.by_agent.get(agent_id, [])
        if who:
            rows = [e for e in rows if e.who == who]
        return rows[-limit:]
