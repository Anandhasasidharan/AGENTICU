from __future__ import annotations

from typing import Any

from agenticu.models import FailureMode

DEFAULT_SIGNATURES: dict[FailureMode, list[str]] = {
    FailureMode.DISOBEY_TASK_SPEC: [
        "Agent was instructed to use tool A but used tool B instead",
        "Agent ignored the constraint to only use provided APIs and called an external service",
        "Agent modified a file the task explicitly said not to modify",
    ],
    FailureMode.DISOBEY_ROLE_SPEC: [
        "Agent took on a role it was not assigned in the system prompt",
        "Agent used capabilities outside its defined scope or authority",
        "Agent impersonated another agent or assumed a different identity",
    ],
    FailureMode.UNAWARE_OF_TERMINATION: [
        "Agent continued processing after the task was already completed",
        "Agent sent additional messages after receiving a termination signal",
        "Agent kept responding after the conversation should have ended",
    ],
    FailureMode.CONVERSATION_RESET: [
        "Agent restarted the conversation from scratch, losing all prior context",
        "Agent ignored shared conversation state and began anew",
        "Agent unilaterally reset the dialogue without consulting other agents",
    ],
    FailureMode.FAIL_TO_ASK_CLARIFICATION: [
        "Agent proceeded with ambiguous instructions instead of asking for clarification",
        "Agent made assumptions about unclear requirements instead of requesting details",
        "Agent guessed the intent of a vague instruction rather than seeking confirmation",
    ],
    FailureMode.INFORMATION_WITHHOLDING: [
        "Agent had the answer but did not share it with other agents",
        "Agent kept relevant data to itself when it should have broadcast it",
        "Agent withheld search results that would have helped the team make a decision",
    ],
    FailureMode.IGNORED_OTHER_AGENT_INPUT: [
        "Agent overwrote another agent's contribution without justification",
        "Agent dismissed a peer's valid output without considering it",
        "Agent ignored a recommendation from another agent and repeated the same mistake",
    ],
    FailureMode.REASONING_ACTION_MISMATCH: [
        "Agent stated one intent but performed a different action",
        "Agent's tool call contradicted its stated plan or reasoning",
        "Agent claimed it would do X but then did Y without explanation",
    ],
    FailureMode.NO_INCOMPLETE_VERIFICATION: [
        "Agent submitted output without verifying correctness",
        "Agent skipped the validation step entirely before delivering results",
        "Agent did not check its work for errors before presenting it as final",
    ],
    FailureMode.STEP_REPETITION: [
        "Agent called the same function with the same arguments repeatedly",
        "Agent generated identical output in consecutive turns",
        "Agent repeated a step it already completed without acknowledging prior work",
    ],
    FailureMode.LOSS_OF_CONVERSATION_HISTORY: [
        "Agent forgot what was discussed earlier in the conversation",
        "Agent contradicted a decision it made two turns ago",
        "Agent restated a goal that was already achieved",
    ],
    FailureMode.TASK_DERAILMENT: [
        "Agent started working on a subtask that was not part of the original plan",
        "Agent pursued an unrelated research direction instead of completing the current step",
        "Agent got sidetracked by an interesting but irrelevant detail",
    ],
    FailureMode.PREMATURE_TERMINATION: [
        "Agent declared the task complete but the output is missing required sections",
        "Agent stopped after completing only the first step of a multi-step workflow",
        "Agent returned an empty or trivial result claiming the task was too simple",
    ],
    FailureMode.INCORRECT_VERIFICATION: [
        "Agent marked a buggy output as correct during self-verification",
        "Agent verified its own work and passed it despite clear logical errors",
        "Agent claimed all test cases passed but the code doesn't compile",
    ],
}


class SignatureDB:
    """Known failure signatures for embedding-based classification.

    Pre-loaded with examples from the MAST taxonomy paper.
    User-extendable via add_signature().
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._signatures: dict[FailureMode, list[str]] = {}
        for mode, sigs in DEFAULT_SIGNATURES.items():
            self._signatures[mode] = list(sigs)

    def add_signature(self, mode: FailureMode, text: str) -> None:
        self._signatures.setdefault(mode, []).append(text)

    def get_signatures(self, mode: FailureMode) -> list[str]:
        return self._signatures.get(mode, [])

    def get_all(self) -> list[tuple[FailureMode, str]]:
        results: list[tuple[FailureMode, str]] = []
        for mode, sigs in self._signatures.items():
            for sig in sigs:
                results.append((mode, sig))
        return results

    def remove_signature(self, mode: FailureMode, text: str) -> bool:
        sigs = self._signatures.get(mode, [])
        if text in sigs:
            sigs.remove(text)
            return True
        return False
