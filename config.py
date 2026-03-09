import os
from dotenv import load_dotenv

load_dotenv()

# Groq API
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama3-8b-8192"
GROQ_WHISPER_MODEL = "whisper-large-v3"

# Bluetooth
PHONE_B_BLUETOOTH_MAC = os.getenv("PHONE_B_BLUETOOTH_MAC", "XX:XX:XX:XX:XX:XX")
BLUETOOTH_PORT = int(os.getenv("BLUETOOTH_PORT", "1"))

# ADB
ADB_DEVICE_SERIAL = os.getenv("ADB_DEVICE_SERIAL", "")

# Demo mode — set to true by default so the app works without real hardware
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
