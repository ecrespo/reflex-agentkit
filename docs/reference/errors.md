# Errors

## Exceptions

Raised to developers, never to the browser.

```
AgentKitError(Exception)
├── ConfigurationError(AgentKitError, ValueError)   # invalid configuration, tool schema, adapter setup
├── AdapterNotInstalledError(AgentKitError, ImportError)
├── AgentHTTPError(AgentKitError)                   # .status_code
└── AgentStreamError(AgentKitError)                 # .reason: timeout, eof, content_type, connect, agent_raised
```

`ConfigurationError` is raised when a class is defined or an object is built, so a
misconfigured app fails at startup. During a run, `AgentState` catches transport and
agent failures and turns them into `run_status`, `error` and `error_code`; nothing escapes
the background task.

## ErrorCode

The `error_code` state var.

| Code | Set when | `run_status` after |
|---|---|---|
| `MESSAGE_TOO_LONG` | `send_message` is over `max_message_length` | unchanged |
| `AGENT_RUN_ERROR` | the agent sent `RUN_ERROR`; `error` is its message | `error` |
| `AGENT_HTTP_ERROR` | the endpoint answered non-`2xx`; `error` has the status code only | `error` |
| `AGENT_STREAM_ERROR` | timeout, early end of stream, dropped connection, wrong content type | `error` |
| `AGENT_EXCEPTION` | an in-process agent raised, or `create_client()` failed | `error` |
| `INVALID_EDITED_ARGS` | `approve_tool` with arguments that are not a JSON object (or over 64 KiB) | unchanged |
| `SHARED_STATE_LOCKED` | an app write to the shared state during a run | unchanged |
| `SHARED_STATE_INVALID` | an update fails `shared_state_model`, or is not a JSON object within 64 KiB | unchanged |
| `SHARED_STATE_PATCH_FAILED` | a JSON Patch fails to apply | unchanged |
| `CLIENT_TOOL_LOOP_LIMIT` | more than `max_client_tool_rounds` client-tool rounds in one turn | `error` |

A failing client tool is not a run error: the call goes to `error` and the conversation
continues. `error` and `error_code` clear when the next run starts.
