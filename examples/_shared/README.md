# examples-shared

Model selection for the reflex-agentkit examples. Set `AGENTKIT_MODEL` before
`reflex run`:

| `AGENTKIT_MODEL` | PydanticAI examples | LangGraph examples | Needs |
|---|---|---|---|
| unset (default) | `anthropic:claude-sonnet-5-5` | `ChatAnthropic("claude-sonnet-5-5")` | `ANTHROPIC_API_KEY` |
| `ollama:<model>`, e.g. `ollama:qwen3` | `OllamaModel` | `ChatOpenAI` against Ollama's OpenAI-compatible API | a running Ollama with a tool-calling model; `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`) |
| `test` | PydanticAI `TestModel` | an offline fake chat model | nothing (CI uses this) |
| any other PydanticAI model name | passed through | — | that provider's key |

```python
from examples_shared.models import langgraph_model, pydantic_ai_model
```
