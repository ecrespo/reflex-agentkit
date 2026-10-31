# Local models with Ollama

[Ollama](https://ollama.com) runs open models on your machine. Use a model that supports
**tool calling**, or tool calls and approvals will not work. Pull one first:

```bash
ollama pull qwen3
```

Ollama serves an OpenAI-compatible API at `http://localhost:11434/v1`.

## PydanticAI

Use the `ollama:` model prefix and point `OLLAMA_BASE_URL` at the server:

```python
agent = Agent("ollama:qwen3", instructions="You are a helpful travel assistant.")
```

```bash
OLLAMA_BASE_URL=http://localhost:11434/v1 uv run reflex run
```

Or build the model explicitly:

```python
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

model = OllamaModel("qwen3", provider=OllamaProvider(base_url="http://localhost:11434/v1"))
agent = Agent(model, instructions="You are a helpful travel assistant.")
```

## LangGraph

Any LangChain chat model works in the graph. Through the OpenAI-compatible endpoint, with
`langchain-openai` installed:

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="qwen3", base_url="http://localhost:11434/v1", api_key="ollama")
```

The API key is required by the client but ignored by Ollama.

## In the examples

Every example reads `AGENTKIT_MODEL`:

```bash
AGENTKIT_MODEL=ollama:qwen3 uv run --package pydantic-ai-dojo reflex run
```

Leave it unset for Claude, or set `AGENTKIT_MODEL=test` for an offline model that needs
neither a key nor a server.

!!! tip "Keep the loop free"
    Ollama runs in its own process, so model calls do not block the Reflex event loop.
    A model run *inside* Python (for example with `transformers`) would: put that agent
    in a [sidecar](sidecar.md).
