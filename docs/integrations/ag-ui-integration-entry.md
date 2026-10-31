# AG-UI integrations table entry (draft)

!!! info "How to submit"
    - **Target repository:** [`ag-ui-protocol/ag-ui`](https://github.com/ag-ui-protocol/ag-ui)
    - **File:** `README.md`, section **Clients** (the table with the columns *Client*,
      *Status*, *AG-UI Resources*, *Integrations*)
    - **PR title:** `docs: add reflex-agentkit (Python / Reflex) to the clients table`
    - **When:** after `reflex-agentkit 0.1.0` is on PyPI, so the link installs a release.
    - Follow the repo's [contributing guide](https://github.com/ag-ui-protocol/ag-ui/blob/main/CONTRIBUTING.md).
      If the maintainers prefer the docs site list
      ([supported integrations](https://docs.ag-ui.com/introduction#supported-integrations)),
      reuse the same text there.

## The row

Insert it in the **Clients** table, after the existing community rows:

```markdown
| [Reflex (Python)](https://github.com/ecrespo/reflex-agentkit) | ✅ Supported | ➡️ [Getting Started](https://github.com/ecrespo/reflex-agentkit#quickstart) 🎮 [Dojo demos](https://github.com/ecrespo/reflex-agentkit/tree/main/examples) | Community |
```

## PR description

```markdown
This adds reflex-agentkit to the Clients table.

reflex-agentkit is an AG-UI client for Python web apps built with Reflex: a streaming
chat, tool-call cards, human-in-the-loop approvals through standard interrupts
(`RUN_FINISHED` with `outcome.type == "interrupt"`, answered via `RunAgentInput.resume`),
shared state (`STATE_SNAPSHOT` / `STATE_DELTA`) and frontend tools, with no
JavaScript to write.

- It consumes any AG-UI 1.0 server over HTTP + SSE, or runs PydanticAI and LangGraph
  agents in process through their AG-UI integrations.
- It handles all 31 event types of the 1.0 spec.
- The repository ports the five Dojo demos (agentic chat, backend tool rendering, human
  in the loop, shared state, tool-based generative UI) to Python, for both PydanticAI
  and LangGraph.

PyPI: https://pypi.org/project/reflex-agentkit/ · License: MIT
```
