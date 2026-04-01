import os
import io
import json
import logging
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from gemini_service import handle_gemini_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TradeEngage Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "ok", "service": "TradeEngage Backend"}

@app.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time audio streaming to Gemini.
    The client will send JSON payloads containing base64 audio chunks.
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted.")
    
    # We use a queue to decouple the WebSocket receive loop from the Gemini send loop
    client_receive_queue = asyncio.Queue()
    
    # Start the Gemini session background task
    
    gemini_task = asyncio.create_task(handle_gemini_session(websocket, client_receive_queue))
    
    try:
        while True:
            # Receive data from frontend
            message = await websocket.receive_text()
            data = json.loads(message)
            logger.info(f"WS received message type: {data.get('type')}, queue size: {client_receive_queue.qsize()}")
            
            if data.get("type") == "audio_chunk":
                audio_data = data.get("data")
                logger.info(f"Enqueuing audio chunk, length: {len(audio_data) if audio_data else 0}")
                await client_receive_queue.put(audio_data)
            elif data.get("type") == "stop":
                logger.info("Client requested to stop.")
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        await client_receive_queue.put(None) # Signal shutdown
        gemini_task.cancel()

@app.post("/api/offline-upload")
async def offline_upload_endpoint(
    audio: UploadFile = File(...),
    metadata: str = Form(...)  # JSON string of any local state we already had
):
    """
    REST Endpoint for the Store & Forward architecture.
    Receives an audio file captured when the app was offline and processes it asynchronously.
    """
    # In a full-scale app, we would save this file to an S3 bucket and trigger a Celery task.
    # For this PoC, we will simulate receiving and logging the metadata.
    try:
        data = json.loads(metadata)
        logger.info(f"Received offline upload. File size: {audio.size} bytes. Metadata: {data}")
        # Here we would initialize a non-streaming Gemini call on `audio` to extract remaining data
        # and update the database with the finalized job.
        return {"status": "success", "message": "Offline payload received and queued for processing."}
    except Exception as e:
        logger.error(f"Offline processing error: {e}")
        raise HTTPException(status_code=400, detail="Invalid request format")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
