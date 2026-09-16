"""The Claude client.

One place where money is spent, so one place where the budget is checked. Every
call goes through :meth:`ResearchClient.ask`, which refuses to start if the
month's cap would be breached and records what the call actually cost the moment
it returns.

Model notes that matter here (Sonnet 5):

* ``thinking: {"type": "adaptive"}`` is the only on-mode. ``budget_tokens`` is
  rejected with a 400; depth is controlled with ``output_config.effort``.
* The web search tool type is ``web_search_20260209``.
* Web search failures come back as HTTP 200 with an error object inside the
  result block, so they must be inspected rather than caught.
* Streaming is used because ``max_tokens`` is large enough to risk an HTTP
  timeout otherwise.

Answers are requested as JSON in the response text rather than through
structured output, because server-tool citations and ``output_config.format``
do not combine. The parser is deliberately tolerant, and there is exactly one
repair attempt before a pass is given up on.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..budget import BudgetGuard, Usage
from ..config import Settings
from ..runlog import Run

PROMPTS_DIR = Path(__file__).parent / "prompts"
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"

# Generous upper bound for the pre-flight budget check: real calls come in well
# under this, and over-estimating only makes the guard more conservative.
ESTIMATED_INPUT_TOKENS_PER_SEARCH = 12_000


class ResearchError(RuntimeError):
    """A research pass that could not produce usable JSON."""


@dataclass
class AskResult:
    payload: dict[str, Any]
    text: str
    usage: Usage
    cost_aud: float
    searches: int
    search_errors: list[str] = field(default_factory=list)
    repaired: bool = False


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise ResearchError(f"No prompt template named {name!r} at {path}")
    return path.read_text(encoding="utf-8")


def render(template: str, **values: Any) -> str:
    """Minimal ``{{name}}`` substitution — no template engine dependency."""
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", str(value))
    leftover = re.findall(r"\{\{(\w+)\}\}", out)
    if leftover:
        raise ResearchError(f"Prompt still has unfilled placeholders: {sorted(set(leftover))}")
    return out


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a response that may wrap it in prose or fences."""
    if not text or not text.strip():
        raise ResearchError("response was empty")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ResearchError(f"no JSON object found in {len(text)} characters of response")


def collect_text(message: Any) -> str:
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(parts)


def collect_search_errors(message: Any) -> tuple[int, list[str]]:
    """Count searches and surface any that failed.

    A successful ``web_search_tool_result`` carries a *list*; a failed one
    carries an error *object*. Branching on that is the documented way to tell
    them apart, since neither raises.
    """
    searches, errors = 0, []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        searches += 1
        content = getattr(block, "content", None)
        if isinstance(content, dict):
            errors.append(str(content.get("error_code", content)))
        elif hasattr(content, "error_code"):
            errors.append(str(content.error_code))
    return searches, errors


class ResearchClient:
    def __init__(self, settings: Settings, guard: BudgetGuard, run: Run,
                 client: Any = None):
        self.settings = settings
        self.guard = guard
        self.run = run
        self._client = client
        self.model = settings.research.model

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic  # imported lazily so offline commands need no SDK

            self._client = anthropic.Anthropic()
        return self._client

    # -- cost ---------------------------------------------------------------

    def estimate_aud(self, max_searches: int, max_tokens: int) -> float:
        pricing = self.settings.pricing_for(self.model)
        input_tokens = max_searches * ESTIMATED_INPUT_TOKENS_PER_SEARCH + 20_000
        usd = (
            input_tokens * pricing.input_per_mtok_usd / 1_000_000
            + max_tokens * pricing.output_per_mtok_usd / 1_000_000
            + max_searches * pricing.web_search_per_1k_usd / 1_000
        )
        return usd * self.settings.budget.usd_to_aud

    # -- the one entry point ------------------------------------------------

    def ask(self, *, system: str, user: str, purpose: str, max_searches: int = 12,
            effort: str = "high", max_tokens: int = 16_000) -> AskResult:
        """Run one research pass. Raises :class:`~..budget.BudgetExhausted` rather
        than spending past the cap, and :class:`ResearchError` on unusable output."""
        estimate = self.estimate_aud(max_searches, max_tokens)
        self.guard.check(estimated_aud=estimate)
        self.run.log("research_call", {"purpose": purpose, "model": self.model,
                                       "max_searches": max_searches, "effort": effort,
                                       "estimate_aud": round(estimate, 3)})

        message = self._send(system=system, user=user, max_tokens=max_tokens,
                             effort=effort, max_searches=max_searches)
        usage = Usage.from_response(message.usage)
        cost = self.guard.record(usage, purpose=purpose)

        searches, search_errors = collect_search_errors(message)
        for error in search_errors:
            self.run.log("web_search_error", {"purpose": purpose, "error": error},
                         level="warn")

        text = collect_text(message)
        repaired = False
        try:
            payload = extract_json(text)
        except ResearchError as first_error:
            self.run.log("json_repair", {"purpose": purpose, "reason": str(first_error)},
                         level="warn")
            payload, repair_usage, repair_cost = self._repair(text, system, purpose)
            usage, cost, repaired = usage + repair_usage, cost + repair_cost, True

        self.run.log("research_done", {
            "purpose": purpose, "searches": searches, "cost_aud": round(cost, 4),
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "repaired": repaired,
        })
        return AskResult(payload=payload, text=text, usage=usage, cost_aud=cost,
                         searches=searches, search_errors=search_errors,
                         repaired=repaired)

    def _send(self, *, system: str, user: str, max_tokens: int, effort: str,
              max_searches: int) -> Any:
        tools = [{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search",
                  "max_uses": max_searches}] if max_searches > 0 else []
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }
        if tools:
            kwargs["tools"] = tools
        with self.client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()

    def _repair(self, text: str, system: str, purpose: str) -> tuple[dict, Usage, float]:
        """One attempt to get valid JSON back, with no tools and no new research."""
        estimate = self.estimate_aud(0, 8_000)
        self.guard.check(estimated_aud=estimate)
        message = self._send(
            system="Return only a single valid JSON object. No prose, no code fences.",
            user=f"Convert the following into the JSON object it was meant to be. "
                 f"Invent nothing; drop anything you cannot represent.\n\n{text[:60_000]}",
            max_tokens=8_000, effort="low", max_searches=0,
        )
        usage = Usage.from_response(message.usage)
        cost = self.guard.record(usage, purpose=f"{purpose}_repair")
        try:
            return extract_json(collect_text(message)), usage, cost
        except ResearchError as exc:
            raise ResearchError(
                f"{purpose}: model did not return usable JSON, and the repair "
                f"attempt failed too ({exc})") from exc
