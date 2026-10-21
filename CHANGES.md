# GharSetu Realty Voice Bot — Change Log

All changes made on **2026-10-20**.

---

## 1. Bot could not speak (Sarvam TTS broken)

**Problem:** Sarvam retired the `bulbul:v2` voice model and the `anushka` speaker.
Every TTS request failed with *"Model 'bulbul:v2' has been deprecated"*, so the
call connected but stayed silent.

**Fix:** switched to model `bulbul:v3` with speaker `priya` (`main.py`, `config.json`).

---

## 2. Rebrand: RainInfra → GharSetu Realty

Every "RainInfra" was replaced with **GharSetu Realty** (*ghar* = home, *setu* = bridge):
the greeting, the goodbye lines, the system prompt and the Deepgram keyterms
(`agent_graph.py`, `estate_functions.py`, `main.py`, `config.json`).

---

## 3. MySQL removed — JSON storage only

- Deleted `db.py`. No other file imported it, so MySQL was never actually used.
- Removed the `MYSQL_*` lines from `.env`.
- Customer data is stored in `customer_memory.json` (unchanged).

---

## 4. Calls connected but disconnected ("this call may be monitored or recorded")

**Problem:** Twilio could not reach the bot (Twilio error **31920 — WebSocket
handshake error**). The bot runs on this PC at `ws://localhost:5000`, and no
public tunnel was running.

**Fix:**
- Installed **cloudflared** (free, no account needed) at `C:\Users\hkoli\tools\cloudflared.exe`.
- `make_call()` in `main.py` now sends the call instructions (TwiML) inline, using the
  new `.env` setting `PUBLIC_WS_URL`. The TwiML Bin is no longer needed, and the
  "monitored and recorded" message is gone. If `PUBLIC_WS_URL` is removed, it goes
  back to using `TWIML_BIN_URL`.
- Fixed `agent_graph.py` so it also loads `.env` (before, it only looked for `_env`
  and crashed when imported on its own, e.g. from `test.py`).

---

## 5. Slow / missing replies — speed fixes

### Measured before vs after (time from user finishing speaking → bot's first audio)

| Turn type                        | Before                        | After      |
|----------------------------------|-------------------------------|------------|
| Normal question                  | **no reply** (LLM crashed)    | ~0.6–0.8 s |
| Property search (tool)           | 22–74 s                       | ~1.7–1.9 s |
| First reply of the call          | —                             | ~1 s (warm-up) |

### What was causing it, and the fix

| # | Cause | Fix | File |
|---|-------|-----|------|
| a | Groq retired `llama-3.3-70b-versatile`, so **every LLM reply failed** (404). Only the canned quick replies worked. | Switched to `qwen/qwen3.8-27b` (fastest available, ~0.13 s to first word), with `reasoning_effort="none"` so it doesn't "think" first. | `agent_graph.py` |
| b | **Groq free-tier rate limit:** 8,000 tokens per minute per model. Each call sent ~2,300 tokens, so after 3–4 turns Groq made the bot wait up to 60 s. | **Automatic model fallback:** qwen → `gpt-oss-20b` → `gpt-oss-120b`. Each model has its own limit, so on a rate limit the bot switches instantly instead of waiting. | `agent_graph.py` |
| c | Tool descriptions (~840 tokens) were sent on every call. | Tools are only sent once purpose + location are known, or for visit/confirm/farewell turns. Removed two placeholder tools that only returned "not available". | `agent_graph.py` |
| d | Up to 20 old messages were sent every turn. | Send only the last 6 messages (the saved customer profile carries the rest). | `agent_graph.py` |
| e | The "tool path" used LangGraph `invoke` (waits for the whole reply, no streaming) plus a `MemorySaver` that duplicated the conversation every turn, so the prompt kept growing. Tools were never actually connected to the LLM (no `bind_tools`), so the bot **made up property listings**. | Removed LangGraph. A single streaming path now handles tools inline: stream → if the model asks for a tool, run it → stream the answer. **Property search now returns real listings** from `estate_functions.py`. | `agent_graph.py` |
| f | Sarvam TTS waited for the **whole audio clip** (1–2.5 s per sentence). | Switched to Sarvam's **streaming** endpoint (`/text-to-speech/stream`, raw mu-law): first audio arrives in ~0.3 s and plays while the rest is generated. | `main.py` |
| g | A new HTTPS connection to Sarvam for every sentence (~0.7 s TLS handshake each time). | One shared, reused HTTP connection. | `main.py` |
| h | `speak_stream` waited for the LLM to finish sentence 2 before playing sentence 1. A "single sentence" shortcut also **cancelled the LLM and cut replies off** after the first sentence. | Rewritten: sentence 1 plays as soon as its audio starts arriving, and later sentences' audio is prepared in the background while earlier ones play. | `main.py` |
| i | The first reply of a call paid for opening the Groq connection. | `warm_up_llm()` opens the Groq connection while the greeting plays. | `main.py`, `agent_graph.py` |
| j | Replies were long (one was 43 s of speech) — slow on a phone call. | Prompt now says max 2 short sentences, and 2 property options instead of 3–4. | `agent_graph.py` |

### Small bug fix
- `gpt-oss` writes special narrow spaces (`50\u202flakh`), which made TTS say "abhipachaas".
  `clean_for_tts()` now turns them into normal spaces.

---

## How to run

1. Start the tunnel and leave it running:
   ```
   C:\Users\hkoli\tools\cloudflared.exe tunnel --url http://localhost:5000
   ```
2. Copy the `https://xxxx.trycloudflare.com` address it prints into `.env`, changing `https` to `wss`:
   ```
   PUBLIC_WS_URL=wss://xxxx.trycloudflare.com
   ```
   (The free tunnel gets a new address every time it starts.)
3. Start the bot (it auto-dials `MY_PHONE_NUMBER`):
   ```
   myenv\Scripts\python.exe main.py
   ```

Voice-only smoke test (no call): `myenv\Scripts\python.exe main.py --test-tts "Namaste ji"`

## Known limits / next steps

- **Groq free tier** (8,000 tokens/min per model) is still the main limit on a long,
  fast-paced call. The model fallback roughly triples capacity, but a Groq
  **Developer plan** removes the problem completely.
- The quick tunnel address changes on every restart. A named Cloudflare tunnel
  (free account) or a paid ngrok domain gives a fixed address.
