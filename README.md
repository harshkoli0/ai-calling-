# GharSetu Realty — AI Voice Calling Bot

An AI phone agent for a real-estate business in Indore. It places (or answers) phone
calls through Twilio and talks to customers in Hindi / Hinglish in real time: it
finds out whether they want to buy, sell or rent, captures their name, budget,
preferred location and property type, searches matching listings, and can schedule
a site visit.

## How it works

```
Twilio call audio ──► Deepgram STT ──► Groq LLM (streamed) ──► Sarvam TTS ──► back to caller
                                         │
                                  estate_functions.py
                         (property search, visits, customer memory)
```

- **Speech-to-text:** Deepgram `nova-3` (multilingual, with real-estate and Indore
  locality keyterms)
- **LLM:** Groq `llama-3.1-8b-instant` via LangChain, with tool calling and a
  fallback model on rate limits
- **Text-to-speech:** Sarvam `bulbul:v3`, speaker `priya`, Hindi
- **Telephony:** Twilio Media Streams over a WebSocket
- **Latency:** sentences are streamed to TTS as soon as they're ready, common
  intents are answered without calling the LLM, and the caller can interrupt
  (barge-in). Typical first-audio time is about 0.6–0.8 s.

## Project files

| File | Purpose |
|------|---------|
| `main.py` | WebSocket server, Twilio handler, Deepgram + Sarvam pipeline, outbound dialler |
| `agent_graph.py` | Conversation brain: system prompt, intent classifier, budget parser, LLM streaming |
| `estate_functions.py` | Property listings and tools: search, details, visits, saving customers |
| `config.json` | STT / TTS / LLM / VAD / conversation settings |
| `CHANGES.md` | Change log |
| `.env.example` | Environment variables you need to set |

## Setup

Requires **Python 3.12** (the `audioop` module was removed in 3.13).

```bash
python -m venv myenv
myenv\Scripts\activate          # Windows  (source myenv/bin/activate on macOS/Linux)
pip install python-dotenv httpx websockets twilio langchain-core langchain-groq
```

Copy `.env.example` to `.env` and fill it in:

| Variable | What it is |
|----------|------------|
| `DEEPGRAM_API_KEY` | Deepgram key for speech-to-text |
| `GROQ_API_KEY` | Groq key for the LLM |
| `SARVAM_API_KEY` | Sarvam key for text-to-speech |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Twilio credentials |
| `TWILIO_PHONE_NUMBER` | Your Twilio number (caller ID) |
| `PUBLIC_WS_URL` | Public `wss://` URL that forwards to `localhost:5000` |
| `MY_PHONE_NUMBER` | Number to auto-dial on startup (or `MY_PHONE_NUMBERS` as a list) |
| `TWIML_BIN_URL` | Optional fallback if `PUBLIC_WS_URL` isn't set |
| `ELEVENLABS_*` | Optional, not used by the current Sarvam TTS setup |

## Running

1. Expose the local WebSocket server so Twilio can reach it, e.g. with
   [cloudflared](https://github.com/cloudflare/cloudflared):

   ```bash
   cloudflared tunnel --url http://localhost:5000
   ```

   Put the generated URL in `.env` as `PUBLIC_WS_URL=wss://<your-subdomain>.trycloudflare.com`.

2. Start the bot:

   ```bash
   python main.py
   ```

   It starts the WebSocket server on port 5000 and dials every number in
   `MY_PHONE_NUMBER` / `MY_PHONE_NUMBERS`. With no number set, it waits for inbound calls.

3. Test only the voice:

   ```bash
   python main.py --test-tts "Namaste, main GharSetu Realty se Priya bol rahi hoon"
   ```

Customer details collected on calls are saved to `customer_memory.json`. That file
is gitignored because it contains phone numbers.
