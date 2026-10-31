# Human in the loop

An agent can stop and ask before it acts. reflex-agentkit uses the AG-UI standard
interrupts for both kinds of pause: **approvals** for a tool call, and **questions**
(generic interrupts) for anything else. While paused, `run_status` is `awaiting_input`
and `agent_chat` opens the approval dialog.

## Approvals with PydanticAI

Mark the tool `requires_approval=True`. Nothing else is needed: the adapter makes the
agent pause cleanly.

```python
@agent.tool_plain(requires_approval=True)
def book_hotel(city: str, nights: int) -> str:
    """Book a hotel room."""
    return f"Booked {nights} nights in {city}."
```

The dialog lets the user approve, edit the arguments as JSON, or reject with a reason.
Edited arguments are what the tool receives. A rejection becomes the tool's result, so
the model can react to it.

## Approvals with LangGraph

Call `request_tool_approval` inside a node or tool. It pauses the graph and returns the
decision when the run resumes:

```python
from reflex_agentkit.adapters.langgraph import request_tool_approval


def act(state):
    call = state["messages"][-1].tool_calls[0]
    decision = request_tool_approval(str(call["id"]), call["name"], call["args"])
    if decision.approved:
        result = book_hotel(**decision.args)  # the edited arguments, if any
    else:
        result = f"Rejected: {decision.reason or 'no reason given'}"
    return {"messages": [ToolMessage(content=result, tool_call_id=call["id"])]}
```

The graph needs a checkpointer (for example `InMemorySaver`), because LangGraph resumes
from its checkpoint.

## Questions

In LangGraph, `interrupt(value)` asks the user. A `dict` value with `reason` and
`message` keys sets `PendingInterrupt.reason` and `.message`; the whole value is in
`.payload`.

```python
from langgraph.types import interrupt


def ask(state):
    nights = interrupt({"reason": "question", "message": "How many nights?"})
    return {"nights": int(nights)}
```

The default form is a JSON editor, validated against the interrupt's `response_schema`
when there is one. Register a renderer per `reason` to replace it. The renderer must call
`respond_to_interrupt` itself:

```python
def question_form(pending, state):
    return rx.form(
        rx.text(pending.message),
        rx.input(name="answer", aria_label="Your answer"),
        rx.button("Send answer", type="submit"),
        on_submit=lambda form: state.respond_to_interrupt(form.to(dict)["answer"]),
    )


agent_chat(ChatState, interrupt_renderers={"question": question_form})
```

## Several at once, and cancelling

One pause can hold several interrupts. The dialog shows them one at a time, approvals
first, and the resume run starts when all of them have an answer. Each LangGraph node
receives its own answer.

`cancel_run` while paused rejects the open approvals and cancels the questions. The next
run tells the agent: a LangGraph approval returns
`ApprovalDecision(approved=False, reason="cancelled")`, and a cancelled `interrupt()`
returns `{"__agui_cancelled__": True, ...}`.

## The resume payload

Any AG-UI agent that follows this contract works with the dialog:

| Interrupt | `ResumeEntry.status` | `ResumeEntry.payload` |
|---|---|---|
| Approved | `resolved` | `{"approved": true}` |
| Approved with edits | `resolved` | `{"approved": true, "editedArgs": {...}}` |
| Rejected | `resolved` | `{"approved": false, "reason": "..."}` (reason optional) |
| Question answered | `resolved` | the answer, as given |
| Cancelled | `cancelled` | omitted |
