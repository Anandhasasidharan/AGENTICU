from __future__ import annotations

import re
from typing import Any

from agenticu.models import FailureCategory, FailureMode

FAILURE_MODE_DEFINITIONS: dict[FailureMode, dict[str, Any]] = {
    FailureMode.DISOBEY_TASK_SPEC: {
        "category": FailureCategory.SPECIFICATION,
        "name": "Disobey Task Spec",
        "description": "Agent ignores or violates explicit task instructions or constraints.",
    },
    FailureMode.DISOBEY_ROLE_SPEC: {
        "category": FailureCategory.SPECIFICATION,
        "name": "Disobey Role Spec",
        "description": "Agent acts outside its assigned role or uses capabilities it wasn't given.",
    },
    FailureMode.STEP_REPETITION: {
        "category": FailureCategory.SPECIFICATION,
        "name": "Step Repetition",
        "description": "Agent repeats the same step or action multiple times without progress.",
    },
    FailureMode.LOSS_OF_CONVERSATION_HISTORY: {
        "category": FailureCategory.SPECIFICATION,
        "name": "Loss of Conversation History",
        "description": (
            "Agent loses context from earlier in the conversation, "
            "repeats or contradicts prior outputs."
        ),
    },
    FailureMode.UNAWARE_OF_TERMINATION: {
        "category": FailureCategory.SPECIFICATION,
        "name": "Unaware of Termination",
        "description": "Agent continues executing after task completion or termination signal.",
    },
    FailureMode.CONVERSATION_RESET: {
        "category": FailureCategory.COORDINATION,
        "name": "Conversation Reset",
        "description": (
            "One agent resets or restarts the conversation unilaterally, losing shared progress."
        ),
    },
    FailureMode.FAIL_TO_ASK_CLARIFICATION: {
        "category": FailureCategory.COORDINATION,
        "name": "Fail to Ask for Clarification",
        "description": (
            "Agent proceeds with ambiguous instructions instead of asking for clarification."
        ),
    },
    FailureMode.TASK_DERAILMENT: {
        "category": FailureCategory.COORDINATION,
        "name": "Task Derailment",
        "description": "Agent shifts focus to an unrelated subtask or goes off on a tangent.",
    },
    FailureMode.INFORMATION_WITHHOLDING: {
        "category": FailureCategory.COORDINATION,
        "name": "Information Withholding",
        "description": "Agent has relevant information but does not share it with other agents.",
    },
    FailureMode.IGNORED_OTHER_AGENT_INPUT: {
        "category": FailureCategory.COORDINATION,
        "name": "Ignored Other Agent Input",
        "description": (
            "Agent disregards or overwrites another agent's contribution without reason."
        ),
    },
    FailureMode.REASONING_ACTION_MISMATCH: {
        "category": FailureCategory.COORDINATION,
        "name": "Reasoning-Action Mismatch",
        "description": "Agent's stated reasoning does not match its actual action or tool call.",
    },
    FailureMode.PREMATURE_TERMINATION: {
        "category": FailureCategory.VERIFICATION,
        "name": "Premature Termination",
        "description": "Agent stops before task is complete, assuming it finished.",
    },
    FailureMode.NO_INCOMPLETE_VERIFICATION: {
        "category": FailureCategory.VERIFICATION,
        "name": "No/Incomplete Verification",
        "description": "Agent does not verify output quality or completeness before submitting.",
    },
    FailureMode.INCORRECT_VERIFICATION: {
        "category": FailureCategory.VERIFICATION,
        "name": "Incorrect Verification",
        "description": "Agent verifies but incorrectly judges the output as correct when it isn't.",
    },
}


def _build_patterns() -> dict[FailureMode, list[re.Pattern[str]]]:
    return {
        FailureMode.STEP_REPETITION: [
            re.compile(r"(repeating|again|already done|duplicate).{0,50}(step|task|action)", re.I),
            re.compile(r"(same|identical).{0,30}(output|result|response)", re.I),
        ],
        FailureMode.TASK_DERAILMENT: [
            re.compile(
                r"(unrelated|off.topic|tangent|irrelevant).{0,50}(task|goal|objective)",
                re.I,
            ),
            re.compile(r"(shifting|changing).{0,30}(focus|topic|subject)", re.I),
        ],
        FailureMode.LOSS_OF_CONVERSATION_HISTORY: [
            re.compile(
                r"(as we discussed earlier|as mentioned before)"
                r".{0,100}(but|however).{0,50}(don't|doesn't)",
                re.I,
            ),
            re.compile(r"(i don't have context|i lost track|what were we doing)", re.I),
        ],
        FailureMode.PREMATURE_TERMINATION: [
            re.compile(
                r"(task complete|finished|done)"
                r".{0,100}(but|however|yet).{0,50}(not|incomplete|missing)",
                re.I,
            ),
            re.compile(r"(output is|result is).{0,20}(empty|truncated|incomplete)", re.I),
        ],
        FailureMode.DISOBEY_TASK_SPEC: [
            re.compile(
                r"(i know you said|despite the instruction|contrary to)"
                r".{0,100}(but|however|still)",
                re.I,
            ),
            re.compile(
                r"(cannot|won't|unable to).{0,30}(because of|due to)"
                r".{0,30}(constraint|limit|restriction)",
                re.I,
            ),
        ],
        FailureMode.DISOBEY_ROLE_SPEC: [
            re.compile(
                r"(i am not|that'?s not my role|out of scope|beyond my)"
                r".{0,50}(role|responsibility|authority)",
                re.I,
            ),
            re.compile(
                r"(acting as|pretending to be|taking on the role of)"
                r".{0,50}(without|not assigned)",
                re.I,
            ),
        ],
        FailureMode.UNAWARE_OF_TERMINATION: [
            re.compile(
                r"(already done|finished that|completed)"
                r".{0,50}(but i|however i|still continuing)",
                re.I,
            ),
            re.compile(
                r"(continuing|proceeding|going ahead)"
                r".{0,50}(after completion|despite being done)",
                re.I,
            ),
        ],
        FailureMode.INFORMATION_WITHHOLDING: [
            re.compile(
                r"(i will not share|not going to tell|keeping this)"
                r".{0,50}(information|detail|data)",
                re.I,
            ),
        ],
        FailureMode.INCORRECT_VERIFICATION: [
            re.compile(
                r"(verif(y|ied|ication).{0,30}(correct|pass|success))"
                r".{0,100}(but|however|yet).{0,50}(error|wrong|incorrect)",
                re.I,
            ),
        ],
        FailureMode.CONVERSATION_RESET: [
            re.compile(r"(restart|reset|start over|from scratch|begin again)", re.I),
        ],
        FailureMode.FAIL_TO_ASK_CLARIFICATION: [
            re.compile(
                r"(ambiguous|unclear|not sure)"
                r".{0,30}(proceeding|continuing|going ahead)",
                re.I,
            ),
        ],
        FailureMode.IGNORED_OTHER_AGENT_INPUT: [
            re.compile(
                r"(ignoring|overwriting|replacing)"
                r".{0,30}(agent'?s?|other'?s?|peer'?s?)",
                re.I,
            ),
            re.compile(
                r"(i don't care about|that doesn't matter|that's wrong)"
                r".{0,50}(what|the|your)",
                re.I,
            ),
        ],
        FailureMode.REASONING_ACTION_MISMATCH: [
            re.compile(
                r"(plan|intend|will).{0,100}(but|however|instead)"
                r".{0,50}(actually|ended up|did)",
                re.I,
            ),
        ],
        FailureMode.NO_INCOMPLETE_VERIFICATION: [
            re.compile(r"(no verification|didn't check|did not verify|skipped validation)", re.I),
            re.compile(
                r"(submitting|delivering|sending).{0,30}(without|no)"
                r".{0,30}(check|verify|review)",
                re.I,
            ),
        ],
    }


PATTERNS = _build_patterns()


def match_patterns(text: str) -> tuple[FailureMode | None, str | None]:
    """Fast-path pattern matching against agent trace text.

    Returns (failure_mode, matched_pattern_text) or (None, None).
    """
    for mode, patterns in PATTERNS.items():
        for p in patterns:
            m = p.search(text)
            if m:
                return mode, m.group()
    return None, None
