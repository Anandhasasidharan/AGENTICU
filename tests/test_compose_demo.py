from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_langgraph_recovery_against_compose():
    server = os.environ.get("TEST_AGENTICU_COMPOSE_URL")
    if not server:
        pytest.skip("Set TEST_AGENTICU_COMPOSE_URL to run the live Compose test")

    demo = Path(__file__).resolve().parents[1] / "examples" / "langgraph_recovery_demo.py"
    result = subprocess.run(
        [sys.executable, str(demo), "--server", server],
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "recovered and verified" in result.stdout
