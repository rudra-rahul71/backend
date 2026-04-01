import os
import enum
import base64
import json
import logging
from typing import Callable, Awaitable
from google import genai
from google.genai import types
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ServiceSector(str, enum.Enum):
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    ELECTRICAL = "ELECTRICAL"
    APPLIANCES = "APPLIANCES"
    LANDSCAPING = "LANDSCAPING"
    UNKNOWN = "UNKNOWN"

def update_job_details(
    homeowner_name: str,
    homeowner_phone: str,
    homeowner_address: str,
    job_description: str,
    service_sector: ServiceSector,
    homeowner_approved: bool
) -> dict:
    """
    Updates the job details on the user's checklist. Use this tool whenever you have extracted or updated information about the job.
    """
    return {"status": "success"}

SYSTEM_INSTRUCTION = """
You are TradeEngage AI, assisting field service technicians.
The technician will dictate job details while recording a video/audio.
Listen to the audio. As soon as you identify any required entities for a job referral, trigger the 'update_job_details' tool.
If the technician corrects themselves (e.g., "Wait, it's HVAC, not plumbing"), fire the tool again with the updated information.
Your ONLY goal is to extract: Homeowner Name, Phone, Address, Job Description, Service Sector, and if they approved the estimate.
"""

async def handle_gemini_session(websocket: WebSocket, client_receive_queue):
    """
    Manages the Gemini Live Session.
    We receive audio from client_receive_queue (produced by the websocket handler),
    stream it to Gemini, and push Gemini's responses (tool calls) back to the websocket.
    """
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        logger.error("GEMINI_API_KEY is not set.")
        await websocket.close(code=1011, reason="Server AI not configured")
        return

    import asyncio
    
    # Establish connection
    try:
        logger.info("Creating Gemini client...")
        client = genai.Client(api_key=gemini_api_key, http_options={'api_version': 'v1alpha'})
        
        config = types.LiveConnectConfig(
            system_instruction=types.Content(parts=[types.Part.from_text(SYSTEM_INSTRUCTION)]),
            tools=[{"function_declarations": [{"name": "update_job_details", "description": "Updates the job details on the user's checklist. Use this tool whenever you have extracted or updated information about the job.", "parameters": {"type": "OBJECT", "properties": {"homeowner_name": {"type": "STRING"}, "homeowner_phone": {"type": "STRING"}, "homeowner_address": {"type": "STRING"}, "job_description": {"type": "STRING"}, "service_sector": {"type": "STRING", "enum": ["PLUMBING", "HVAC", "ELECTRICAL", "APPLIANCES", "LANDSCAPING", "UNKNOWN"]}, "homeowner_approved": {"type": "BOOLEAN"}}, "required": ["homeowner_name", "homeowner_phone", "homeowner_address", "job_description", "service_sector", "homeowner_approved"]}}]}],
            response_modalities=["AUDIO"]
        )
        logger.info("Connecting to Gemini Live API...")
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
            logger.info("✅ Connected to Gemini Live API successfully")
            
            # Task to receive audio from frontend and send to Gemini
            async def send_to_gemini():
                logger.info("send_to_gemini task started, waiting for audio from queue...")
                while True:
                    data = await client_receive_queue.get()
                    if data is None:
                        logger.info("Received shutdown signal in send_to_gemini")
                        break
                    
                    logger.info(f"Dequeued audio chunk, length: {len(data)}, sending to Gemini...")
                    # Bypassing the SDK's parse_client_message to avoid the deprecated media_chunks format
                    # 'data' is already a base64 encoded audio string from the frontend
                    msg = {
                        "realtime_input": {
                            "audio": {
                                "mimeType": "audio/pcm;rate=16000",
                                "data": data
                            }
                        }
                    }
                    import json
                    await session._ws.send(json.dumps(msg))
                    logger.info("Audio chunk sent to Gemini successfully")
            
            # Task to receive from Gemini and send to Frontend
            async def receive_from_gemini():
                while True:
                    async for response in session.receive():
                        # Handle audio responses from Gemini
                        if response.server_content is not None:
                            sc = response.server_content
                            if sc.model_turn is not None:
                                for part in sc.model_turn.parts:
                                    if part.inline_data is not None:
                                        audio_b64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                                        logger.info(f"Relaying audio from Gemini, size: {len(part.inline_data.data)} bytes")
                                        await websocket.send_json({
                                            "type": "audio_response",
                                            "data": audio_b64,
                                            "mime_type": part.inline_data.mime_type or "audio/pcm;rate=24000"
                                        })
                                    if part.text is not None:
                                        logger.info(f"Gemini text: {part.text}")
                                        await websocket.send_json({
                                            "type": "text_response",
                                            "text": part.text
                                        })
                            if sc.turn_complete:
                                logger.info("Gemini turn complete, listening for next turn...")
                                await websocket.send_json({"type": "turn_complete"})

                        # Handle tool calls
                        if response.tool_call is not None:
                            for fc in response.tool_call.function_calls:
                                if fc.name == "update_job_details":
                                    logger.info(f"Tool call received: {fc.args}")
                                    # Relay tool call arguments to the frontend checklist
                                    await websocket.send_json({
                                        "type": "tool_call",
                                        "function": "update_job_details",
                                        "args": fc.args
                                    })
                                    
                                    # Acknowledge tool call back to Gemini to keep session active
                                    await session.send(input=types.LiveClientToolResponse(
                                        function_responses=[
                                            types.FunctionResponse(
                                                name=fc.name,
                                                id=fc.id,
                                                response={"success": True}
                                            )
                                        ]
                                    ))
            
            task_send = asyncio.create_task(send_to_gemini())
            task_receive = asyncio.create_task(receive_from_gemini())
            
            done, pending = await asyncio.wait(
                [task_send, task_receive],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for p in pending:
                p.cancel()
                
    except Exception as e:
        import traceback
        logger.error(f"Gemini Session Error: {e}")
        logger.error(traceback.format_exc())
        try:
            await websocket.close()
        except:
            pass
