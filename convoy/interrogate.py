"""Asking a finished run questions, and answering from the record.

THE RULE THIS MODULE EXISTS TO ENFORCE

Answer from what the agent actually said. Call a model only when a question
genuinely needs several decisions weighed together, and even then, ground it in
retrieved text and cite the hours.

That is not a cost optimisation, though it is also that (thirty students asking
twenty questions is 600 calls a session). It is the whole point of PHASE4 §9.
Before reasoning capture, "why did you buy charcoal at hour 40?" could only be
answered by a model inventing a plausible-sounding motive, because nothing had
stored the real one. Now the real one is on disk. Regenerating it would throw
away the only thing that makes the classroom exercise work: a student can check
the answer against the transcript and catch it being wrong.

So every answer carries CITATIONS -- hour, what the agent did, and its own words
-- and `kind` says plainly which of the two happened:

    recall     lifted from the record; no model was called
    synthesis  a model was called, over the cited decisions only
    nothing    the record has no answer, and it says so instead of guessing

`nothing` is a first-class outcome. An interrogation tool that always produces
an answer teaches students that agents always have reasons, which is false and
is the opposite of the lesson.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUN_DIR = Path("runs/phase2")

# Decisions retrieved for one question. Enough to see a pattern, few enough that
# a synthesis prompt stays small and a reader can check every citation.
MAX_CITATIONS = 8

# Words that mean "weigh several things together", which the record cannot do by
# itself. Everything else is treated as a lookup, because a lookup is truthful
# and free and most questions are lookups.
_SYNTHESIS_WORDS = frozenset({
    "overall", "strategy", "strategic", "generally", "pattern", "patterns",
    "compare", "compared", "better", "worse", "best", "worst", "smart", "wise",
    "mistake", "mistakes", "wrong", "right", "should", "shouldve", "could",
    "would", "summarise", "summarize", "summary", "explain", "assess",
    "evaluate", "judge", "opinion", "think", "learn", "learned", "advice",
    "improve", "instead", "rather", "why not", "trend", "across", "throughout",
})

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "did", "do", "does", "you", "your",
    "was", "were", "is", "are", "at", "in", "on", "of", "to", "for", "it",
    "that", "this", "with", "what", "when", "where", "who", "how", "why",
    "hour", "hours", "me", "my", "i", "not", "no", "yes", "so", "then",
    "there", "their", "them", "they", "he", "she", "we", "us", "have", "had",
    "has", "been", "be", "will", "can", "could", "would", "should", "about",
})


@dataclass
class Citation:
    """One decision, quoted rather than summarised."""

    hour: float
    woken_because: str
    did: str
    text: str
    # What the agent owned at that decision, when the run recorded it. Runs made
    # before 2026-08-18 have none, so this is always optional -- an interrogation
    # tool that only worked on the newest run would be useless on every run
    # already sitting on disk.
    assets: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "hour": self.hour, "woken_because": self.woken_because,
            "did": self.did, "text": self.text,
        }
        if self.assets:
            out["assets"] = self.assets
        return out

    def position(self) -> str:
        """The holdings line for a prompt, or nothing at all.

        Compressed hard: this is appended to EVERY cited decision, and a
        question that pulls eight of them would otherwise spend more of the
        prompt on balance sheets than on what the agent was thinking. Businesses
        carry cash and payroll because those are the two numbers behind every
        insolvency in the last run; everything else is a count.
        """
        a = self.assets
        if not a:
            return ""
        bits = [f"{a.get('denari', 0):.0f}d"]
        if a.get("net_worth") is not None:
            bits.append(f"worth {a['net_worth']:.0f}")
        for b in a.get("businesses") or ():
            bits.append(
                f"{b.get('type', 'business')}[cash {b.get('cash', 0):.0f}, "
                f"payroll {b.get('payroll_per_hour', 0):.0f}/h]"
            )
        if a.get("vehicles"):
            bits.append(f"{len(a['vehicles'])} vehicle(s)")
        if a.get("home"):
            bits.append("a home")
        if job := a.get("job"):
            bits.append(f"job {job.get('role')} at {job.get('wage', 0):.0f}/h")
        if carrying := a.get("carrying"):
            bits.append(
                "carrying " + ", ".join(f"{v}x {k}" for k, v in carrying.items())
            )
        return " | ".join(bits)


@dataclass
class Answer:
    kind: str                                  # recall | synthesis | nothing
    text: str
    citations: list[Citation] = field(default_factory=list)
    model_called: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "model_called": self.model_called,
            "citations": [c.as_dict() for c in self.citations],
        }


# ---------------------------------------------------------------------------
# LOADING
# ---------------------------------------------------------------------------

def newest_run() -> Path:
    runs = [d for d in RUN_DIR.iterdir() if (d / "events.jsonl").exists()]
    if not runs:
        raise SystemExit(f"no runs with an events.jsonl under {RUN_DIR}")
    return max(runs, key=lambda d: d.stat().st_mtime)


def _names_from_checkpoint(run_path: Path) -> dict[str, str]:
    """Display names, which the event log does not carry.

    Read straight out of the checkpoint JSON rather than through
    `checkpoint.load`, because this must not fail. The checkpoint of a RUNNING
    run is rewritten every simulated hour, so a read can land mid-rename and get
    a truncated file; and a demo that cannot show a transcript because it could
    not show a name is a bad trade. No names is a cosmetic loss -- ids are still
    correct -- so every failure here degrades to an empty map.
    """
    path = run_path / "checkpoint.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        agents = raw.get("agents", {}).get("__dict__", [])
        return {
            entry[0]: entry[1]["name"]
            for entry in agents
            if isinstance(entry, list) and len(entry) == 2
            and isinstance(entry[1], dict) and "name" in entry[1]
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}


@dataclass
class Run:
    """A finished run, indexed for questioning.

    The event log is the source, not the checkpoint. A checkpoint holds only the
    last 40 decisions per agent (`MAX_REASONING_KEPT`) because that is the
    working set an agent reasons with; the log holds every one, and an
    84-hour interrogation needs hour 12 as much as hour 80.
    """

    path: Path
    events: list[dict] = field(default_factory=list)
    by_agent: dict[str, list[dict]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Run":
        path = Path(path) if path else newest_run()
        events = [
            json.loads(line)
            for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        run = cls(path=path, events=events)
        for e in events:
            actor = e.get("actor")
            if actor and actor.startswith("A"):
                run.by_agent.setdefault(actor, []).append(e)
        run.names = _names_from_checkpoint(path)
        return run

    # -- summary -----------------------------------------------------------

    def hours(self) -> float:
        return round(max((e["sim_time"] for e in self.events), default=0.0) / 3600.0, 2)

    def summary(self) -> dict[str, Any]:
        agents = []
        for aid, evs in sorted(self.by_agent.items()):
            decisions = [e for e in evs if e["type"] == "llm_reasoning"]
            agents.append({
                "id": aid,
                "name": self._name(aid),
                "decisions": len(decisions),
                "with_reasoning": sum(
                    1 for e in decisions
                    if (e["detail"].get("text") or "").strip()
                    and not e["detail"]["text"].startswith("(acted without")
                ),
                "actions": sum(1 for e in evs if e["type"] == "action_call"),
                "advice_received": sum(1 for e in evs if e["type"] == "advice_delivered"),
                "last_seen_hour": round(
                    max(e["sim_time"] for e in evs) / 3600.0, 2
                ),
                "alive": not any(e["type"] == "starved_to_death" for e in evs),
            })
        return {
            "run": str(self.path),
            "events": len(self.events),
            "sim_hours": self.hours(),
            "agents": agents,
        }

    def _name(self, agent_id: str) -> str:
        return self.names.get(agent_id, agent_id)

    # -- one agent ---------------------------------------------------------

    def decisions(self, agent_id: str) -> list[Citation]:
        out = []
        for e in self.by_agent.get(agent_id, ()):
            if e["type"] != "llm_reasoning":
                continue
            d = e["detail"]
            out.append(Citation(
                hour=round(e["sim_time"] / 3600.0, 2),
                woken_because=str(d.get("woken_because") or "?"),
                did=str(d.get("did") or "nothing"),
                text=str(d.get("text") or ""),
                assets=d.get("assets") or None,
            ))
        return out

    def agent_state(self, agent_id: str) -> dict[str, Any]:
        """What happened to this agent, from the log alone.

        Deliberately not read from the checkpoint: a run that crashed still has
        a log, and an interrogation tool that only works on cleanly-finished
        runs is useless exactly when something interesting went wrong.
        """
        evs = self.by_agent.get(agent_id, [])
        if not evs:
            return {}
        notable = {
            "business_founded", "business_bankrupt", "business_closed", "hired",
            "fired", "quit_job", "job_started", "job_posted", "starved_to_death",
            "assets_wiped", "decision_cap_reached", "bankruptcy_warning",
        }
        return {
            "id": agent_id,
            "name": self._name(agent_id),
            "decisions": sum(1 for e in evs if e["type"] == "llm_reasoning"),
            "actions": sum(1 for e in evs if e["type"] == "action_call"),
            "refused": sum(
                1 for e in evs
                if e["type"] == "action_call" and not e["detail"].get("ok")
            ),
            "last_seen_hour": round(max(e["sim_time"] for e in evs) / 3600.0, 2),
            "milestones": [
                {
                    "hour": round(e["sim_time"] / 3600.0, 2),
                    "what": e["type"],
                    "detail": {
                        k: v for k, v in e["detail"].items() if k != "text"
                    },
                }
                for e in evs if e["type"] in notable
            ],
            "advice": self.advice(agent_id),
        }

    def advice(self, agent_id: str) -> list[dict[str, Any]]:
        """Every recommendation this agent was given, and whether it arrived.

        Given and delivered are reported separately because they are different
        facts and the gap between them is the first thing to check when advice
        looks ignored -- see `convoy/advice.py`.
        """
        evs = self.by_agent.get(agent_id, [])
        recs: dict[str, dict[str, Any]] = {}
        for e in evs:
            d = e.get("detail", {})
            rid = d.get("advice_id")
            if not rid:
                continue
            slot = recs.setdefault(rid, {
                "id": rid, "text": d.get("text") or d.get("advice") or "",
                "from_who": d.get("from_who"), "given_at_hour": d.get("given_at_hour"),
                "delivered": False, "first_seen_hour": None, "outcomes": [],
            })
            if e["type"] == "advice_given":
                slot["given_at_hour"] = round(e["sim_time"] / 3600.0, 2)
            elif e["type"] == "advice_delivered":
                slot["delivered"] = True
                slot["first_seen_hour"] = round(e["sim_time"] / 3600.0, 2)
            elif e["type"] == "advice_outcome":
                slot["text"] = slot["text"] or d.get("advice") or ""
                slot["outcomes"].append({
                    "hour": round(e["sim_time"] / 3600.0, 2),
                    "did": d.get("did"),
                    "said": d.get("text"),
                })
        return list(recs.values())


# ---------------------------------------------------------------------------
# RETRIEVAL
# ---------------------------------------------------------------------------

def _terms(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9_]+", question.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def _hours_mentioned(question: str) -> list[float]:
    """Explicit hours in the question: 'at hour 40', 'h40', 'between 30 and 45'."""
    out = [float(m) for m in re.findall(r"(?:hour|h)\s*(\d+(?:\.\d+)?)", question.lower())]
    return out


def _score(citation: Citation, terms: list[str], hours: list[float]) -> tuple[float, int]:
    """Relevance, and how many of the question's content words actually matched.

    The count is returned separately because it, not the score, is what decides
    whether a decision is about the question at all. See `retrieve`.
    """
    haystack = f"{citation.did} {citation.text} {citation.woken_because}".lower()
    matched = [t for t in terms if t in haystack]
    score = sum(2.0 if t in citation.did.lower() else 1.0 for t in matched)
    if hours:
        # Nearest named hour, decaying over a couple of hours. A question that
        # names an hour is asking about THAT moment, and a keyword match twenty
        # hours away is a different decision that happens to use the same word.
        nearest = min(abs(citation.hour - h) for h in hours)
        score += max(0.0, 4.0 - nearest * 2.0)
    return score, len(matched)


def retrieve(
    run: Run, agent_id: str, question: str, limit: int = MAX_CITATIONS
) -> list[Citation]:
    """The decisions most likely to contain the answer, best first.

    A MATCH THRESHOLD, NOT JUST A RANKING. Sorting by score and taking the top
    few will always return something, and "always returns something" is the
    confabulation problem moved out of the model and into the retriever. Asked
    "why did you buy a camel?" about an agent that never saw one, a bare ranking
    returned the hour it bought CHARCOAL -- because "buy" matched -- and the
    answer read as the agent confirming a purchase that never happened.

    So a decision must match a strict MAJORITY of the question's content words
    to count as being about it. Half is not enough: "buy camel" has two content
    words and the charcoal purchase matched one of them, which is exactly the
    case this threshold exists for. A named hour qualifies on its own -- an hour
    is an unambiguous request for a specific moment, and answering it with what
    the agent really did then is honest even when that is not what was asked.
    """
    decisions = run.decisions(agent_id)
    if not decisions:
        return []
    terms, hours = _terms(question), _hours_mentioned(question)
    if not terms and not hours:
        return decisions[-limit:]

    required = len(terms) // 2 + 1 if terms else 0        # a strict majority
    scored = []
    for c in decisions:
        score, matched = _score(c, terms, hours)
        near = hours and min(abs(c.hour - h) for h in hours) <= 1.0
        if matched >= required and score > 0 or near:
            scored.append((c, score))
    hits = [c for c, _s in sorted(scored, key=lambda p: -p[1])][:limit]
    return sorted(hits, key=lambda c: c.hour)


def needs_synthesis(question: str) -> bool:
    """Does answering this require weighing decisions against each other?

    Biased towards NO. A lookup answered from the record is free and cannot be
    wrong about what the agent said; a synthesis costs a call and can drift. So
    the question has to actually ask for a judgement to get one.
    """
    q = question.lower()
    return any(w in q for w in _SYNTHESIS_WORDS)


# ---------------------------------------------------------------------------
# ANSWERING
# ---------------------------------------------------------------------------

def _recall(citations: list[Citation], question: str) -> Answer:
    """Hand back what the agent said, framed but not rewritten."""
    if len(citations) == 1:
        c = citations[0]
        said = c.text if c.text and not c.text.startswith("(acted without") else ""
        body = (
            f"At hour {c.hour} I was woken because: {c.woken_because}. "
            f"I did: {c.did}."
        )
        body += f'\n\nIn my own words at the time: "{said}"' if said else (
            "\n\nI did not record a reason for that one -- the model acted "
            "without explaining itself on that turn."
        )
        if pos := c.position():
            body += f"\n\nWhat I held at the time: {pos}"
        return Answer(kind="recall", text=body, citations=citations)

    lines = [f"{len(citations)} decisions in my record bear on that:"]
    for c in citations:
        said = c.text.strip().replace("\n", " ")
        if said.startswith("(acted without"):
            said = "(no reason recorded)"
        lines.append(f"\n  h{c.hour} — did: {c.did}\n    \"{said[:300]}\"")
        if pos := c.position():
            lines.append(f"    held: {pos}")
    return Answer(kind="recall", text="\n".join(lines), citations=citations)


# An answer is two or three sentences. `LLMPolicy` defaults to reserving 4,096
# completion tokens, and OpenRouter charges that RESERVATION against the key's
# remaining credit rather than what the reply actually uses -- so a fat default
# returns 402 ("you requested up to 4096 tokens, but can only afford 1174")
# while a small honest one goes through on the same balance. `llm.py`'s own
# docstring records this biting a live run at 65,536; it bit the ask box at
# 4,096, and the fix is the same both times: reserve what the job needs.
#
# It also bounds the damage of a model that decides to write an essay, which is
# worth something in a classroom where thirty students are asking at once.
ANSWER_TOKENS = 700

# How many recent decisions to fall back on for a question about the future,
# which by definition matches no citation.
RECENT_FALLBACK = 6

def _fallback(
    citations: list[Citation], question: str, present: str | None, note: str = ""
) -> Answer:
    """The no-model answer: the agent's situation, then its own words.

    One helper rather than two call sites, because the two used to differ -- the
    no-policy path carried the live situation and the transport-failure path
    silently dropped it, so an answer got worse in a way nobody would think to
    test for.
    """
    out = _recall(citations, question)
    parts = [p for p in (note, f"Right now: {present}" if present else "", out.text) if p]
    out.text = "\n\n".join(parts)
    return out


SYNTHESIS_SYSTEM = """You are {name}, an agent living in Convoy, an Iron Age economic simulation. Someone is asking you about your own decisions. Talk to them like a person, not like a database.

You will be shown YOUR OWN recorded decisions -- the hour, what you did, and what you were thinking at the time. That record is your memory. It is the only thing you actually know.

How to answer:
- Speak in the first person, past tense, conversationally. Contractions are fine. Two or three sentences unless more is genuinely needed.
- Cite the hours you are drawing on, like (h40.2), so the person can check you.
- Some decisions carry a "you held" line: your cash, businesses, vehicles and job at that moment. Those numbers are real -- use them when you are asked what something cost you or what you could afford. Where there is no such line, you do not know what you were holding, and should say so rather than estimating.
- Explain your reasoning the way you would to someone looking over your shoulder -- what you were weighing, what you were worried about.

What you must never do:
- Never invent a motive, a number, an event or an hour that is not in the record. If you did not record why you did something, say "I didn't note why" rather than reconstructing a plausible reason. A confident guess is the worst possible answer here.
- If the record does not answer what was asked, say so plainly and say what it DOES show. That is a good answer, not a failure.
- Where what you were thinking does not match what you actually did, say so. That is the most interesting thing you can tell anyone.

You are allowed to have opinions about your own choices, including that one was a mistake -- as long as the opinion is about something in the record.

If you are shown a RIGHT NOW block, that is your live situation this second -- where you are, what you are in the middle of, what you are carrying, and how long until you next get to choose. When someone asks what you are going to do NEXT, answer from that: say what you are planning and why, and be honest that it is a plan rather than something that has happened. A plan can change; say so if someone gives you a reason to change it. Do not describe the present as though it were finished, and do not invent a future that your situation does not support."""


def answer(
    run: Run,
    agent_id: str,
    question: str,
    *,
    policy: Any = None,
    model: str = "openai/gpt-5.6-luna",
    force_synthesis: bool = False,
    history: list[Any] | None = None,
    present: str | None = None,
) -> Answer:
    """Answer a question about one agent, in that agent's own voice.

    THE MODEL ANSWERS BY DEFAULT. An earlier version gated it behind a keyword
    test and returned the raw record for anything that did not look like a
    judgement, which made "why did you buy charcoal?" come back as
    `At hour 12.0 I was woken because: reevaluation. I did: buy_item.` That is a
    printout, not an answer, and nobody in a classroom is served by it.

    What was worth keeping from that design is not recall-instead-of-a-model, it
    is GROUNDING: the model is shown the agent's retrieved decisions and told to
    use nothing else, and the same citations come back with the answer so a
    student can check it. Reasoning capture (PHASE4 §9) exists so that the
    agent's account of itself is recall rather than invention; letting a model
    narrate that record is fine, letting it replace the record is not.

    Recall is now the FALLBACK -- no policy, no key, or a transport failure. It
    is still a true answer, just an unsummarised one, and a classroom that loses
    its API key mid-session should get quotes rather than an error page.

    `history` is prior exchanges with this person (see `convoy/conversation.py`),
    so a follow-up question lands instead of being met from scratch.

    Cost: one call per question. Thirty students asking twenty questions is 600
    calls, which is why `serve.py --no-model` exists and returns the record.
    """
    citations = retrieve(run, agent_id, question)

    # A question about the FUTURE is answerable from the present alone -- "what
    # are you going to do next?" has no citation because it has not happened.
    # Without this the most natural thing anyone says to a live agent falls
    # through to "there is nothing in my record about that", which is true and
    # useless.
    if present and not citations:
        citations = run.decisions(agent_id)[-RECENT_FALLBACK:]

    # Even a factual lookup may name nothing the retriever can match ("how did
    # it go?"). If a model is available it should still get the recent record
    # and answer conversationally rather than the question falling on the floor.
    if not citations and (policy is not None or force_synthesis or needs_synthesis(question)):
        # "Was your overall strategy sound?" names nothing in particular and so
        # matches no keyword -- but its subject is the whole record, not none of
        # it. Falling through to `nothing` here made every judgement question
        # unanswerable while the transcript sat right there.
        citations = run.decisions(agent_id)[-MAX_CITATIONS:]

    if not citations and not present:
        return Answer(
            kind="nothing",
            text=(
                "There is nothing in my record about that. Either it never "
                "happened, or it happened on a turn where no reasoning was "
                "captured. I would rather say that than make something up."
            ),
        )

    if policy is None:
        return _fallback(citations, question, present)

    record = "\n".join(
        f"[h{c.hour}] woken: {c.woken_because} | did: {c.did} | said: {c.text}"
        + (f"\n           you held: {pos}" if (pos := c.position()) else "")
        for c in citations
    )
    turns = "\n".join(
        f"They asked: {e.question}\nYou answered: {e.answer}"
        for e in (history or ())
    )
    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM.format(name=run._name(agent_id))},
        {"role": "user", "content": (
            (f"EARLIER IN THIS CONVERSATION\n{turns}\n\n" if turns else "")
            + f"YOUR RECORDED DECISIONS\n{record}\n\n"
            + (f"RIGHT NOW\n{present}\n\n" if present else "")
            + f"THE HOUR NOW: {run.hours()}\n\nTHEY ASK: {question}"
        )},
    ]

    class _Stub:
        id, model_name = agent_id, model

    stub = _Stub()
    stub.model = model
    reply = policy._call(stub, messages, [])
    if not reply:
        # The present block belongs here TOO. A degraded answer that drops it
        # tells someone watching a live agent nothing about where it is
        # standing -- which is the half of the answer they can see on the map
        # and would immediately notice missing.
        return _fallback(
            citations, question, present,
            note="(the model could not be reached, so here is the record)",
        )

    text = (reply.get("content") or reply.get("reasoning") or "").strip()
    if not text:
        return _recall(citations, question)
    return Answer(kind="synthesis", text=text, citations=citations, model_called=True)
