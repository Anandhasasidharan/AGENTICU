from __future__ import annotations

import threading
from collections import defaultdict

from agenticu import metrics as prom
from agenticu.models import FailureMode, RecoveryAttempt


class MetricsTracker:
    """In-memory recovery success rate tracking.

    Thread-safe. Periodic snapshot to Prometheus via the API layer.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._attempts: list[RecoveryAttempt] = []
        self._by_mode: dict[FailureMode, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "succeeded": 0, "failed": 0}
        )

    def record(self, attempt: RecoveryAttempt) -> None:
        with self._lock:
            self._attempts.append(attempt)
            if attempt.failure_mode and attempt.success is not None:
                slot = self._by_mode[attempt.failure_mode]
                slot["total"] += 1
                if attempt.success:
                    slot["succeeded"] += 1
                else:
                    slot["failed"] += 1
        prom.record_recovery_attempt(attempt)

    def success_rate(self, mode: FailureMode | None = None) -> float:
        with self._lock:
            if mode is not None:
                slot = self._by_mode.get(mode, {"total": 1, "succeeded": 0, "failed": 0})
                total = slot["total"]
                succeeded = slot["succeeded"]
            else:
                total = len(self._attempts)
                succeeded = sum(1 for a in self._attempts if a.success)
            if total == 0:
                return 0.0
            return succeeded / total

    def count_by_mode(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {k.value: dict(v) for k, v in self._by_mode.items()}
