"""Decide whether a push publishes a release (T-041, Plan v1.3, TD §9.1).

- A push to ``main`` publishes when ``__version__`` is publishable (not a ``.dev``
  version) and has no ``v<version>`` tag yet; otherwise it is a no-op.
- A pushed ``v*`` tag must equal ``v<__version__>`` and must not be a ``.dev`` version.

The result is written as ``key=value`` lines to ``$GITHUB_OUTPUT`` (``version``, ``tag``,
``publish``, ``prerelease``). Run from the repository root.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "reflex_agentkit" / "__init__.py"


class ReleaseError(Exception):
    """The push cannot be released as it is."""


@dataclasses.dataclass(frozen=True)
class Decision:
    version: str
    tag: str
    publish: bool
    prerelease: bool


def decide(version: str, *, ref_type: str, ref_name: str, tag_exists: bool) -> Decision:
    """The release decision for one push."""
    try:
        parsed = Version(version)
    except InvalidVersion:
        raise ReleaseError(f"__version__ {version!r} is not a PEP 440 version") from None
    tag = f"v{version}"
    if ref_type == "tag":
        if ref_name != tag:
            raise ReleaseError(f"tag {ref_name} does not match __version__ {version}")
        if parsed.is_devrelease:
            raise ReleaseError(f"{version} is a development version and cannot be released")
        return Decision(version, tag, publish=True, prerelease=parsed.is_prerelease)
    publish = not parsed.is_devrelease and not tag_exists
    return Decision(version, tag, publish=publish, prerelease=parsed.is_prerelease)


def read_version() -> str:
    match = re.search(r'^__version__ = "([^"]+)"', INIT.read_text(encoding="utf-8"), re.M)
    if match is None:
        raise ReleaseError(f"no __version__ in {INIT}")
    return match.group(1)


def tag_exists(tag: str) -> bool:
    """Whether the tag exists on ``origin`` (the checkout may not have fetched tags)."""
    result = subprocess.run(  # noqa: S603  (fixed command)
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return bool(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref-type", default=os.environ.get("GITHUB_REF_TYPE", "branch"))
    parser.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--version", help="defaults to __version__ in the package")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args(argv)
    try:
        version = args.version or read_version()
        exists = args.ref_type == "tag" or tag_exists(f"v{version}")
        decision = decide(
            version, ref_type=args.ref_type, ref_name=args.ref_name, tag_exists=exists
        )
    except ReleaseError as error:
        print(f"::error::{error}")
        return 1
    lines = [
        f"version={decision.version}",
        f"tag={decision.tag}",
        f"publish={str(decision.publish).lower()}",
        f"prerelease={str(decision.prerelease).lower()}",
    ]
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
