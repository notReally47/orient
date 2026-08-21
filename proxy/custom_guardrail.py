"""Guardrails written here rather than bought, so they show up in the dashboard beside the rest.

LiteLLM loads a class named in the guardrail config as `guardrail: custom_guardrail.<ClassName>`
from a file mounted into the proxy image. Each one implements `apply_guardrail`, which is handed
the parts of a call a guardrail can act on: return them to let the call through, raise to block it.

A guardrail sees one call at a time and holds no memory of a conversation, so anything counted
across a run has to key its own state on something each call carries. Every call orient makes
carries `litellm_session_id`, and one run is one session, which is what makes that possible.
"""

import json
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, Final, Literal

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.utils import GenericGuardrailAPIInputs

if TYPE_CHECKING:
    from litellm.litellm_core_utils.litellm_logging import Logging as LiteLLMLoggingObj

DEFAULT_BUDGET: Final = 3
BLOCKED: Final = 422


class Rule:
    """One entry from the guardrail's `rules` list: which tools it covers, and on what terms.

    `tool_name` is a regular expression matched against the whole name, so a set of tools shares
    one entry. `budget` caps how often each tool it covers may be called in a run, counted per
    tool rather than pooled across the set, so one busy tool cannot starve its neighbours.
    `uncounted` exempts the set from counting altogether, which is what a tool that ends a run
    needs. `allowed_param_patterns` maps an argument name to a pattern its value must match; an
    argument the call does not pass is not checked.
    """

    def __init__(
        self,
        tool_name: str,
        id: str = "",  # noqa: A002  # the config calls this field `id`
        budget: int | None = None,
        uncounted: bool = False,
        allowed_param_patterns: dict[str, str] | None = None,
    ) -> None:
        self.id: Final = id or tool_name
        self.tool_name: Final = re.compile(tool_name)
        self.budget: Final = budget
        self.uncounted: Final = uncounted
        self.patterns: Final = {param: re.compile(pattern) for param, pattern in (allowed_param_patterns or {}).items()}

    def covers(self, tool: str) -> bool:
        return self.tool_name.fullmatch(tool) is not None

    def rejected(self, arguments: dict[str, object]) -> tuple[str, object, str] | None:
        """The first argument that fails its pattern, as (name, value, pattern), or nothing."""
        for param, pattern in self.patterns.items():
            if param in arguments and not pattern.fullmatch(str(arguments[param])):
                return (param, arguments[param], pattern.pattern)
        return None


class ToolBudget(CustomGuardrail):
    """Caps how often each tool may be called within a session, and what it may be called with.

    A model that keeps searching spends a daily request allowance re-asking a question it has
    already had answered, and one that asks for four hundred days of prices when thirty would do
    pays for the difference on every turn that carries the result. Neither is something a policy
    matched against a single call can see, which is why the count lives here.

    Rules are tried in order and the first whose pattern covers the tool decides its terms. A tool
    no rule covers is allowed and counted against `default_budget`, because every tool the server
    registers is one the model is meant to be able to reach.

    State lives in this process, keyed by session, so it holds for one proxy instance. That is the
    deployment this runs in; a horizontally scaled proxy would need a shared counter.
    """

    def __init__(
        self,
        default_budget: int = DEFAULT_BUDGET,
        # Spelled `tool_rules` rather than `rules`, which LiteLLM reserves for the schema of
        # its own tool permission guardrail and would validate this list against.
        tool_rules: list[dict[str, Any]] | None = None,
        **kwargs: Any,  # the base class takes arbitrary guardrail params
    ) -> None:
        self.default_budget: Final = int(default_budget)
        self.rules: Final = tuple(Rule(**rule) for rule in tool_rules or ())
        self._spent: Final[dict[str, Counter[str]]] = {}
        super().__init__(**kwargs)

    def rule_for(self, tool: str) -> Rule | None:
        return next((rule for rule in self.rules if rule.covers(tool)), None)

    async def apply_guardrail(
        self,
        inputs: GenericGuardrailAPIInputs,
        request_data: dict,  # the proxy's own request dict, carrying the session and the caller
        input_type: Literal["request", "response"],
        logging_obj: "LiteLLMLoggingObj | None" = None,
    ) -> GenericGuardrailAPIInputs:
        del logging_obj
        if input_type != "response":
            return inputs

        session: Final = _session(request_data)
        spent: Final = self._spent.setdefault(session, Counter()) if session else Counter()

        for tool, arguments in _requested(inputs):
            rule = self.rule_for(tool)
            self._check_arguments(tool, arguments, rule)
            if session:
                self._check_budget(tool, spent, rule)
        return inputs

    def _check_arguments(self, tool: str, arguments: dict[str, object], rule: Rule | None) -> None:
        refused: Final = rule.rejected(arguments) if rule is not None else None
        if refused is None:
            return
        param, value, pattern = refused
        raise HTTPException(
            status_code=BLOCKED,
            detail={
                "error": "tool argument not permitted",
                "tool": tool,
                "parameter": param,
                "message": (
                    f"{tool} was called with {param}={value!r}, which this proxy does not allow. "
                    f"Values for {param} must match {pattern}. Call it again within that range."
                ),
            },
        )

    def _check_budget(self, tool: str, spent: Counter[str], rule: Rule | None) -> None:
        if rule is not None and rule.uncounted:
            return
        budget: Final = self.default_budget if rule is None or rule.budget is None else rule.budget
        spent[tool] += 1
        if spent[tool] <= budget:
            return
        raise HTTPException(
            status_code=BLOCKED,
            detail={
                "error": "tool budget exhausted",
                "tool": tool,
                "budget": budget,
                "message": (
                    f"{tool} has already been called {budget} times in this run, which is its "
                    "limit. Work with what it returned, or use a different tool."
                ),
            },
        )


def _session(request_data: dict) -> str:  # the proxy's request dict
    """The run this call belongs to, from wherever the proxy recorded it.

    A chat completion names it in the body. Everything else names it in a header, which the proxy
    copies into the request metadata rather than the body, so both places are read.
    """
    named: Final = request_data.get("litellm_session_id")
    if isinstance(named, str) and named:
        return named
    for key in ("metadata", "litellm_metadata"):
        holder = request_data.get(key)
        if isinstance(holder, dict):
            carried = holder.get("session_id")
            if isinstance(carried, str) and carried:
                return carried
    return ""


def _function(call: object) -> tuple[str, str]:
    """A call's name and its raw arguments, whether it arrived as a mapping or a parsed object."""
    if isinstance(call, dict):
        function = call.get("function")
        function = function if isinstance(function, dict) else {}
        return str(function.get("name") or ""), str(function.get("arguments") or "")
    function = getattr(call, "function", None)
    return str(getattr(function, "name", "") or ""), str(getattr(function, "arguments", "") or "")


def _arguments(raw: str) -> dict[str, object]:
    """Arguments a model wrote, so anything unreadable is checked as though nothing was passed."""
    try:
        parsed: Final = json.loads(raw or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _requested(inputs: GenericGuardrailAPIInputs) -> tuple[tuple[str, dict[str, object]], ...]:
    """The tools the model just asked for, which the proxy extracts from the response for us."""
    calls: Final = inputs.get("tool_calls") or ()
    named: Final = (_function(call) for call in calls)
    return tuple((name, _arguments(raw)) for name, raw in named if name)
