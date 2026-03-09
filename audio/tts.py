import config


def speak(text: str) -> bytes:
    """Convert text to speech audio bytes using pyttsx3 (or demo stub)."""
    if config.DEMO_MODE:
        print(f"[TTS DEMO] {text}")
        return b""

    try:
        import os
        import tempfile
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 150)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        engine.save_to_file(text, tmp_path)
        engine.runAndWait()

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        os.unlink(tmp_path)
        return audio_bytes
    except Exception as e:
        print(f"[TTS] Error generating speech: {e}")
        return b""
