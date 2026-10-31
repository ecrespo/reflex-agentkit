"""Fail if line+branch coverage of a gated package is below the threshold.

Constitution Art. 6 requires >= 85 % on each of ``reflex_agentkit/core`` and
``reflex_agentkit/state`` separately. A package with no measurable statements counts
as 100 %. Run after ``uv run pytest`` (which writes ``.coverage``).
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import coverage
from coverage.exceptions import NoDataError

ROOT = Path(__file__).resolve().parent.parent
GATED_PACKAGES = ("core", "state")
DEFAULT_THRESHOLD = 85.0


def package_coverage(cov: coverage.Coverage, package: str) -> float:
    """Return the coverage percentage of one package; 100.0 if it has nothing to measure."""
    pattern = str(ROOT / "src" / "reflex_agentkit" / package / "*")
    try:
        return cov.report(include=[pattern], file=io.StringIO())
    except NoDataError:
        return 100.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", default=str(ROOT / ".coverage"))
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    if not Path(args.data_file).exists():
        print(f"error: no coverage data at {args.data_file}; run `uv run pytest` first")
        return 2

    cov = coverage.Coverage(data_file=args.data_file, config_file=str(ROOT / "pyproject.toml"))
    cov.load()

    failed = False
    for package in GATED_PACKAGES:
        percent = package_coverage(cov, package)
        ok = percent >= args.threshold
        failed |= not ok
        status = "ok" if ok else "FAIL"
        print(f"reflex_agentkit/{package}: {percent:.1f} % (min {args.threshold:.0f} %) {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
