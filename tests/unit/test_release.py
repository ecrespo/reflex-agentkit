"""Automatic releases (T-041, REQ-032.2, Plan v1.3, TD §9.1).

``scripts/release_version.py`` decides whether a push publishes; ``release.yml`` must keep
the shape that the PyPI trusted publisher was registered with.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_version", ROOT / "scripts" / "release_version.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load_script()


@pytest.mark.parametrize(
    ("version", "tag_exists", "publish", "prerelease"),
    [
        ("0.1.0a1", False, True, True),
        ("0.1.0rc1", False, True, True),
        ("0.1.0", False, True, False),
        ("0.1.0", True, False, False),
        ("0.1.0.dev0", False, False, True),
    ],
)
def test_REQ_032_2_a_push_to_main_publishes_new_versions_only(
    version: str, tag_exists: bool, publish: bool, prerelease: bool
) -> None:
    decision = release.decide(version, ref_type="branch", ref_name="main", tag_exists=tag_exists)
    assert (decision.publish, decision.prerelease, decision.tag) == (
        publish,
        prerelease,
        f"v{version}",
    )


def test_REQ_032_2_a_matching_tag_publishes() -> None:
    decision = release.decide("0.1.0a1", ref_type="tag", ref_name="v0.1.0a1", tag_exists=True)
    assert (decision.publish, decision.prerelease) == (True, True)


@pytest.mark.parametrize(
    ("version", "ref_name"), [("0.1.0a1", "v0.1.0"), ("0.1.0.dev0", "v0.1.0.dev0")]
)
def test_REQ_032_2_a_wrong_or_dev_tag_is_an_error(version: str, ref_name: str) -> None:
    with pytest.raises(release.ReleaseError):
        release.decide(version, ref_type="tag", ref_name=ref_name, tag_exists=True)


def test_REQ_032_2_an_invalid_version_is_an_error() -> None:
    with pytest.raises(release.ReleaseError):
        release.decide("not a version", ref_type="branch", ref_name="main", tag_exists=False)


def test_REQ_032_2_cli_writes_github_outputs(tmp_path: Path) -> None:
    output = tmp_path / "out"
    subprocess.run(  # noqa: S603  (fixed command)
        [
            sys.executable,
            str(ROOT / "scripts" / "release_version.py"),
            "--ref-type",
            "branch",
            "--ref-name",
            "main",
            "--version",
            "9.9.9rc1",
            "--github-output",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    lines = output.read_text().splitlines()
    assert lines == ["version=9.9.9rc1", "tag=v9.9.9rc1", "publish=true", "prerelease=true"]


def _workflow() -> dict[str, Any]:
    data: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads `on` as True
    return data


def test_REQ_032_2_release_runs_on_main_and_on_tags() -> None:
    triggers = _workflow()["on"]
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["tags"] == ["v*"]


def test_REQ_032_2_publish_job_matches_the_trusted_publisher() -> None:
    """The PyPI pending publisher names workflow ``release.yml`` and environment ``pypi``."""
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    publish = workflow["jobs"]["pypi"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["permissions"] == {"id-token": "write"}
    commands = " ".join(step.get("run", "") for step in publish["steps"])
    assert "uv publish --trusted-publishing always" in commands
    others = [job for name, job in workflow["jobs"].items() if name != "pypi"]
    assert all("id-token" not in job.get("permissions", {}) for job in others)
    assert "test.pypi" not in WORKFLOW.read_text(encoding="utf-8")


def test_REQ_032_2_tests_gate_the_build_and_the_tag_follows_the_upload() -> None:
    jobs = _workflow()["jobs"]
    build_steps = " ".join(step.get("run", "") for step in jobs["build"]["steps"])
    assert "uv run pytest" in build_steps
    assert build_steps.index("uv run pytest") < build_steps.index("uv build")
    assert jobs["pypi"]["needs"] == "build"
    assert jobs["github-release"]["needs"] == ["build", "pypi"]
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
