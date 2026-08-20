"""OpenRouter-backed policy: the same `decide()` seam the rule agents use.

THE CACHE CONTRACT

Priced out, the full 120-hour run costs ~$66 with prompt caching and ~$293
without, against a $94 budget. Caching is therefore not an optimisation, it is
the thing that keeps the run affordable -- and a cache that stops hitting fails
silently, showing up only on the invoice. So:

  * the cached prefix (static briefing + tool schemas) is built ONCE at startup
    and reused byte-identically for every agent and every call;
  * it always goes first, because caching matches on prefix;
  * nothing agent-specific or clock-specific may appear in it.

`test_observe.py` and `test_schemas.py` both assert this, and `usage` on every
response is recorded so a cache regression is visible in the run summary rather
than a month later.

FAILURE POSTURE

A 120-hour run cannot die because one HTTP call timed out at hour 63. Every
failure path here degrades to "this agent does nothing this tick" and logs why.
The simulation continues.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import actions as A
from . import data as D
from . import observe as O
from . import schemas as S
from .config import load_env
from .events import EventLog, Significance
from .state import REASONING_CHARS, Agent, Recommendation, World

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# An agent may chain a few actions in one decision -- collect stock, then travel,
# then sell. Capped so a confused model cannot spend a whole budget in one tick.
MAX_ACTIONS_PER_DECISION = 4

REQUEST_TIMEOUT_S = 90.0
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0

# A decision is a tool call and at most a sentence of reasoning, so the model
# never needs much room. Sending no limit at all is what bit the first live run:
# OpenRouter reserves the model's FULL completion window (65,536 tokens) against
# the key's remaining credit and returns 402 when the balance cannot cover it,
# which fails every call on a key that is not nearly empty.
MAX_COMPLETION_TOKENS = 4096

# New OpenRouter accounts are capped per model (10 rpm on Luna). One 429 costs
# three retries and a wasted decision, so the calls are paced instead.
REQUESTS_PER_MINUTE = 10.0


@dataclass
class Usage:
    """Token and cost accounting, aggregated per model."""

    calls: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    errors: int = 0
    actions: int = 0

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.prompt_tokens if self.prompt_tokens else 0.0


@dataclass
class LLMPolicy:
    """Drives agents with real models. Drop-in for `RuleBasedPolicy`."""

    log: EventLog
    api_key: str | None = None
    max_actions: int = MAX_ACTIONS_PER_DECISION
    dry_run: bool = False              # build prompts, make no network calls
    max_completion_tokens: int = MAX_COMPLETION_TOKENS
    requests_per_minute: float = REQUESTS_PER_MINUTE   # 0 disables pacing
    usage: dict[str, Usage] = field(default_factory=dict)
    _prefix: tuple[str, list[dict[str, Any]]] | None = None
    _last_call_at: float = 0.0
    # The sim clock, stashed for `_fail`. See its docstring.
    _sim_time: float = 0.0

    def __post_init__(self) -> None:
        if self.api_key is None:
            load_env()          # a .env at the repo root, if there is one
            self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key and not self.dry_run:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Export it, pass api_key=, or use "
                "dry_run=True to build prompts without calling the API."
            )
        # Built once. Rebuilding per call would still be correct but would risk
        # byte drift, which is exactly what breaks caching.
        self._prefix = (O.static_briefing(), S.tool_schemas())

    # -- the Policy protocol ----------------------------------------------

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        self._sim_time = world.sim_time
        briefing, tools = self._prefix        # type: ignore[misc]
        obs = O.observe(world, self.log, agent, reason, record_delivery=not self.dry_run)

        # Which recommendations were in the prompt this agent is about to answer.
        # Read AFTER `observe`, so it is the same list `observe` just marked as
        # delivered rather than a second, hopeful guess at what it sent.
        advised = agent.live_advice(world.sim_hour) if not self.dry_run else []

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": briefing},
            {"role": "user", "content": O.render(obs)},
        ]

        if self.dry_run:
            self.log.emit(
                world.sim_time, "llm_dry_run", actor=agent.id,
                prompt_chars=sum(len(str(m.get("content") or "")) for m in messages),
            )
            return

        # One decision produces ONE record, not one per step. A four-step
        # decision typically reasons once and then executes: the model explains
        # itself on step 1 and emits bare tool calls after. Recording per step
        # made three quarters of a live smoke run read "acted without saying
        # why" when the reason had in fact been given -- one step earlier.
        acted = 0
        texts: list[str] = []
        did: list[str] = []
        try:
            for _step in range(self.max_actions):
                reply = self._call(agent, messages, tools)
                if reply is None:
                    return                              # logged; agent idles

                calls = reply.get("tool_calls") or []
                messages.append(reply)
                text = _reasoning_text(reply)
                if text:
                    texts.append(text)
                stop = False

                if not calls:
                    # The model chose to say something rather than act. That is
                    # a legitimate decision -- it may be waiting on production.
                    return

                for call in calls:
                    name, args = _parse_tool_call(call)
                    if name is None:
                        result = (False, "unparseable tool call")
                    else:
                        result = S.dispatch(world, self.log, agent, name, args)
                    acted += 1
                    if name in A.TERMINAL_ACTIONS:
                        stop = True
                    self._record_action(agent)
                    did.append(
                        f"{name or '<unparseable>'}" + ("" if result[0] else " (refused)")
                    )
                    # Every call, refusals included. Only exceptions emit
                    # action_error, so without this an engine refusal ("you are
                    # already employed") leaves no trace at all -- and what
                    # agents TRY is the whole point of the harness run.
                    self.log.emit(
                        world.sim_time, "action_call", actor=agent.id,
                        action=name or "<unparseable>", ok=result[0],
                        detail_text=str(result[1])[:200],
                    )
                    # Feed the outcome back: an agent that tried to sell what it
                    # is not carrying should learn why, not silently retry.
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps({"ok": result[0], "detail": result[1]}),
                    })

                if stop:
                    return
                if acted >= self.max_actions:
                    return
        finally:
            # In a `finally` so that every exit -- a clean stop, the action cap,
            # a transport failure mid-decision, or an exception out of dispatch
            # -- still records what the agent said and did up to that point. A
            # decision that half-happened is exactly the kind a student asking
            # "why did you do that?" most needs an answer for.
            self._remember(world, agent, reason, "\n".join(texts), did, advised=advised)

    # -- reasoning ---------------------------------------------------------

    def _remember(
        self,
        world: World,
        agent: Agent,
        reason: str,
        text: str,
        did: list[str],
        *,
        advised: list[Recommendation] | None = None,
    ) -> None:
        """Store the model's own account of this decision, on the agent and in the log.

        A decision is recorded even when the model said nothing, as long as it
        acted: an unbroken record of what an agent did is what makes the gaps in
        why it did it legible. A decision with neither words nor actions did not
        happen -- a transport failure on the first call -- and is skipped.

        The agent keeps a bounded working set for its own recall; the log keeps
        every one, which is what a transcript is built from.
        """
        if not text and not did:
            return
        agent.remember_reasoning(world.sim_hour, reason, text, did)
        self.log.emit(
            world.sim_time, "llm_reasoning", actor=agent.id,
            location=agent.location,
            woken_because=reason,
            text=text[:REASONING_CHARS] or "(acted without saying why)",
            did=", ".join(did) or "nothing",
            # What the agent owned when it decided. Taken AFTER the actions, so
            # it is the position the decision produced rather than the one it
            # started from -- which is the number a reader wants when asking
            # what a choice cost. The prior row holds the state before.
            #
            # On the event only, NOT on `Agent.reasoning`: the ring buffer is
            # what an agent carries in its own prompt, and it already knows its
            # current balances from the observation. Putting balances there
            # would pay for 40 copies of a fact the agent can see, and is the
            # same separate-budgets argument as PHASE4 §9.
            assets=agent.assets(world),
        )
        # What the agent did while holding this advice, paired with the advice
        # itself. Deliberately NOT a verdict: nothing here decides whether the
        # advice was "followed". A model asked to grade its own obedience will
        # say yes, and a keyword match on the action names would call
        # `sell_to_business` compliance with "sell the ore" even when it sold
        # something else entirely. This records what was said and what was done,
        # which is what lets a student -- or Step 3 -- judge it from evidence.
        for rec in advised or ():
            self.log.emit(
                world.sim_time, "advice_outcome", actor=agent.id,
                location=agent.location,
                significance=Significance.MEDIUM,
                advice_id=rec.id, from_who=rec.from_who, advice=rec.text,
                hours_since_given=round(world.sim_hour - rec.given_at_hour, 2),
                times_seen=rec.times_seen,
                did=", ".join(did) or "nothing",
                text=text[:REASONING_CHARS] or "(acted without saying why)",
            )

    # -- transport ---------------------------------------------------------

    def _call(
        self, agent: Agent, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        payload = {
            "model": agent.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": self.max_completion_tokens,
        }
        effort = D.EFFORT_BY_MODEL.get(agent.model)
        if effort:
            payload["reasoning"] = {"effort": effort}
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "Convoy",
            },
            method="POST",
        )

        for attempt in range(MAX_RETRIES):
            self._pace()
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self._record_usage(agent.model, data.get("usage") or {})
                choices = data.get("choices") or []
                if not choices:
                    self._fail(agent, "no choices in response")
                    return None
                return choices[0].get("message") or None

            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                # 4xx other than rate-limiting will not fix itself on retry.
                if exc.code != 429 and 400 <= exc.code < 500:
                    self._fail(agent, f"HTTP {exc.code}: {detail}")
                    return None
                if attempt == MAX_RETRIES - 1:
                    self._fail(agent, f"HTTP {exc.code} after {MAX_RETRIES} tries: {detail}")
                    return None
                time.sleep(BACKOFF_BASE_S * (2 ** attempt))

            # OSError, not just URLError: a connection reset mid-body happens
            # AFTER urlopen() returns, so it arrives during resp.read() as a bare
            # ConnectionResetError and is not wrapped. That killed a live run at
            # 1.5 simulated hours. URLError and TimeoutError are both OSError
            # subclasses, so this covers the whole family.
            except (OSError, json.JSONDecodeError) as exc:
                if attempt == MAX_RETRIES - 1:
                    self._fail(agent, f"{type(exc).__name__}: {exc}")
                    return None
                time.sleep(BACKOFF_BASE_S * (2 ** attempt))

        return None

    def _pace(self) -> None:
        """Hold the request rate under the account's per-model limit."""
        if not self.requests_per_minute:
            return
        gap = 60.0 / self.requests_per_minute
        wait = self._last_call_at + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call_at = time.monotonic()

    # -- accounting --------------------------------------------------------

    def _slot(self, model: str) -> Usage:
        return self.usage.setdefault(model, Usage())

    def _record_usage(self, model: str, usage: dict[str, Any]) -> None:
        slot = self._slot(model)
        slot.calls += 1
        slot.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        slot.completion_tokens += int(usage.get("completion_tokens") or 0)
        slot.cost += float(usage.get("cost") or 0.0)
        details = usage.get("prompt_tokens_details") or {}
        slot.cached_tokens += int(details.get("cached_tokens") or 0)

    def _record_action(self, agent: Agent) -> None:
        self._slot(agent.model).actions += 1

    def _fail(self, agent: Agent, detail: str) -> None:
        """Record a transport failure AT THE HOUR IT HAPPENED.

        This passed a literal 0.0 as the sim time until 2026-08-19, so every
        API failure in every run is stamped hour 0. On the 84-hour run of
        2026-08-18 that hid the only thing that mattered about 2,859 errors:
        that there were none for the first 46 hours and then nothing but. Read
        off the log they looked like a bad start rather than a cliff, and the
        cliff is the diagnosis.

        The clock is on the World, which `_fail` had no reference to -- so it is
        stashed by `decide` rather than threaded through every call site.
        """
        self._slot(agent.model).errors += 1
        self.log.emit(
            self._sim_time, "llm_error", actor=agent.id, model=agent.model,
            error=detail,
        )

    def summary(self) -> str:
        lines = [
            f"{'model':<34}{'calls':>7}{'cache':>8}{'actions':>9}{'errors':>8}{'cost':>10}"
        ]
        total = 0.0
        for model, u in sorted(self.usage.items()):
            total += u.cost
            lines.append(
                f"{model:<34}{u.calls:>7}{u.cache_hit_rate:>7.0%}{u.actions:>9}"
                f"{u.errors:>8}{'$' + format(u.cost, '.4f'):>10}"
            )
        lines.append(f"{'TOTAL':<34}{'':>7}{'':>8}{'':>9}{'':>8}{'$' + format(total, '.4f'):>10}")
        return "\n".join(lines)


def _reasoning_text(reply: dict[str, Any]) -> str:
    """The model's justification for this step, from wherever it put it.

    Until 2026-08-17 this was read only from `content`, and only on replies with
    NO tool calls -- so reasoning was captured precisely on the turns where the
    agent decided not to act. It fired TWICE in 6,916 calls, which is why an
    agent asked "why did you do that?" could only confabulate.

    Two places to look. Most of the roster are reasoning models, which routinely
    return an empty `content` alongside a tool call and put their thinking in
    `reasoning` instead; taking only `content` would keep losing exactly the
    turns where the agent actually did something.
    """
    for key in ("content", "reasoning"):
        value = reply.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_tool_call(call: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Pull (name, arguments) out of a tool call.

    Arguments arrive as a JSON *string*, and models do occasionally emit one that
    does not parse. That is a bad call, not a bad run -- report it and continue.
    """
    fn = call.get("function") or {}
    name = fn.get("name")
    if not name:
        return None, {}
    raw = fn.get("arguments") or "{}"
    if isinstance(raw, dict):
        return name, raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, {}
    return (name, parsed) if isinstance(parsed, dict) else (None, {})
