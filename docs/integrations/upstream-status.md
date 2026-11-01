# Upstream submissions: status

reflex-agentkit asked three upstream projects to mention it in their docs. All three
requests are **waiting on the maintainers** of those projects. Nothing is blocked on our
side, and the library doesn't depend on any of them being accepted.

*Last checked: 2026-10-31.*

| Project | Submission | What we asked for | Status |
|---|---|---|---|
| AG-UI | [PR ag-ui-protocol/ag-ui#3280](https://github.com/ag-ui-protocol/ag-ui/pull/3280) | One row in the README's **Clients** table | Open, review required, no comments |
| PydanticAI | [Issue pydantic/pydantic-ai#12141](https://github.com/pydantic/pydantic-ai/issues/12141) | A "Python frontend with Reflex" subsection on the AG-UI page | Open, labeled `pydanty:is-working`, no comments |
| LangChain docs | [Issue langchain-ai/docs#7266](https://github.com/langchain-ai/docs/issues/7266) | A "Frontend with Reflex" page in the LangGraph docs | Open, labeled `external`, unassigned, no comments |

The texts we proposed are the drafts on the other pages of this section:

- [AG-UI integrations table](ag-ui-integration-entry.md)
- [PydanticAI docs page](pydantic-ai-ui-with-reflex.md)
- [LangGraph docs page](langgraph-frontend-with-reflex.md)

## Why two are issues and not pull requests

PydanticAI and LangChain both ask for an issue first. A maintainer has to agree before
anyone opens a PR that adds a section or a page:

- PydanticAI's contributing guide says to align with a maintainer on the approach before
  writing code. Only typos and small doc fixes can go straight to a PR.
- LangChain's contributing guide says new pages need a linked issue and maintainer
  approval. PRs opened without that may be closed automatically.

AG-UI asks contributors to reach out before *significant* work. A single table row isn't,
so that one went straight to a PR.

## How to read each response

Watch the notifications on the GitHub account that opened the submissions (`ecrespo`),
then act on what the maintainers say:

### AG-UI (#3280)

| Response | What it means | Next step |
|---|---|---|
| Merged | reflex-agentkit is listed as an AG-UI client | Nothing more; update this page |
| Changes requested | They want different wording, a link or a position in the table | Push the change to the same branch (`docs/reflex-agentkit-client` on the fork `ecrespo/ag-ui`) |
| "List it on the docs site instead" | They prefer [docs.ag-ui.com](https://docs.ag-ui.com/introduction#supported-integrations) | Reuse the same text there, following their instructions |
| Closed without merging | They don't want third-party clients in the table | Accept it; no follow-up |

### PydanticAI (#12141)

| Response | What it means | Next step |
|---|---|---|
| A maintainer agrees (and may assign the issue) | We can open the PR | Open it from the [draft](pydantic-ai-ui-with-reflex.md), linking the issue |
| Agreement plus an answer about the code block | Their docs tests run code blocks, and ours imports `reflex` and `reflex_agentkit` | Apply what they choose (a skip marker, or showing the block as plain text) |
| An automated reply (the `pydanty:is-working` label) | Their bot is triaging; it is not a maintainer's decision | Wait for a human maintainer, unless the bot asks something specific |
| "Publish it in your own docs" or closed | They don't want third-party frontends in their docs | Accept it; our own docs already cover PydanticAI |

### LangChain docs (#7266)

| Response | What it means | Next step |
|---|---|---|
| Approved and assigned | We can open the PR | Open it from the [draft](langgraph-frontend-with-reflex.md), run their local preview and link checks first, and link the issue |
| "Put it elsewhere" | They prefer a community or integrations listing | Adapt the draft to the place they name |
| Closed | They don't take third-party frontend pages | Accept it; no follow-up |

## While we wait

- Nothing to do. Don't open the PydanticAI or LangChain PRs before a maintainer agrees:
  both projects may close them unread.
- If a submission sees no response for several weeks, a short polite follow-up comment
  on the issue or PR is fine. PydanticAI also suggests pinging `#pydantic-ai` on their
  Slack.
- When a response arrives, update the table at the top of this page and the "Submitted"
  note on the matching draft page.

## Related upstream bug

The `ag-ui-langgraph` `fastapi` import bug was already reported upstream as
[ag-ui-protocol/ag-ui#2013](https://github.com/ag-ui-protocol/ag-ui/issues/2013), so we
didn't file it again. See [Upstream issues](upstream-issues.md).
