import config


def transcribe_audio(audio_bytes: bytes) -> str:
    """Convert raw audio bytes to text using Groq Whisper (or demo stub)."""
    if config.DEMO_MODE:
        return "Hello, this is a test message from Phone B."

    try:
        import io
        from groq import Groq

        client = Groq(api_key=config.GROQ_API_KEY)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.wav"

        transcription = client.audio.transcriptions.create(
            model=config.GROQ_WHISPER_MODEL,
            file=audio_file,
        )
        return transcription.text.strip()
    except Exception as e:
        print(f"[STT] Transcription error: {e}")
        return ""
