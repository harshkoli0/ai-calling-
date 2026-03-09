import gradio as gr

import config
from agent.graph import run_agent
from audio.tts import speak
from bridge.bluetooth_bridge import BluetoothBridge
from bridge.adb_bridge import ADBBridge

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
bt_bridge: BluetoothBridge = BluetoothBridge()
adb_bridge: ADBBridge = ADBBridge()
conversation_history: list[dict] = []
call_active: bool = True


# ---------------------------------------------------------------------------
# Core logic helpers
# ---------------------------------------------------------------------------

def process_message(user_text: str, history: list):
    """Run the agent on user_text, speak the response, and update the chatbot."""
    global conversation_history, call_active

    if not user_text.strip():
        return history, ""

    try:
        response, conversation_history, call_active = run_agent(
            user_text, conversation_history
        )
    except Exception as e:
        response = f"Agent error: {e}"

    # Text-to-speech
    audio_bytes = speak(response)

    # Forward audio to Phone B via Bluetooth (best-effort)
    if bt_bridge.connected and audio_bytes:
        bt_bridge.send_audio(audio_bytes)

    # Update Gradio chatbot history
    history = history + [[user_text, response]]

    status_suffix = "" if call_active else " [Call ended]"
    if not call_active:
        history = history + [[None, f"📴 Call has been ended.{status_suffix}"]]

    return history, ""


def connect_adb() -> str:
    """Connect to Phone A via ADB and return a status string."""
    try:
        success = adb_bridge.connect()
        if success:
            info = adb_bridge.get_device_info()
            return f"✅ ADB connected — {info}"
        return "❌ ADB connection failed. Check USB cable and ADB daemon."
    except Exception as e:
        return f"❌ ADB error: {e}"


def connect_bluetooth(mac_address: str) -> str:
    """Connect to Phone B via Bluetooth and return a status string."""
    try:
        # Update the runtime config so the bridge picks up the new MAC
        config.PHONE_B_BLUETOOTH_MAC = mac_address.strip()
        success = bt_bridge.connect()
        if success:
            return f"✅ Bluetooth connected — {config.PHONE_B_BLUETOOTH_MAC}"
        return "❌ Bluetooth connection failed. Check MAC address and pairing."
    except Exception as e:
        return f"❌ Bluetooth error: {e}"


def disconnect_all() -> str:
    """Disconnect all bridges."""
    try:
        bt_bridge.disconnect()
        return "🔌 All connections disconnected."
    except Exception as e:
        return f"⚠️ Disconnect error: {e}"


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

custom_css = """
#chatbot { border-radius: 12px; }
#send-btn { background: #4f46e5; color: white; border-radius: 8px; }
#clear-btn { border-radius: 8px; }
.status-box { font-family: monospace; font-size: 0.85rem; }
"""

with gr.Blocks(theme=gr.themes.Soft(), css=custom_css, title="AI Calling Agent") as demo:
    gr.Markdown("# 📞 AI Calling Agent")
    gr.Markdown(
        "Relay AI-powered conversations between phones via Bluetooth and ADB."
    )

    with gr.Row():
        # ── Left column: connection setup ───────────────────────────────────
        with gr.Column(scale=1):
            gr.Markdown("## 🔌 Connection Setup")

            with gr.Group():
                gr.Markdown("### ADB (Phone A — USB)")
                adb_status = gr.Textbox(
                    label="ADB Status",
                    value="Not connected",
                    interactive=False,
                    elem_classes="status-box",
                )
                adb_btn = gr.Button("Connect ADB")

            with gr.Group():
                gr.Markdown("### Bluetooth (Phone B)")
                mac_input = gr.Textbox(
                    label="Phone B MAC Address",
                    value=config.PHONE_B_BLUETOOTH_MAC,
                    placeholder="XX:XX:XX:XX:XX:XX",
                )
                bt_status = gr.Textbox(
                    label="Bluetooth Status",
                    value="Not connected",
                    interactive=False,
                    elem_classes="status-box",
                )
                bt_btn = gr.Button("Connect Bluetooth")
                disc_btn = gr.Button("Disconnect All")

            with gr.Group():
                gr.Markdown("### ℹ️ System Info")
                mode_label = "🟡 DEMO MODE" if config.DEMO_MODE else "🟢 LIVE MODE"
                gr.Markdown(f"**Mode:** {mode_label}")
                gr.Markdown(f"**LLM Model:** `{config.GROQ_MODEL}`")
                gr.Markdown(f"**STT Model:** `{config.GROQ_WHISPER_MODEL}`")

        # ── Right column: chat interface ────────────────────────────────────
        with gr.Column(scale=2):
            gr.Markdown("## 💬 Conversation")
            chatbot = gr.Chatbot(height=450, elem_id="chatbot", label="Chat")
            with gr.Row():
                user_input = gr.Textbox(
                    placeholder="Type a message from Phone B…",
                    show_label=False,
                    scale=4,
                )
                send_btn = gr.Button("Send", elem_id="send-btn", scale=1)
            clear_btn = gr.Button("Clear Conversation", elem_id="clear-btn")

    # ── Event handlers ───────────────────────────────────────────────────────
    adb_btn.click(fn=connect_adb, outputs=adb_status)

    bt_btn.click(fn=connect_bluetooth, inputs=mac_input, outputs=bt_status)

    disc_btn.click(fn=disconnect_all, outputs=bt_status)

    send_btn.click(
        fn=process_message,
        inputs=[user_input, chatbot],
        outputs=[chatbot, user_input],
    )

    user_input.submit(
        fn=process_message,
        inputs=[user_input, chatbot],
        outputs=[chatbot, user_input],
    )

    clear_btn.click(
        fn=lambda: ([], ""),
        outputs=[chatbot, user_input],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
