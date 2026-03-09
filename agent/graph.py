from typing import TypedDict, List, Dict
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END

import config
from agent.prompts import SYSTEM_PROMPT

# Phrases that signal the caller wants to end the call
END_CALL_PHRASES = ("goodbye", "bye", "end call", "hang up", "talk later")


class AgentState(TypedDict):
    user_input: str
    response: str
    call_active: bool
    conversation_history: List[Dict[str, str]]


def _build_llm() -> ChatGroq:
    return ChatGroq(
        api_key=config.GROQ_API_KEY,
        model=config.GROQ_MODEL,
        temperature=0.7,
    )


def listen_node(state: AgentState) -> AgentState:
    """Add the latest user input to the conversation history."""
    history = list(state.get("conversation_history", []))
    history.append({"role": "user", "content": state["user_input"]})
    return {**state, "conversation_history": history}


def think_node(state: AgentState) -> AgentState:
    """Call the Groq LLM with the system prompt and recent history."""
    try:
        llm = _build_llm()
        history = state.get("conversation_history", [])

        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for entry in history[-6:]:
            if entry["role"] == "user":
                messages.append(HumanMessage(content=entry["content"]))
            elif entry["role"] == "assistant":
                messages.append(AIMessage(content=entry["content"]))

        result = llm.invoke(messages)
        response_text = result.content.strip()
    except Exception as e:
        response_text = f"I encountered an error: {e}"

    return {**state, "response": response_text}


def respond_node(state: AgentState) -> AgentState:
    """Append the AI response to history and decide whether the call continues."""
    history = list(state.get("conversation_history", []))
    response = state.get("response", "")
    history.append({"role": "assistant", "content": response})

    user_input_lower = state.get("user_input", "").lower()
    call_active = not any(phrase in user_input_lower for phrase in END_CALL_PHRASES)

    return {**state, "conversation_history": history, "call_active": call_active}


def should_continue(state: AgentState) -> str:
    """Return 'end' if the call is no longer active, otherwise 'continue'."""
    if state.get("call_active", True):
        return "continue"
    return "end"


def build_agent_graph():
    """Compile and return the LangGraph agent."""
    graph = StateGraph(AgentState)

    graph.add_node("listen", listen_node)
    graph.add_node("think", think_node)
    graph.add_node("respond", respond_node)

    graph.set_entry_point("listen")
    graph.add_edge("listen", "think")
    graph.add_edge("think", "respond")
    graph.add_conditional_edges(
        "respond",
        should_continue,
        {"continue": END, "end": END},
    )

    return graph.compile()


def run_agent(
    user_input: str,
    history: List[Dict[str, str]],
) -> tuple[str, List[Dict[str, str]], bool]:
    """Run a single turn of the agent and return (response, updated_history, call_active)."""
    compiled = build_agent_graph()
    initial_state: AgentState = {
        "user_input": user_input,
        "response": "",
        "call_active": True,
        "conversation_history": history,
    }
    result = compiled.invoke(initial_state)
    return result["response"], result["conversation_history"], result["call_active"]
