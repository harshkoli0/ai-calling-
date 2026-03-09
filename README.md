# 📞 AI Calling Agent

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Groq](https://img.shields.io/badge/LLM-Groq%20llama3-orange)
![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-green)
![Gradio](https://img.shields.io/badge/UI-Gradio-purple)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

An AI-powered phone relay system where an Android phone acts as a Bluetooth–USB bridge, letting a laptop AI agent converse with a remote caller in real time.

---

## 🏗️ Architecture

```
Phone B 🗣️
   ↕ (Bluetooth Audio)
Phone A 📱 (USB tethered / ADB connected to Laptop)
   ↕ (USB / ADB bridge)
Laptop 💻
   └─ LangGraph Agent (Groq LLM)
      ├─ Speech-to-Text  (Groq Whisper large-v3)
      ├─ LLM Reasoning   (Groq llama3-8b-8192)
      └─ Text-to-Speech  → back to Phone B via Bluetooth
```

---

## ✨ Features

- 🔗 **ADB bridge** — connects to Phone A over USB
- 📡 **Bluetooth bridge** — relays audio to/from Phone B
- 🤖 **LangGraph stateful agent** — maintains conversation context
- ⚡ **Groq LLM** — fast, free-tier inference (llama3-8b-8192)
- 🎙️ **Groq Whisper** — speech-to-text transcription
- 🔊 **pyttsx3 TTS** — converts AI replies to speech
- 🖥️ **Gradio UI** — clean web interface for monitoring
- 🟡 **Demo mode** — works without real hardware out of the box

---

## 📋 Prerequisites

- Python 3.10+
- Android Debug Bridge (ADB) installed and in `PATH`
- Phone A paired with Phone B via Bluetooth
- (Optional) Free Groq API key for live inference

---

## 🚀 Installation

```bash
git clone https://github.com/harshkoli0/ai-calling-
cd ai-calling-
pip install -r requirements.txt
```

---

## 🔑 Get a Free Groq API Key

1. Visit <https://console.groq.com>
2. Sign up / log in
3. Go to **API Keys** → **Create API Key**
4. Copy the key into your `.env` file

---

## 🔧 ADB Setup

1. Enable **Developer Options** on Phone A
2. Enable **USB Debugging** in Developer Options
3. Connect Phone A to the laptop via USB
4. Run `adb devices` to confirm the device is listed

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `GROQ_API_KEY` | Your Groq API key | *(required for live mode)* |
| `PHONE_B_BLUETOOTH_MAC` | Bluetooth MAC of Phone B | `XX:XX:XX:XX:XX:XX` |
| `BLUETOOTH_PORT` | RFCOMM channel | `1` |
| `ADB_DEVICE_SERIAL` | ADB serial of Phone A | *(auto-detect)* |
| `DEMO_MODE` | `true` to run without hardware | `true` |

---

## ▶️ Running

```bash
python main.py
```

Open your browser at <http://localhost:7860>.

---

## 🟡 Demo Mode

When `DEMO_MODE=true` (the default):

- ADB and Bluetooth connections are **simulated** — no real hardware needed.
- STT returns a fixed demo sentence instead of calling Whisper.
- TTS prints the AI reply to the console instead of generating audio.
- The Groq LLM is still called (requires a valid `GROQ_API_KEY`).

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---|---|
| `adb: command not found` | Install ADB: `sudo apt install adb` (Linux) or use Android SDK |
| Bluetooth connection fails | Pair the phones first; confirm the correct MAC and RFCOMM port |
| Groq API errors | Check your `GROQ_API_KEY` in `.env`; verify quota at console.groq.com |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| Port 7860 in use | Set `server_port` in `main.py` or kill the conflicting process |

---

## 📁 Folder Structure

```
ai-calling-/
├── agent/
│   ├── __init__.py
│   ├── graph.py        # LangGraph stateful agent
│   ├── prompts.py      # System prompt
│   └── tools.py        # LangChain tools
├── audio/
│   ├── __init__.py
│   ├── stt.py          # Speech-to-text (Groq Whisper)
│   └── tts.py          # Text-to-speech (pyttsx3)
├── bridge/
│   ├── __init__.py
│   ├── adb_bridge.py   # ADB USB bridge
│   └── bluetooth_bridge.py  # Bluetooth RFCOMM bridge
├── .env.example        # Environment variable template
├── config.py           # Centralised configuration
├── main.py             # Entry point + Gradio UI
├── requirements.txt    # Python dependencies
└── README.md
```
