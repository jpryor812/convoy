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

from . import observe as O
from . import schemas as S
from .config import load_env
from .events import EventLog
from .state import Agent, World

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# An agent may chain a few actions in one decision -- collect stock, then travel,
# then sell. Capped so a confused model cannot spend a whole budget in one tick.
MAX_ACTIONS_PER_DECISION = 4

REQUEST_TIMEOUT_S = 90.0
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0


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
    usage: dict[str, Usage] = field(default_factory=dict)
    _prefix: tuple[str, list[dict[str, Any]]] | None = None

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
        briefing, tools = self._prefix        # type: ignore[misc]
        obs = O.observe(world, self.log, agent, reason)

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

        acted = 0
        for _step in range(self.max_actions):
            reply = self._call(agent, messages, tools)
            if reply is None:
                return                                  # logged; agent idles

            calls = reply.get("tool_calls") or []
            messages.append(reply)

            if not calls:
                # The model chose to say something rather than act. That is a
                # legitimate decision -- an agent may be waiting on production.
                text = (reply.get("content") or "").strip()
                if text:
                    self.log.emit(
                        world.sim_time, "llm_reasoning", actor=agent.id,
                        text=text[:400],
                    )
                return

            for call in calls:
                name, args = _parse_tool_call(call)
                if name is None:
                    result = (False, "unparseable tool call")
                else:
                    result = S.dispatch(world, self.log, agent, name, args)
                acted += 1
                self._record_action(agent)
                # Feed the outcome back: an agent that tried to sell what it is
                # not carrying should learn why, not silently retry forever.
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": json.dumps({"ok": result[0], "detail": result[1]}),
                })

            if acted >= self.max_actions:
                return

    # -- transport ---------------------------------------------------------

    def _call(
        self, agent: Agent, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        payload = {
            "model": agent.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
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

            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == MAX_RETRIES - 1:
                    self._fail(agent, f"{type(exc).__name__}: {exc}")
                    return None
                time.sleep(BACKOFF_BASE_S * (2 ** attempt))

        return None

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
        self._slot(agent.model).errors += 1
        self.log.emit(0.0, "llm_error", actor=agent.id, model=agent.model, error=detail)

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
