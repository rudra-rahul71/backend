# TradeEngage Backend

FastAPI backend that acts as a secure proxy between the React Native Web app and the **Gemini Multimodal Live / Batch APIs**, enabling real-time voice-driven job-referral extraction for field service technicians.

---

## Architecture

```text
Web App Client ──WebSocket──▶ FastAPI ──Live API──▶ Gemini (3.1-flash-live-preview)
                               │
                               ├─ /ws/audio        (real-time streaming)
                               └─ /api/offline-upload (store & forward batch via gemini-2.5-flash)
```

### Key Components

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — health check, WebSocket endpoint, offline upload REST endpoint |
| `gemini_service.py` | Manages the Gemini session — sends inline audio chunk/blob payloads, receives async tool calls |
| `Dockerfile` | Python 3.11-slim container running Uvicorn |
| `docker-compose.yml` | One-command local deployment with unbuffered hot-reload logs |
| `.env` | Local environment variables |

### How It Works

1. **WebSocket `/ws/audio`** — The web app connects and streams base64-encoded PCM audio chunks. The backend immediately forwards them to the **Gemini Live API** using the `google-genai` package SDK.
2. **Tool Calling** — Gemini is instructed to invoke `update_job_details` whenever it identifies entities. The structured JSON is relayed back to the web app in real time for UI updates.
3. **Audio Responses** — Gemini's spoken replies are base64-encoded and sent back over the same WebSocket for the web app to play back.
4. **Offline Upload `/api/offline-upload`** — When the technician is working off-grid, the app queues their checklist. Later, the app synchronizes recordings here, where the **Gemini Batch API** parses the inline bytes synchronously.

---

## Getting Started

### Prerequisites

- **Docker & Docker Compose** (recommended)
- _or_ Python 3.11+ with pip
- A [Gemini API Key](https://aistudio.google.com/app/apikey)

### Quick Start (Docker)

```bash
# 1. Copy the example env and add your API key
cp .env.example .env
# Edit .env and insert your GEMINI_API_KEY

# 2. Start the service
docker compose up -d

# 3. Verify
curl http://localhost:8000/
# → {"status":"ok","service":"TradeEngage Backend"}
```

The backend is fully transparent in its console output inside Docker. The API is hosted at `http://localhost:8000` and the WebSocket at `ws://localhost:8000/ws/audio`.

### Local Development (without Docker)

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env and set your key
cp .env.example .env

# Run the server with hot-reload
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Reference

### `GET /`

Health check endpoint.

**Response:** `{"status": "ok", "service": "TradeEngage Backend"}`

### `WS /ws/audio`

Real-time bidirectional audio streaming for Live Interaction.

**Client → Server messages:**
```json
{ "type": "audio_chunk", "data": "<base64 PCM audio>" }
{ "type": "stop" }
```

**Server → Client messages:**
```json
{ "type": "tool_call", "function": "update_job_details", "args": { ... } }
{ "type": "audio_response", "data": "<base64 audio>", "mime_type": "audio/pcm;rate=24000" }
{ "type": "text_response", "text": "..." }
{ "type": "turn_complete" }
```

### `POST /api/offline-upload`

Multipart form upload for offline-captured recordings to be parsed collectively via `generate_content`.

| Field | Type | Description |
|---|---|---|
| `audio` | File | Audio recording file blob |
| `metadata` | String (JSON) | Prior partially gathered checklist data |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Google Gemini API key |
