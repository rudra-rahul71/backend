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

from gemini_service import handle_gemini_session, process_offline_audio, check_completeness

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TradeEngage Backend")

# Mock database (in-memory list for PoC)
mock_db: list[dict] = []

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

@app.post("/api/jobs")
async def create_job(job: dict):
    """
    REST endpoint to save a finalized job when the user is online.
    Validates required fields before persisting.
    """
    logger.info(f"Job submitted: {job}")
    
    is_complete, missing_fields = check_completeness(job)
    if not is_complete:
        raise HTTPException(
            status_code=400,
            detail={"message": "Missing required fields", "missingFields": missing_fields}
        )
    
    # Save to mock DB
    import uuid
    from datetime import datetime
    job_record = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        **job
    }
    mock_db.append(job_record)
    logger.info(f"Job saved to mock DB. Total jobs: {len(mock_db)}")
    
    return {"status": "success", "message": "Job saved.", "job": job_record}


@app.get("/api/jobs")
async def list_jobs():
    """List all jobs in mock DB (for debugging)."""
    return {"jobs": mock_db}


@app.post("/api/offline-upload")
async def offline_upload_endpoint(
    audio: UploadFile = File(...),
    metadata: str = Form(default="{}")  # JSON string of any partial state from live session
):
    """
    Store & Forward endpoint.
    Receives an audio file captured offline, processes it through Gemini's batch API,
    and returns the extracted job form with completeness info.
    """
    try:
        partial_metadata = json.loads(metadata) if metadata else {}
        audio_bytes = await audio.read()
        mime_type = audio.content_type or "audio/wav"
        
        logger.info(f"Offline upload received. Size: {len(audio_bytes)} bytes, type: {mime_type}, partial: {partial_metadata}")
        
        # Process through Gemini batch API
        result = await process_offline_audio(audio_bytes, mime_type, partial_metadata)
        
        # If the form is complete, auto-save to mock DB
        if result["isComplete"]:
            import uuid
            from datetime import datetime
            job_record = {
                "id": str(uuid.uuid4()),
                "created_at": datetime.utcnow().isoformat(),
                "source": "offline_upload",
                **result["job"]
            }
            mock_db.append(job_record)
            logger.info(f"Complete offline job auto-saved. Total jobs: {len(mock_db)}")
            result["job"] = job_record
        
        return result
        
    except ValueError as e:
        logger.error(f"Offline processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Offline processing error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to process offline audio")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
