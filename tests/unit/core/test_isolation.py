"""The pure core imports neither Reflex nor any extra (REQ-031.2, Constitution Art. 5)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "assert_core_isolated.py"


def test_REQ_031_2_core_import_pulls_no_reflex_or_extras() -> None:
    """REQ-031.2: a fresh interpreter importing the core loads no forbidden module."""
    result = subprocess.run(  # noqa: S603  # fixed argv: this interpreter + repo script
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
