# AGENTS.md

Guidance for coding agents working on reflex-agentkit.

1. **Read [`specs/constitution.md`](specs/constitution.md) first.** Its articles are
   non-negotiable, and its glossary (run, thread, tool call, approval, interrupt, shared
   state, adapter, client) is canonical.
2. Work from the approved specs in `specs/`: PRD (`REQ-NNN.k`), API, Technical Design,
   Data Model, Plan and Tasks. Pick the next task in
   [`specs/tasks/agentkit-tasks.md`](specs/tasks/agentkit-tasks.md) and mark progress there.
3. Any change to observable behavior or public API needs an approved delta spec in
   `changes/<yyyy-mm>-<slug>/` first. If a task shows that a spec is wrong, stop and fix
   the spec before continuing.
4. `core` and `state` are written test-first. Test names embed the requirement ID:
   `test_REQ_<NNN>_<k>_<behavior>`.

## Standard commands (uv only)

```bash
uv sync --all-extras                               # env with all extras + dev group
uv run ruff check . && uv run ruff format --check .
uv run mypy                                        # strict on core and state
uv run pytest                                      # tests with coverage
uv run python scripts/check_gated_coverage.py      # >= 85 % on core and on state
uv run python scripts/assert_core_isolated.py      # core imports no reflex / extras
uv build
```

The full table is in `CLAUDE.md` and in Plan §1.1 (`specs/plans/agentkit-phase-1.md`).
