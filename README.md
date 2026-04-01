# TradeEngage Backend

FastAPI backend that acts as a secure proxy between the React Native mobile app and the **Gemini Multimodal Live API**, enabling real-time voice-driven job-referral extraction for field service technicians.

---

## Architecture

```
Mobile App ──WebSocket──▶ FastAPI ──Live API──▶ Gemini
                              │
                              ├─ /ws/audio        (real-time streaming)
                              └─ /api/offline-upload (store & forward)
```

### Key Components

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — health check, WebSocket endpoint, offline upload REST endpoint |
| `gemini_service.py` | Manages the Gemini Live session — sends audio, receives tool calls & audio responses |
| `Dockerfile` | Python 3.11-slim container running Uvicorn |
| `docker-compose.yml` | One-command local deployment with hot-reload |

### How It Works

1. **WebSocket `/ws/audio`** — The mobile app connects and streams base64-encoded 16 kHz PCM audio chunks. The backend immediately forwards them to the Gemini Live API.
2. **Tool Calling** — Gemini is instructed to invoke `update_job_details` whenever it identifies entities (name, phone, address, job description, service sector, approval). The structured JSON is relayed back to the app in real time.
3. **Audio Responses** — Gemini's spoken replies are base64-encoded and sent back over the same WebSocket for the app to play.
4. **Offline Upload `/api/offline-upload`** — When the technician was offline, the app submits the recorded audio + metadata via a multipart POST for asynchronous extraction.

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

The backend will be available at `http://localhost:8000` and the WebSocket at `ws://localhost:8000/ws/audio`.

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

Health check.

**Response:** `{"status": "ok", "service": "TradeEngage Backend"}`

### `WS /ws/audio`

Real-time bidirectional audio streaming.

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

Multipart form upload for offline-captured recordings.

| Field | Type | Description |
|---|---|---|
| `audio` | File | Audio recording file |
| `metadata` | String (JSON) | Any locally captured job metadata |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Google Gemini API key |

---

## License

Proprietary — all rights reserved.
