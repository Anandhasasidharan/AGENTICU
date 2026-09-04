from __future__ import annotations

from agenticu.classification.mast_taxonomy import FAILURE_MODE_DEFINITIONS, match_patterns
from agenticu.models import FailureCategory, FailureMode


def test_all_14_modes_defined():
    assert len(FAILURE_MODE_DEFINITIONS) == 14


def _by_category(category: FailureCategory) -> list:
    return [m for m, d in FAILURE_MODE_DEFINITIONS.items() if d["category"] == category]


def test_category_counts():
    spec = _by_category(FailureCategory.SPECIFICATION)
    coord = _by_category(FailureCategory.COORDINATION)
    verif = _by_category(FailureCategory.VERIFICATION)
    assert len(spec) == 5
    assert len(coord) == 6
    assert len(verif) == 3


def test_pattern_step_repetition():
    mode, match = match_patterns("the agent kept repeating the same step over and over")
    assert mode == FailureMode.STEP_REPETITION
    assert match is not None


def test_pattern_task_derailment():
    mode, match = match_patterns(
        "the agent went off on an unrelated topic instead of completing the task"
    )
    assert mode == FailureMode.TASK_DERAILMENT
    assert match is not None


def test_pattern_premature_termination():
    mode, match = match_patterns("task complete but the output is incomplete")
    assert mode == FailureMode.PREMATURE_TERMINATION
    assert match is not None


def test_pattern_no_match():
    mode, match = match_patterns("everything is working normally")
    assert mode is None
    assert match is None


def test_pattern_loss_of_history():
    mode, match = match_patterns("i lost track of what we were doing")
    assert mode == FailureMode.LOSS_OF_CONVERSATION_HISTORY


def test_pattern_disobey_task_spec():
    mode, match = match_patterns(
        "despite the instruction to use tool A, the agent still used tool B"
    )
    assert mode == FailureMode.DISOBEY_TASK_SPEC


def test_signature_db_defaults():
    from agenticu.classification.signature_db import SignatureDB

    db = SignatureDB()
    sigs = db.get_all()
    assert len(sigs) > 0
    modes = {m for m, _ in sigs}
    assert FailureMode.DISOBEY_TASK_SPEC in modes
    assert FailureMode.STEP_REPETITION in modes
