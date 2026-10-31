# LangGraph Dojo

The five AG-UI Dojo demos built with reflex-agentkit and LangGraph, one page each:

| Route | Demo | What it shows |
|---|---|---|
| `/agentic-chat` | Agentic chat | Streaming Markdown replies, a tool node's call card, new thread, stop |
| `/backend-tools` | Backend tool rendering | A custom card (`tool_renderers`) for a tool that runs in the graph |
| `/human-in-the-loop` | Human in the loop | `interrupt()` for a question (custom form) and `request_tool_approval` for a booking: approve, edit the arguments or reject |
| `/shared-state` | Shared state | A recipe kept in the graph state, shown in `shared_state` (validated by `shared_state_model`) and renamed by the user through JSON Patch |
| `/generative-ui` | Tool-based generative UI | A client tool the graph binds from the AG-UI `tools` state key; its renderer draws a chart |

Each graph has a checkpointer (`InMemorySaver`), which `LangGraphAGUIAgent` requires for
interrupts and resumes.

## Run

From the repository root:

```bash
uv sync --all-extras --all-packages
cd examples/langgraph_dojo
ANTHROPIC_API_KEY=sk-ant-... uv run --package langgraph-dojo reflex run
```

`AGENTKIT_MODEL` picks the chat model (see [`examples/_shared`](../_shared/README.md)):

- unset: Claude (`claude-sonnet-5-5` through `langchain-anthropic`, needs
  `ANTHROPIC_API_KEY`);
- `AGENTKIT_MODEL=ollama:qwen3`: a local Ollama model with tool calling, through its
  OpenAI-compatible endpoint (`OLLAMA_BASE_URL`, default `http://localhost:11434/v1`);
- `AGENTKIT_MODEL=test`: an offline fake chat model (what CI uses to compile the app).
