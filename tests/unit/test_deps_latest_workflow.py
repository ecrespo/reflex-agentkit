"""The weekly latest-dependencies workflow (T-049, DD-001)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "deps-latest.yml"


def _workflow() -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return loaded


def test_DD_001_deps_latest_runs_weekly_and_on_demand() -> None:
    """It runs on a weekly schedule and can be started by hand."""
    triggers = _workflow()[True]  # YAML 1.1 reads the ``on`` key as True
    assert len(triggers["schedule"]) == 1
    assert "workflow_dispatch" in triggers


def test_DD_001_deps_latest_never_blocks_or_writes_the_repository() -> None:
    """Failures never fail the run; read-only contents; the upgrade is in a temporary copy."""
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["latest"]
    assert job["permissions"] == {"contents": "read"}
    upgrade = next(step for step in job["steps"] if step.get("id") == "tests")
    assert upgrade["continue-on-error"] is True
    assert "mktemp -d" in upgrade["run"]
    assert "uv lock --upgrade" in upgrade["run"]
    steps = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "git push" not in steps
    assert "git commit" not in steps


def test_DD_001_unvetted_dependencies_never_run_with_a_token() -> None:
    """The job that installs the newest versions has no token and no stored credentials."""
    job = _workflow()["jobs"]["latest"]
    assert "GH_TOKEN" not in str(job.get("env", {}))
    assert all("GH_TOKEN" not in str(step.get("env", {})) for step in job["steps"])
    checkout = next(
        s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["persist-credentials"] is False


def test_DD_001_deps_latest_reports_failures_in_an_issue() -> None:
    """A separate job, which installs nothing, opens an issue or comments on the open one."""
    report = _workflow()["jobs"]["report"]
    assert report["needs"] == "latest"
    assert report["if"] == "needs.latest.outputs.failed == 'true'"
    assert report["permissions"] == {"issues": "write"}
    script = "\n".join(str(step.get("run", "")) for step in report["steps"])
    assert "gh issue create" in script
    assert "gh issue comment" in script
    assert "uv " not in script
