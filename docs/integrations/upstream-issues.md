# Upstream issues (drafts)

Issues found while building reflex-agentkit that belong to upstream projects. Each one is
a draft for the maintainer to file; none has been filed by the agent. TD OQ-4 tracks the
first one.

## ag-ui-langgraph: `import ag_ui_langgraph` requires `fastapi`, which is an optional extra

**Repository:** `ag-ui-protocol/ag-ui` (package `integrations/langgraph/python`,
published as `ag-ui-langgraph`)
**Version:** 0.0.47
**Status:** already reported upstream as [ag-ui-protocol/ag-ui#2013](https://github.com/ag-ui-protocol/ag-ui/issues/2013) (open; still reproduces on 0.0.47, checked 2026-10-31), so this draft was not filed

### Title

`import ag_ui_langgraph` fails without FastAPI although `fastapi` is an optional extra

### Body

`ag-ui-langgraph` declares FastAPI as an optional extra:

```text
Provides-Extra: fastapi
Requires-Dist: fastapi>=0.115.12; extra == 'fastapi'
```

But the package's `__init__.py` imports the endpoint module unconditionally:

```python
from .endpoint import add_langgraph_fastapi_endpoint
```

and `endpoint.py` imports FastAPI at module level:

```python
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
```

So `pip install ag-ui-langgraph` followed by `import ag_ui_langgraph` raises
`ModuleNotFoundError: No module named 'fastapi'`, even for users who only need
`LangGraphAgent` (for example, to run the agent in process, with no HTTP server).

**Steps to reproduce**

```bash
python -m venv venv && . venv/bin/activate
pip install "ag-ui-langgraph==0.0.47"
python -c "import ag_ui_langgraph"
```

**Expected:** the import succeeds, and only `add_langgraph_fastapi_endpoint` needs the
`fastapi` extra.

**Suggested fix:** import the endpoint lazily, for example with a module `__getattr__`
in `__init__.py`:

```python
def __getattr__(name):
    if name == "add_langgraph_fastapi_endpoint":
        from .endpoint import add_langgraph_fastapi_endpoint
        return add_langgraph_fastapi_endpoint
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

or guard the import and raise an `ImportError` that names the extra when the function is
used without FastAPI.

**Workaround we use:** our `langgraph` extra depends on `ag-ui-langgraph[fastapi]`. A
contract test (`tests/contract/test_langgraph_facts.py::test_TD_OQ_4_ag_ui_langgraph_imports_fastapi_unconditionally`)
fails once the upstream fix ships, which is our cue to drop the `[fastapi]` extra.
