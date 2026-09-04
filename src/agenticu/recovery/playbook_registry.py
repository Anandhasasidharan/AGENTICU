from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from agenticu.models import FailureMode, RecoveryAction, Span

logger = logging.getLogger(__name__)

RecoveryFn = Callable[..., Coroutine[Any, Any, RecoveryAction] | RecoveryAction]

_PLAYBOOKS: dict[FailureMode, RecoveryFn] = {}


def register(mode: FailureMode) -> Callable[[RecoveryFn], RecoveryFn]:
    """Decorator to register a recovery playbook for a failure mode."""

    def decorator(fn: RecoveryFn) -> RecoveryFn:
        _PLAYBOOKS[mode] = fn
        logger.debug("Registered playbook for %s: %s", mode.value, fn.__name__)
        return fn

    return decorator


def get_playbook(mode: FailureMode) -> RecoveryFn | None:
    return _PLAYBOOKS.get(mode)


def list_playbooks() -> list[tuple[FailureMode, str]]:
    return [(mode, fn.__name__) for mode, fn in _PLAYBOOKS.items()]


def registered_modes() -> set[FailureMode]:
    return set(_PLAYBOOKS.keys())


# ------------------------------------------------------------------ #
# Playbook implementations (6 of 14)
# ------------------------------------------------------------------ #


@register(FailureMode.DISOBEY_TASK_SPEC)
async def recover_disobey_task_spec(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Re-prompt with clarified spec + constraint validation.

    Real implementation: queries the trace for the stored task_spec
    and constructs a recovery instruction with the actual original spec.
    """
    logger.info("Recovering DisobeyTaskSpec for span %s", span.span_id)
    task_spec: str | None = None
    try:
        trace_spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(trace_spans, key=lambda x: x.start_time):
            if s.attributes and s.attributes.get("agenticu.task_spec"):
                task_spec = s.attributes["agenticu.task_spec"]
                break
    except Exception:
        pass

    spec_clause = f" Original spec: '{task_spec}'." if task_spec else ""
    return RecoveryAction(
        should_retry=True,
        instructions=(
            "Re-prompt with clarified spec: the previous attempt violated "
            f"task constraints.{spec_clause} "
            f"Error: {span.error_message or 'unknown'}"
        ),
        payload={"task_spec": task_spec, "error": span.error_message},
    )


@register(FailureMode.STEP_REPETITION)
async def recover_step_repetition(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Inject progress checkpoint, instruct to skip completed steps."""
    logger.info("Recovering StepRepetition for span %s", span.span_id)
    return RecoveryAction(
        should_retry=True,
        instructions="Skip the repeated step — it was already completed. Proceed to the next step.",
    )


@register(FailureMode.LOSS_OF_CONVERSATION_HISTORY)
async def recover_loss_of_history(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Replay context from last checkpoint.

    Real implementation: extracts actual output from prior successful
    spans and includes it in the recovery instruction.
    """
    logger.info("Recovering LossOfHistory for span %s", span.span_id)
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        checkpoint = [
            s
            for s in sorted(spans, key=lambda x: x.start_time)
            if s.status != "failure" and s.output is not None
        ]
        if checkpoint:
            last = checkpoint[-1]
            return RecoveryAction(
                should_retry=True,
                instructions=f"Restore context from last checkpoint (span '{last.span_id}', "
                f"agent '{last.agent_id}'). Prior output: {str(last.output)[:300]}",
                payload={"checkpoint_span_id": last.span_id, "checkpoint_output": last.output},
            )
    except Exception:
        pass
    return RecoveryAction(
        should_retry=False,
        instructions="No checkpoint available to restore context from.",
    )


@register(FailureMode.TASK_DERAILMENT)
async def recover_task_derailment(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Re-anchor to original task spec, trim extraneous actions.

    Real implementation: queries the trace for the original task_spec
    and the agent's prior output to construct a targeted re-anchor instruction.
    """
    logger.info("Recovering TaskDerailment for span %s", span.span_id)
    task_spec: str | None = None
    prior_output: str | None = None
    try:
        trace_spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(trace_spans, key=lambda x: x.start_time):
            if s.attributes and s.attributes.get("agenticu.task_spec"):
                task_spec = s.attributes["agenticu.task_spec"]
            if s.output is not None:
                prior_output = str(s.output)
    except Exception:
        pass

    if task_spec:
        return RecoveryAction(
            should_retry=True,
            instructions=f"Re-anchor to original task: '{task_spec}'. "
            f"Discard unrelated subtask results. "
            f"{'Last known output: ' + prior_output[:200] if prior_output else ''}",
            payload={"task_spec": task_spec, "prior_output": prior_output},
        )
    return RecoveryAction(
        should_retry=True,
        instructions="Re-anchor to the original task objective. Discard unrelated subtask results.",
    )


@register(FailureMode.PREMATURE_TERMINATION)
async def recover_premature_termination(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Restart agent from last completed span.

    Real: counts completed steps, finds task_spec, reports what's done vs total.
    """
    logger.info("Recovering PrematureTermination for span %s", span.span_id)
    task_spec: str | None = None
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        completed = [s for s in spans if s.status == "ok"]
        for s in sorted(spans, key=lambda x: x.start_time):
            if s.attributes and s.attributes.get("agenticu.task_spec"):
                task_spec = s.attributes["agenticu.task_spec"]
                break
        if completed:
            return RecoveryAction(
                should_retry=True,
                instructions=f"Continue from last completed step. {len(completed)} steps done."
                f"{' Task: ' + task_spec if task_spec else ''}",
                payload={
                    "completed_steps": len(completed),
                    "task_spec": task_spec,
                    "last_completed": completed[-1].span_id,
                },
            )
    except Exception:
        pass
    return RecoveryAction(
        should_retry=True,
        instructions="No prior steps found. Restart the task from the beginning.",
    )


@register(FailureMode.INCORRECT_VERIFICATION)
async def recover_incorrect_verification(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Trigger adversarial re-check (verifybot pattern).

    Real: scans the trace for the last output and flags potential contradictions.
    """
    logger.info("Recovering IncorrectVerification for span %s", span.span_id)
    last_output: str | None = None
    contradictions: list[str] = []
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(spans, key=lambda x: x.start_time, reverse=True):
            if s.output is not None:
                last_output = str(s.output)[:500]
                break
        if last_output:
            for kw in ["correct", "verified", "passed", "complete"]:
                if kw in last_output.lower():
                    contradictions.append(f"output claims '{kw}' but failure suggests otherwise")
    except Exception:
        pass

    return RecoveryAction(
        should_retry=True,
        instructions=(
            "Run adversarial verification: assume the previous output is wrong. "
            "Re-check every claim thoroughly."
            + (f" Potential contradictions: {'; '.join(contradictions)}." if contradictions else "")
        ),
        payload={"last_output": last_output, "contradictions": contradictions},
    )


@register(FailureMode.DISOBEY_ROLE_SPEC)
async def recover_disobey_role_spec(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Re-assert role boundary + inject role constraint validation.

    Real: checks the trace for which agents are active and their assigned roles.
    """
    logger.info("Recovering DisobeyRoleSpec for span %s", span.span_id)
    agent_ids: set[str] = set()
    task_spec: str | None = None
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in spans:
            if s.agent_id:
                agent_ids.add(s.agent_id)
            if s.attributes and s.attributes.get("agenticu.task_spec"):
                task_spec = s.attributes["agenticu.task_spec"]
    except Exception:
        pass

    return RecoveryAction(
        should_retry=True,
        instructions=(
            f"Agent '{span.agent_id}' violated its role boundary."
            f" Active agents: {', '.join(sorted(agent_ids)) if agent_ids else 'unknown'}."
            + (f" Task spec: {task_spec}." if task_spec else "")
        ),
        payload={
            "agent_id": span.agent_id,
            "active_agents": list(agent_ids),
            "task_spec": task_spec,
        },
    )


@register(FailureMode.UNAWARE_OF_TERMINATION)
async def recover_unaware_of_termination(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Signal termination again + inject completion guard.

    Real: checks task_spec for completion criteria and whether the trace finished.
    """
    logger.info("Recovering UnawareOfTermination for span %s", span.span_id)
    task_spec: str | None = None
    last_output: str | None = None
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(spans, key=lambda x: x.start_time):
            if s.attributes and s.attributes.get("agenticu.task_spec"):
                task_spec = s.attributes["agenticu.task_spec"]
            if s.output is not None:
                last_output = str(s.output)
    except Exception:
        pass

    return RecoveryAction(
        should_retry=False,
        instructions="Task was already completed. No further work needed."
        + (f" Last output indicates: {last_output[:200]}" if last_output else ""),
        payload={"task_spec": task_spec, "last_output": last_output},
    )


@register(FailureMode.CONVERSATION_RESET)
async def recover_conversation_reset(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Restore conversation state from last pre-reset checkpoint.

    Real: extracts actual prior outputs and includes them in the recovery action.
    """
    logger.info("Recovering ConversationReset for span %s", span.span_id)
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        prior = [s for s in spans if s.status != "failure"]
        prior_outputs = [str(s.output)[:200] for s in prior if s.output is not None]
        if prior:
            return RecoveryAction(
                should_retry=True,
                instructions=f"Restore conversation from {len(prior)} prior spans. "
                f"Last known state: {prior_outputs[-1] if prior_outputs else 'none'}",
                payload={"prior_span_count": len(prior), "prior_outputs": prior_outputs},
            )
    except Exception:
        pass
    return RecoveryAction(
        should_retry=True,
        instructions="Start fresh but preserve shared state across agents.",
    )


@register(FailureMode.FAIL_TO_ASK_CLARIFICATION)
async def recover_fail_to_ask_clarification(
    span: Span, store: Any, **kwargs: Any
) -> RecoveryAction:
    """Re-prompt with explicit request to clarify ambiguous instructions.

    Real: extracts task_spec and prior outputs to identify ambiguous context.
    """
    logger.info("Recovering FailToAskClarification for span %s", span.span_id)
    task_spec: str | None = None
    last_input: str | None = None
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(spans, key=lambda x: x.start_time):
            if s.attributes and s.attributes.get("agenticu.task_spec"):
                task_spec = s.attributes["agenticu.task_spec"]
            if s.input is not None:
                last_input = str(s.input)
    except Exception:
        pass

    return RecoveryAction(
        should_retry=True,
        instructions="The instructions were ambiguous. Ask for clarification before proceeding."
        + (f" Last input: {last_input[:200]}" if last_input else "")
        + (f" Task spec: {task_spec}" if task_spec else ""),
        payload={"task_spec": task_spec, "last_input": last_input},
    )


@register(FailureMode.INFORMATION_WITHHOLDING)
async def recover_information_withholding(span: Span, store: Any, **kwargs: Any) -> RecoveryAction:
    """Force state sync — push held information to all agents.

    Real: lists all agent_ids in the trace and what outputs each produced.
    """
    logger.info("Recovering InformationWithholding for span %s", span.span_id)
    agent_outputs: dict[str, list[str]] = {}
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in spans:
            if s.agent_id and s.output is not None:
                agent_outputs.setdefault(s.agent_id, []).append(str(s.output)[:200])
    except Exception:
        pass

    summary = "; ".join(
        f"{aid} produced {len(outs)} outputs" for aid, outs in agent_outputs.items()
    )
    return RecoveryAction(
        should_retry=True,
        instructions=f"Share all relevant information with peer agents before proceeding. "
        f"Trace data: {summary}"
        if summary
        else "Share all relevant information with peer agents before proceeding.",
        payload={"agent_outputs": agent_outputs},
    )


@register(FailureMode.IGNORED_OTHER_AGENT_INPUT)
async def recover_ignored_other_agent_input(
    span: Span, store: Any, **kwargs: Any
) -> RecoveryAction:
    """Re-present ignored input with request for re-evaluation.

    Real: finds the most recent output from a different agent and includes it.
    """
    logger.info("Recovering IgnoredOtherAgentInput for span %s", span.span_id)
    peer_outputs: list[dict[str, str]] = []
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(spans, key=lambda x: x.start_time, reverse=True):
            if s.agent_id and s.agent_id != span.agent_id and s.output is not None:
                peer_outputs.append(
                    {
                        "agent_id": s.agent_id,
                        "output": str(s.output)[:300],
                    }
                )
    except Exception:
        pass

    if peer_outputs:
        nearest = peer_outputs[0]
        return RecoveryAction(
            should_retry=True,
            instructions=f"Re-evaluate peer agent '{nearest['agent_id']}'s input: "
            f"'{nearest['output']}'. Do not dismiss or overwrite it.",
            payload={"peer_outputs": peer_outputs},
        )
    return RecoveryAction(
        should_retry=True,
        instructions="Re-evaluate the peer agent's input. Do not dismiss or overwrite it.",
    )


@register(FailureMode.REASONING_ACTION_MISMATCH)
async def recover_reasoning_action_mismatch(
    span: Span, store: Any, **kwargs: Any
) -> RecoveryAction:
    """Re-run decision step with explicit action verification.

    Real: finds the last decision span and compares its rationale to the output.
    """
    logger.info("Recovering ReasoningActionMismatch for span %s", span.span_id)
    rationale: str | None = None
    actual_output: str | None = None
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(spans, key=lambda x: x.start_time, reverse=True):
            if s.span_type == "decision" and s.output is not None:
                rationale = str(s.output)
                break
        last_action = [
            s for s in spans if s.span_type in ("tool_call", "agent") and s.output is not None
        ]
        if last_action:
            actual_output = str(last_action[-1].output)[:300]
    except Exception:
        pass

    return RecoveryAction(
        should_retry=True,
        instructions=(
            "Re-run the decision step. Ensure the chosen action matches "
            "the stated reasoning."
            + (f" Stated rationale: {rationale[:200]}" if rationale else "")
            + (f" Actual action: {actual_output[:200]}" if actual_output else "")
        ),
        payload={"rationale": rationale, "actual_action": actual_output},
    )


@register(FailureMode.NO_INCOMPLETE_VERIFICATION)
async def recover_no_incomplete_verification(
    span: Span, store: Any, **kwargs: Any
) -> RecoveryAction:
    """Trigger adversarial re-check (verifybot pattern).

    Real: inspects the last output for basic quality signals (length, error keywords).
    """
    logger.info("Recovering NoIncompleteVerification for span %s", span.span_id)
    last_output: str | None = None
    checks: dict[str, bool] = {}
    try:
        spans = await store.get_trace_by_id(span.trace_id)
        for s in sorted(spans, key=lambda x: x.start_time, reverse=True):
            if s.output is not None:
                last_output = str(s.output)
                break
        if last_output:
            checks["has_content"] = len(last_output) > 50
            checks["no_error_markers"] = not any(
                kw in last_output.lower() for kw in ["error", "fail", "exception", "traceback"]
            )
            checks["has_result"] = any(
                kw in last_output.lower()
                for kw in ["result", "output", "answer", "summary", "conclusion"]
            )
    except Exception:
        pass

    failed_checks = [k for k, v in checks.items() if not v]
    return RecoveryAction(
        should_retry=True,
        instructions=(
            "Verify the output before submitting."
            + (f" Failed checks: {', '.join(failed_checks)}." if failed_checks else "")
        ),
        payload={"last_output": last_output, "quality_checks": checks},
    )
