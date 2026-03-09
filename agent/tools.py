from langchain.tools import tool

# Shared conversation log accessible by all tools
conversation_log: list[dict] = []


@tool
def send_reply_tool(message: str) -> str:
    """Send a reply message back to Phone B via Bluetooth."""
    try:
        # In a real deployment this would write to the Bluetooth socket.
        # Here we record the outgoing reply and return confirmation.
        conversation_log.append({"role": "assistant", "content": message})
        return f"Reply sent: {message}"
    except Exception as e:
        return f"Failed to send reply: {e}"


@tool
def get_call_context_tool() -> str:
    """Retrieve the last 5 messages from the current conversation."""
    try:
        recent = conversation_log[-5:] if len(conversation_log) >= 5 else conversation_log
        if not recent:
            return "No conversation history yet."
        lines = [f"{entry['role'].capitalize()}: {entry['content']}" for entry in recent]
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to retrieve context: {e}"


@tool
def end_call_tool(reason: str) -> str:
    """End the call gracefully with the given reason."""
    try:
        conversation_log.append({"role": "system", "content": f"Call ended: {reason}"})
        return f"CALL_ENDED: {reason}"
    except Exception as e:
        return f"Failed to end call: {e}"
