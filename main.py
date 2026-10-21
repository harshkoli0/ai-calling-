"""
main.py — GharSetu Realty Real Estate Voice Bot  (Production v4)

ARCHITECTURE — STT → LLM stream → TTS pipeline
══════════════════════════════════════════════════════════════════

  Twilio audio  ──►  Deepgram STT  ──►  transcript_q
                                              │
                                         convo_loop
                                              │
                             ┌── intent classifier (instant) ──┐
                             │  OR                              │
                             └── chat_stream() ─── sentences ──┘
                                                       │
                                                 sarvam_tts()  ← parallel
                                                       │
                                               Twilio chunks
                                           (40ms each, barge-in)

v4 FIXES:
  1. TIMEOUT REMOVED — no more "timed out waiting for first sentence".
     convo_loop waits on the queue with no hard cut-off; the generator
     always ends via sentinel None, never via TimeoutError.
  2. STREAMING SAFETY — broken partial tokens can no longer reach TTS.
     The sentence splitter checks Devanagari codepoint boundaries before
     yielding any chunk.
  3. INTENT CLASSIFIER — greetings, acknowledgements, and common intents
     handled instantly before LLM is called (zero latency path).
  4. BUDGET FILLER removed — no more spurious "Haan ji, ek second" before
     the actual response is ready.
  5. BARGE-IN improved — clear sent to Twilio immediately on detection,
     pending TTS tasks cancelled before they waste API quota.

v4.1 FIXES:
  6. GREETING TIMEOUT raised 5s → 12s — Sarvam cold-start latency was
     causing a silent asyncio.TimeoutError, greeting_mulaw = None, and a
     redundant second TTS fetch that raced against Twilio's stop event.
  7. EXCEPTION LOGGING — greeting catch now prints type(e).__name__ so
     TimeoutError / ConnectError are visible in logs instead of blank lines.
  8. GREETING GUARD — if greeting_mulaw is still None after the wait,
     speak() is called without prebuilt audio only as a last-resort fallback
     with a clear log warning instead of silently re-fetching.
"""

import asyncio
import audioop
import base64
import json
import os
import sys
import uuid
import wave
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
import websockets
from twilio.rest import Client

from agent_graph import ConversationSession, clean_for_tts, warm_up_llm

# ── env loading ───────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
for _env_path in [
    _HERE / "_env",
    Path.cwd() / "_env",
    _HERE / ".env",
    Path.cwd() / ".env",
]:
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=True)
        print(f"[env] Loaded: {_env_path}")
        break
else:
    load_dotenv(override=True)


# ── Tuning ────────────────────────────────────────────────────────────────────
VAD_ENERGY_THRESHOLD   = 180   # RMS barge-in threshold (150–280)
MIN_TRANSCRIPT_LEN     = 2     # Ignore transcripts shorter than this
GREETING_TTS_TIMEOUT   = 12.0  # FIX v4.1: raised from 5s — Sarvam cold-start can take 6–10s


# ═══════════════════════════════════════════════════════════════
# SARVAM TTS
# ═══════════════════════════════════════════════════════════════

SARVAM_STREAM_URL = "https://api.sarvam.ai/text-to-speech/stream"

# One shared HTTP client for every TTS request — reusing the connection skips
# a fresh TLS handshake per sentence (~0.7s saved each time).
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=120),
        )
    return _http_client


async def sarvam_tts_stream(text: str) -> AsyncIterator[bytes]:
    """
    Stream TTS from Sarvam AI as raw 8kHz mu-law chunks, ready for Twilio.
    First audio arrives in ~0.3s instead of waiting 1–2.5s for the whole clip.
    """
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise RuntimeError("SARVAM_API_KEY not set")

    text = clean_for_tts(text)
    if not text:
        raise ValueError("TTS text empty after cleaning")

    payload = {
        "text":                 text,
        "target_language_code": "hi-IN",
        "speaker":              "priya",
        "model":                "bulbul:v3",
        "pace":                 1.05,
        "speech_sample_rate":   8000,
        "output_audio_codec":   "mulaw",
        "enable_preprocessing": True,
        "temperature":          0.5,
    }

    print(f"[Sarvam] TTS: {text[:80]}")
    async with _get_http_client().stream(
        "POST",
        SARVAM_STREAM_URL,
        headers={"api-subscription-key": api_key},
        json=payload,
    ) as r:
        if r.status_code != 200:
            body = (await r.aread())[:300]
            raise RuntimeError(f"Sarvam HTTP {r.status_code}: {body!r}")
        async for chunk in r.aiter_bytes():
            if chunk:
                yield chunk


async def sarvam_tts(text: str) -> bytes:
    """Fetch the complete TTS clip as mu-law bytes (greeting pre-fetch, tests)."""
    parts = [chunk async for chunk in sarvam_tts_stream(text)]
    mulaw = b"".join(parts)
    print(f"[Sarvam] {len(mulaw)} bytes mulaw")
    return mulaw


def prefetch_tts(text: str) -> tuple[asyncio.Queue, asyncio.Task]:
    """
    Start streaming TTS for `text` in the background right away.
    Returns (chunk_queue, task); the queue ends with a None sentinel,
    also on error, so a reader never hangs.
    """
    q: asyncio.Queue = asyncio.Queue()

    async def _run():
        try:
            async for chunk in sarvam_tts_stream(text):
                q.put_nowait(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[TTS] fetch failed: {type(e).__name__}: {e}")
        finally:
            q.put_nowait(None)

    return q, asyncio.create_task(_run())


async def _queue_chunks(q: asyncio.Queue) -> AsyncIterator[bytes]:
    while True:
        chunk = await q.get()
        if chunk is None:
            return
        yield chunk


# ═══════════════════════════════════════════════════════════════
# SEND TTS TO TWILIO  (40ms chunk loop with barge-in)
# ═══════════════════════════════════════════════════════════════

async def send_tts(
    text: str,
    ws,
    stream_sid: str,
    bot_speaking_evt: asyncio.Event = None,
    interrupt_evt: asyncio.Event = None,
    prebuilt_audio: bytes = None,
    audio_stream: AsyncIterator[bytes] = None,
) -> str:
    """
    Stream mu-law audio to Twilio in 20ms chunks, starting as soon as the
    first TTS bytes arrive. Audio source, in priority order: prebuilt_audio,
    audio_stream, else a fresh Sarvam stream for `text`.
    Returns: "interrupted" | "" (error) | mark_label (done)
    """
    if prebuilt_audio is not None:
        async def _prebuilt():
            yield prebuilt_audio
        source = _prebuilt()
    elif audio_stream is not None:
        source = audio_stream
    else:
        source = sarvam_tts_stream(text)

    CHUNK       = 160   # 20ms @ 8kHz mu-law — tighter barge-in
    sent        = 0
    interrupted = False

    try:
        async for data in source:
            if bot_speaking_evt and not bot_speaking_evt.is_set():
                bot_speaking_evt.set()
            for i in range(0, len(data), CHUNK):
                if interrupt_evt and interrupt_evt.is_set():
                    print("[TTS] barge-in — stopping playback")
                    interrupted = True
                    break
                await ws.send(
                    json.dumps({
                        "event":     "media",
                        "streamSid": stream_sid,
                        "media":     {"payload": base64.b64encode(data[i : i + CHUNK]).decode()},
                    })
                )
                sent += len(data[i : i + CHUNK])
                await asyncio.sleep(0)  # yield to VAD / DG receiver
            if interrupted:
                break
    except Exception as e:
        print(f"[TTS] stream/send error: {type(e).__name__}: {e}")
        if bot_speaking_evt:
            bot_speaking_evt.clear()
        return ""

    if bot_speaking_evt:
        bot_speaking_evt.clear()

    if sent == 0 and not interrupted:
        return ""

    if interrupted:
        try:
            await ws.send(
                json.dumps({"event": "clear", "streamSid": stream_sid})
            )
            print("[TTS] Twilio buffer cleared after barge-in")
        except Exception:
            pass
        return "interrupted"

    mark_label = f"done_{uuid.uuid4().hex[:8]}"
    try:
        await ws.send(
            json.dumps({
                "event":     "mark",
                "streamSid": stream_sid,
                "mark":      {"name": mark_label},
            })
        )
    except Exception as e:
        print(f"[TTS] mark error: {e}")
        return ""

    print(f"[TTS] done {sent}b mark={mark_label}")
    return mark_label


# ═══════════════════════════════════════════════════════════════
# DEEPGRAM STT
# ═══════════════════════════════════════════════════════════════

def _build_deepgram_url() -> str:
    """
    Build Deepgram WS URL from config.json.
    Keyterms are injected as repeated &keyterm= params so ASR
    boosts confidence on Indore area names, Hindi budget words, etc.
    """
    import urllib.parse
    _cfg_path = Path(__file__).parent / "config.json"
    try:
        _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
        stt = _cfg.get("deepgram_stt", {})
    except Exception:
        stt = {}

    base = "wss://api.deepgram.com/v1/listen"
    params = [
        ("model",            stt.get("model", "nova-3")),
        ("language",         stt.get("language", "multi")),
        ("encoding",         stt.get("encoding", "mulaw")),
        ("sample_rate",      str(stt.get("sample_rate", 8000))),
        ("channels",         str(stt.get("channels", 1))),
        ("interim_results",  "true" if stt.get("interim_results", True) else "false"),
        ("endpointing",      str(stt.get("endpointing", 100))),
        ("utterance_end_ms", str(stt.get("utterance_end_ms", 1000))),
        ("smart_format",     "true" if stt.get("smart_format", True) else "false"),
    ]
    # keyterms cause HTTP 400 with language=multi — skip them
    language = stt.get("language", "multi")
    if language != "multi":
        for term in stt.get("keyterms", []):
            params.append(("keyterm", term))
        print(f"[DG] Keyterms injected: {len(stt.get('keyterms', []))}")
    else:
        print("[DG] Keyterms SKIPPED — incompatible with language=multi")

    url = base + "?" + urllib.parse.urlencode(params)
    print(f"[DG] Connecting: {url[:100]}...")
    return url


DEEPGRAM_URL = _build_deepgram_url()


def dg_connect():
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_API_KEY not set")
    try:
        major = int(websockets.__version__.split(".")[0])
    except Exception:
        major = 99
    hdr = "additional_headers" if major >= 13 else "extra_headers"
    return websockets.connect(
        DEEPGRAM_URL, **{hdr: {"Authorization": f"Token {api_key}"}}
    )


# ═══════════════════════════════════════════════════════════════
# CALL HANDLER
# ═══════════════════════════════════════════════════════════════

async def twilio_handler(twilio_ws, phone: str = "unknown"):
    print(f"[Handler] New call — phone={phone if phone != 'unknown' else 'resolving...'}")

    audio_q      = asyncio.Queue()
    sid_q        = asyncio.Queue()
    transcript_q = asyncio.Queue()

    bot_speaking   = asyncio.Event()  # set while TTS chunks are streaming
    interrupt_flag = asyncio.Event()  # set on barge-in detection

    barge_buffer: list[str] = []

    session          = ConversationSession(phone=phone)
    call_ended_event = asyncio.Event()

    # Pre-fetch greeting TTS immediately — before streamSid arrives
    greeting_text       = session.get_greeting()
    greeting_audio_task = asyncio.create_task(sarvam_tts(greeting_text))
    warm_up_task        = asyncio.create_task(warm_up_llm())  # Groq connection ready before user speaks
    print("[Handler] Pre-fetching greeting TTS...")

    active_llm_task: asyncio.Task | None = None

    # ─────────────────────────────────────────────────────────────────────
    # TWILIO RECV
    # ─────────────────────────────────────────────────────────────────────
    async def twilio_recv():
        nonlocal phone
        async for raw in twilio_ws:
            try:
                msg   = json.loads(raw)
                event = msg.get("event")

                if event == "connected":
                    print("[Twilio] connected")

                elif event == "start":
                    start_data = msg["start"]
                    stream_sid = start_data["streamSid"]

                    # ── Phone resolution (best-effort, multiple sources) ──
                    if phone == "unknown":
                        cp = start_data.get("customParameters", {})
                        resolved = (
                            cp.get("phone")
                            or cp.get("to")
                            or cp.get("caller")
                            or start_data.get("from")
                            or start_data.get("to")
                            or start_data.get("callSid")
                        )
                        if resolved:
                            phone = resolved.strip()
                            session.phone = phone
                            print(f"[Twilio] caller identified — {phone}")

                    print(f"[Twilio] start — sid={stream_sid}")
                    sid_q.put_nowait(stream_sid)

                elif event == "media":
                    if msg["media"].get("track", "inbound") == "inbound":
                        chunk = base64.b64decode(msg["media"]["payload"])
                        audio_q.put_nowait(chunk)

                        # VAD — instant energy barge-in detection
                        if bot_speaking.is_set() and not interrupt_flag.is_set():
                            try:
                                pcm = audioop.ulaw2lin(chunk, 2)
                                rms = audioop.rms(pcm, 2)
                                if rms > VAD_ENERGY_THRESHOLD:
                                    print(f"[VAD] rms={rms} — barge-in detected")
                                    interrupt_flag.set()
                            except Exception:
                                pass

                elif event == "stop":
                    print("[Twilio] stop")
                    call_ended_event.set()
                    break

            except Exception as e:
                print(f"[Twilio recv error] {e}")

    # ─────────────────────────────────────────────────────────────────────
    # DEEPGRAM SENDER / RECEIVER
    # ─────────────────────────────────────────────────────────────────────
    async def dg_sender(dg_ws):
        while True:
            chunk = await audio_q.get()
            if call_ended_event.is_set():
                break
            try:
                await dg_ws.send(chunk)
            except Exception as e:
                print(f"[DG sender] {e}")
                break

    async def dg_receiver(dg_ws):
        async for raw in dg_ws:
            try:
                data       = json.loads(raw)
                if data.get("type") != "Results":
                    continue
                alt        = data["channel"]["alternatives"][0]
                transcript = alt.get("transcript", "").strip()
                is_final   = data.get("is_final", False)
                speech_end = data.get("speech_final", False)
                if not transcript:
                    continue

                if bot_speaking.is_set():
                    # BARGE-IN PATH — buffer speech for after interrupt
                    if not interrupt_flag.is_set():
                        print(f"[Barge-in] DG confirmed: '{transcript}'")
                        interrupt_flag.set()
                    if not barge_buffer or len(transcript) > len(barge_buffer[-1]):
                        barge_buffer.append(transcript)
                else:
                    # NORMAL PATH — only push finals
                    if is_final or speech_end:
                        print(f"[USER] {transcript}")
                        transcript_q.put_nowait(transcript)

            except Exception as e:
                print(f"[DG receiver error] {e}")

    # ─────────────────────────────────────────────────────────────────────
    # SPEAK HELPER — plays one clip, handles barge-in
    # ─────────────────────────────────────────────────────────────────────
    async def speak(
        text: str, stream_sid: str, prebuilt: bytes = None
    ) -> str:
        nonlocal barge_buffer
        barge_buffer = []
        interrupt_flag.clear()

        result = await send_tts(
            text,
            twilio_ws,
            stream_sid,
            bot_speaking_evt=bot_speaking,
            interrupt_evt=interrupt_flag,
            prebuilt_audio=prebuilt,
        )

        if result == "interrupted" and barge_buffer:
            await asyncio.sleep(0.1)
            best = max(barge_buffer, key=len).strip()
            barge_buffer = []
            if best and len(best) > MIN_TRANSCRIPT_LEN:
                print(f"[Barge-in] queuing captured: '{best}'")
                transcript_q.put_nowait(best)

        return result

    # ─────────────────────────────────────────────────────────────────────
    # STREAMING SPEAK — parallel TTS pre-fetch for sentence stream
    # ─────────────────────────────────────────────────────────────────────
    async def speak_stream(sentence_gen, stream_sid: str) -> str:
        """
        Consume an async generator of sentences.
        Sentence 1 starts playing the moment its first audio bytes arrive;
        TTS for later sentences starts in the background as soon as the LLM
        yields them, so there is no gap between sentences.
        Returns "interrupted" | "done" | "error".
        """
        nonlocal barge_buffer
        barge_buffer = []
        interrupt_flag.clear()

        # (text, chunk_queue, tts_task) per sentence; None = no more sentences.
        # maxsize caps how far ahead we pre-fetch (saves TTS quota on barge-in).
        clips: asyncio.Queue = asyncio.Queue(maxsize=2)
        started: list[asyncio.Task] = []

        async def _producer():
            try:
                async for sentence in sentence_gen:
                    q, task = prefetch_tts(sentence)
                    started.append(task)
                    await clips.put((sentence, q, task))
            except Exception as e:
                print(f"[SpeakStream] sentence source error: {e}")
            finally:
                await clips.put(None)

        producer = asyncio.create_task(_producer())
        played_any = False
        result = ""

        try:
            while True:
                clip = await clips.get()
                if clip is None:
                    break
                text, q, _ = clip
                if interrupt_flag.is_set():
                    print("[SpeakStream] interrupt before play — aborting stream")
                    result = "interrupted"
                    break
                result = await send_tts(
                    text,
                    twilio_ws,
                    stream_sid,
                    bot_speaking_evt=bot_speaking,
                    interrupt_evt=interrupt_flag,
                    audio_stream=_queue_chunks(q),
                )
                if result == "interrupted":
                    break
                if result:
                    played_any = True
        finally:
            producer.cancel()
            for t in started:
                if not t.done():
                    t.cancel()

        if result == "interrupted":
            await asyncio.sleep(0.1)
            if barge_buffer:
                best = max(barge_buffer, key=len).strip()
                barge_buffer = []
                if best and len(best) > MIN_TRANSCRIPT_LEN:
                    print(f"[Barge-in] queuing: '{best}'")
                    transcript_q.put_nowait(best)
            return "interrupted"

        return "done" if played_any else "error"

    # ─────────────────────────────────────────────────────────────────────
    # CONVERSATION LOOP
    # ─────────────────────────────────────────────────────────────────────
    async def convo_loop():
        nonlocal active_llm_task

        try:
            stream_sid = await asyncio.wait_for(sid_q.get(), timeout=10.0)
        except asyncio.TimeoutError:
            print("[Conv] FATAL: streamSid never received")
            return

        # ── FIX v4.1: Greeting TTS wait ───────────────────────────────────
        # Raised timeout 5s → 12s.  Sarvam cold-start can easily take 6–10s.
        # Exception now logs type(e).__name__ so TimeoutError is visible.
        # If mulaw is still None we warn clearly and fall back to a live fetch
        # via speak() rather than silently passing None (which caused a silent
        # re-fetch that often raced against Twilio's stop event).
        print(f"[Conv] streamSid={stream_sid} — waiting for greeting TTS (timeout={GREETING_TTS_TIMEOUT}s)")
        greeting_mulaw = None
        try:
            greeting_mulaw = await asyncio.wait_for(
                greeting_audio_task, timeout=GREETING_TTS_TIMEOUT
            )
            print("[Conv] greeting TTS ready — playing")
        except asyncio.TimeoutError:
            print(f"[Conv] greeting TTS timeout after {GREETING_TTS_TIMEOUT}s — falling back to live fetch")
        except Exception as e:
            print(f"[Conv] greeting TTS failed: {type(e).__name__}: {e} — falling back to live fetch")

        # speak() handles greeting_mulaw=None gracefully by doing a live fetch
        await speak(greeting_text, stream_sid, prebuilt=greeting_mulaw)
        session.mark_greeted()

        import time as _time

        while not call_ended_event.is_set():
            # Wait for user utterance — no silence follow-ups
            try:
                user_text = await asyncio.wait_for(
                    transcript_q.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if call_ended_event.is_set():
                break

            # Ignore trivial noise
            cleaned = user_text.strip().lower().rstrip(".!?,;")
            if len(cleaned) <= MIN_TRANSCRIPT_LEN:
                continue

            # Cancel any stale LLM task
            if active_llm_task and not active_llm_task.done():
                print("[Conv] cancelling stale LLM task")
                active_llm_task.cancel()
                try:
                    await active_llm_task
                except (asyncio.CancelledError, Exception):
                    pass
                active_llm_task = None

            # Drain duplicate transcripts (take longest)
            await asyncio.sleep(0.02)
            latest = user_text
            while not transcript_q.empty():
                candidate = transcript_q.get_nowait()
                if len(candidate) >= len(latest):
                    latest = candidate
            user_text = latest

            print(f"[LLM] Processing: '{user_text}'")
            interrupt_flag.clear()

            # ── STREAMING PIPELINE ────────────────────────────────────
            sentence_q: asyncio.Queue = asyncio.Queue()

            async def _drain_gen():
                """Feed chat_stream sentences into sentence_q."""
                try:
                    async for sentence in session.chat_stream(user_text):
                        await sentence_q.put(sentence)
                except Exception as e:
                    print(f"[drain_gen error] {e}")
                finally:
                    await sentence_q.put(None)  # sentinel — always fires

            drain_task = asyncio.create_task(_drain_gen())
            active_llm_task = drain_task

            # ── Wait for first sentence (NO hard timeout) ─────────────
            # The generator always ends with a None sentinel, so this
            # get() will eventually return. No TimeoutError possible.
            first_sentence = await sentence_q.get()
            active_llm_task = None

            if call_ended_event.is_set():
                drain_task.cancel()
                break

            if interrupt_flag.is_set():
                print("[Conv] skipping stale reply — user already speaking")
                drain_task.cancel()
                interrupt_flag.clear()
                continue

            if first_sentence is None:
                # Generator produced nothing — wait for user to speak again
                drain_task.cancel()
                continue

            # Build async generator from queue contents + drain_task
            async def _queued_sentences():
                yield first_sentence
                while True:
                    try:
                        item = sentence_q.get_nowait()
                        if item is None:
                            break
                        yield item
                    except asyncio.QueueEmpty:
                        item = await sentence_q.get()
                        if item is None:
                            break
                        yield item

            # Always stream: the first sentence plays immediately while the
            # LLM keeps producing the rest (the old single-sentence shortcut
            # cancelled the LLM and cut replies off after sentence one).
            result = await speak_stream(_queued_sentences(), stream_sid)
            if result == "interrupted":
                print("[Conv] stream interrupted — captured speech queued")

            if not drain_task.done():
                drain_task.cancel()

    # ─────────────────────────────────────────────────────────────────────
    # LAUNCH — run all coroutines concurrently
    # ─────────────────────────────────────────────────────────────────────
    try:
        async with dg_connect() as dg_ws:
            await asyncio.gather(
                twilio_recv(),
                dg_sender(dg_ws),
                dg_receiver(dg_ws),
                convo_loop(),
            )
    except Exception as e:
        print(f"[Handler error] {e}")
    finally:
        if active_llm_task and not active_llm_task.done():
            active_llm_task.cancel()
        if not greeting_audio_task.done():
            greeting_audio_task.cancel()
        print("[Handler] Call ended")


# ═══════════════════════════════════════════════════════════════
# TTS SMOKE TEST:  python main.py --test-tts "Namaste ji"
# ═══════════════════════════════════════════════════════════════

async def _test_tts(text: str):
    print(f"[Test] Input:   {text}")
    cleaned = clean_for_tts(text)
    print(f"[Test] Cleaned: {cleaned}")
    try:
        mulaw = await sarvam_tts(cleaned)
    except Exception as e:
        print(f"[Test] FAILED: {e}")
        return
    with wave.open("test_output.wav", "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(8000)
        wf.writeframes(mulaw)
    print(f"[Test] Saved {len(mulaw)} bytes → test_output.wav")


# ═══════════════════════════════════════════════════════════════
# OUTBOUND DIALLER
# ═══════════════════════════════════════════════════════════════

def make_call(to_number: str) -> str:
    import urllib.parse
    from xml.sax.saxutils import quoteattr
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    )
    ws_url = os.getenv("PUBLIC_WS_URL", "").strip()
    if ws_url:
        # Inline TwiML — no TwiML Bin to edit when the tunnel URL changes.
        # The called number reaches twilio_handler via customParameters.
        twiml = (
            f"<Response><Connect><Stream url={quoteattr(ws_url)}>"
            f"<Parameter name=\"phone\" value={quoteattr(to_number)} />"
            f"</Stream></Connect></Response>"
        )
        call = client.calls.create(
            twiml=twiml,
            to=to_number,
            from_=os.getenv("TWILIO_PHONE_NUMBER"),
        )
    else:
        base_url  = os.getenv("TWIML_BIN_URL", "")
        # Append the called number so our WebSocket handler can identify the caller
        sep       = "&" if "?" in base_url else "?"
        twiml_url = f"{base_url}{sep}phone={urllib.parse.quote(to_number)}"
        call = client.calls.create(
            url=twiml_url,
            to=to_number,
            from_=os.getenv("TWILIO_PHONE_NUMBER"),
        )
    print(f"[Twilio] SID={call.sid}  →  {to_number}")
    return call.sid


def _parse_phone_numbers() -> list:
    raw_multi  = os.getenv("MY_PHONE_NUMBERS", "").strip()
    raw_single = os.getenv("MY_PHONE_NUMBER", "").strip()
    if raw_multi:
        try:
            numbers = json.loads(raw_multi)
            if not isinstance(numbers, list):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            numbers = raw_multi.split(",")
        return [n.strip() for n in numbers if n.strip()]
    if raw_single:
        return [raw_single]
    return []


def make_calls(numbers: list) -> dict:
    import time as _time
    results = {}
    for i, number in enumerate(numbers):
        try:
            results[number] = make_call(number)
        except Exception as e:
            results[number] = f"ERROR: {e}"
        if i < len(numbers) - 1:
            _time.sleep(1.5)
    return results


async def _ws_dispatcher(websocket):
    import urllib.parse
    path   = getattr(websocket, "path", "") or ""
    params = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    # Try multiple param names Twilio might use
    phone = (
        params.get("phone", [None])[0]
        or params.get("From", [None])[0]
        or params.get("To", [None])[0]
        or params.get("CallSid", [None])[0]
        or "unknown"
    )
    if phone != "unknown":
        print(f"[Dispatcher] Caller from URL: {phone}")
    await twilio_handler(websocket, phone=phone)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    server = await websockets.serve(_ws_dispatcher, "0.0.0.0", 5000)
    print("\n[Main] WebSocket server ready on ws://0.0.0.0:5000\n")

    numbers = _parse_phone_numbers()
    if numbers:
        print(f"\n[Main] Auto-dialling {len(numbers)} number(s) from _env...")
        loop    = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, make_calls, numbers)
        for num, sid in results.items():
            status = "OK" if not str(sid).startswith("ERROR") else "FAIL"
            print(f"  [{status}] {num}  SID={sid}")
        print("\n[Main] Calls placed — waiting for Twilio WebSocket connections...\n")
    else:
        print("[Main] No MY_PHONE_NUMBER in _env — inbound-only mode.")
        print("[Main] Set MY_PHONE_NUMBER=+91XXXXXXXXXX in _env to auto-dial.\n")

    await asyncio.Future()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test-tts":
        asyncio.run(_test_tts(" ".join(sys.argv[2:])))
    else:
        asyncio.run(main())