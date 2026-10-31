# Contributing to reflex-agentkit

Thanks for your interest! This project is **spec-driven**: the specifications in
[`specs/`](specs/) are the source of truth, and code follows them. Start with
[`specs/constitution.md`](specs/constitution.md).

## Development setup

The only supported workflow is [uv](https://docs.astral.sh/uv/) (≥ 0.11).

```bash
git clone https://github.com/ecrespo/reflex-agentkit.git
cd reflex-agentkit
uv sync --all-extras        # creates .venv with all extras and the dev group
```

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/check_gated_coverage.py
```

CI runs the same checks on Python 3.11, 3.12 and 3.13, plus a `core-no-extras` job that
installs the package without extras and checks that `reflex_agentkit.core` imports neither
`reflex` nor any optional framework.

## Tests

- `reflex_agentkit.core` and `reflex_agentkit.state` are written **test-first**: the
  failing test lands in a `test:` commit before the `feat:` commit that makes it pass.
- Coverage must stay at or above 85 % on each of `core` and `state`.
- Test names embed the requirement they verify: `test_REQ_<NNN>_<k>_<behavior>`, for
  example `test_REQ_013_3_approve_with_edited_args_records_payload`. Technical-design
  items use `test_DD_<NNN>_…` and data-model invariants `test_INV_<N>_…`.
  `uv run pytest -k REQ_013` selects every test for a requirement.
- Event fixtures are JSON Lines files under `tests/fixtures/`.

## Changing behavior: the delta-spec gate

Any change to observable behavior or to the public API needs an **approved delta spec**
under `changes/<yyyy-mm>-<slug>/` before code is written. Once merged, the delta is
folded into `specs/`. Pure bug fixes that restore the specified behavior do not need one.
Requirement IDs are never reused.

## Commits and changelog

- [Conventional Commits](https://www.conventionalcommits.org/): `feat(core): …`,
  `fix(state): …`, `test(core): …`, `docs: …`, `ci: …`, `build: …`.
- User-visible changes get an entry under `[Unreleased]` in
  [`CHANGELOG.md`](CHANGELOG.md) ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)).
- Everything (code, docs, commits) is written in English.

## Dependencies

Do not add dependencies in a regular PR. New or re-pinned dependencies need a note in the
Technical Design (DD-001) and are added by the maintainer with `uv add`.
