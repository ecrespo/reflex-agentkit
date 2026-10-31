# PydanticAI Dojo

The five AG-UI Dojo demos built with reflex-agentkit and PydanticAI, one page each:

| Route | Demo | What it shows |
|---|---|---|
| `/agentic-chat` | Agentic chat | Streaming Markdown replies, a backend tool call card, new thread, stop |
| `/backend-tools` | Backend tool rendering | A custom card (`tool_renderers`) for a server-side tool |
| `/human-in-the-loop` | Human in the loop | `requires_approval=True`: approve, edit the arguments or reject |
| `/shared-state` | Shared state | A recipe in `shared_state` (validated by `shared_state_model`), written by the agent through `STATE_SNAPSHOT` and by the user through JSON Patch |
| `/generative-ui` | Tool-based generative UI | A client tool whose renderer draws a chart |

## Run

From the repository root:

```bash
uv sync --all-extras --all-packages
cd examples/pydantic_ai_dojo
ANTHROPIC_API_KEY=sk-ant-... uv run --package pydantic-ai-dojo reflex run
```

`AGENTKIT_MODEL` picks the model (see [`examples/_shared`](../_shared/README.md)):

- unset: Claude (`claude-sonnet-5-5`, needs `ANTHROPIC_API_KEY`);
- `AGENTKIT_MODEL=ollama:qwen3`: a local Ollama model with tool calling
  (`OLLAMA_BASE_URL`, default `http://localhost:11434/v1`);
- `AGENTKIT_MODEL=test`: PydanticAI's `TestModel`, offline (what CI uses).
