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
    service_sector: str,
    homeowner_approved: bool
) -> dict:
    """
    Updates the job details on the user's checklist. Use this tool whenever you have extracted or updated information about the job.
    service_sector must be one of: PLUMBING, HVAC, ELECTRICAL, APPLIANCES, LANDSCAPING, UNKNOWN.
    """
    return {"status": "success"}

SYSTEM_INSTRUCTION = """
You are TradeEngage AI, assisting field service technicians.
The technician will dictate job details while recording a video/audio.
Listen to the audio. As soon as you identify any required entities for a job referral, trigger the 'update_job_details' tool.
If the technician corrects themselves (e.g., "Wait, it's HVAC, not plumbing"), fire the tool again with the updated information.
Your ONLY goal is to extract: Homeowner Name, Phone, Address, Job Description, Service Sector, and if they approved the estimate.
"""

REQUIRED_FIELDS = ["homeowner_name", "homeowner_phone", "homeowner_address", "job_description", "service_sector"]
VALID_SECTORS = {"PLUMBING", "HVAC", "ELECTRICAL", "APPLIANCES", "LANDSCAPING", "UNKNOWN"}

BATCH_SYSTEM_INSTRUCTION = """
You are TradeEngage AI, assisting field service technicians.
You will receive an audio recording from a field technician who was dictating job details.
Listen to the ENTIRE audio carefully, then extract ALL of the following information and call the 'update_job_details' tool ONCE with everything you found:
- Homeowner Name
- Homeowner Phone
- Homeowner Address
- Job Description
- Service Sector (one of: PLUMBING, HVAC, ELECTRICAL, APPLIANCES, LANDSCAPING, UNKNOWN)
- Whether the homeowner approved the estimate (true/false)

If some information is missing from the audio, still call the tool with whatever you did find — leave missing string fields as empty strings and missing booleans as false.
"""


def check_completeness(job: dict) -> tuple[bool, list[str]]:
    """Check if all required job fields are filled in."""
    missing = []
    for field in REQUIRED_FIELDS:
        value = job.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)
        elif field == "service_sector" and value == "UNKNOWN":
            missing.append(field)
    return len(missing) == 0, missing


async def process_offline_audio(audio_bytes: bytes, mime_type: str, partial_metadata: dict | None = None) -> dict:
    """
    Process a saved audio file using the Gemini Content API (non-streaming batch mode).
    Returns { job: {...}, isComplete: bool, missingFields: [...] }
    """
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=gemini_api_key)

    # Build the prompt
    prompt_parts = []
    if partial_metadata:
        non_empty = {k: v for k, v in partial_metadata.items() if v}
        if non_empty:
            prompt_parts.append(
                f"The following fields were already extracted during a partial live session: {json.dumps(non_empty)}. "
                "Please verify and complete the remaining fields from the audio."
            )
    prompt_parts.append("Listen to the attached audio recording and extract all job details using the update_job_details tool.")

    try:
        logger.info(f"Using inline audio bytes. Size: {len(audio_bytes)} bytes, mime_type: {mime_type}")
        base_mime = mime_type.split(";")[0].strip()

        # Call generate_content with function calling
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=base_mime),
                        types.Part.from_text("\n".join(prompt_parts)),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=BATCH_SYSTEM_INSTRUCTION,
                tools=[update_job_details],
            ),
        )

        # Parse tool call from response
        job = {
            "homeowner_name": "",
            "homeowner_phone": "",
            "homeowner_address": "",
            "job_description": "",
            "service_sector": "UNKNOWN",
            "homeowner_approved": False,
        }

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.function_call and part.function_call.name == "update_job_details":
                    args = dict(part.function_call.args)
                    logger.info(f"Batch Gemini extracted: {args}")
                    # Validate service_sector against allowed values
                    if "service_sector" in args:
                        sector = args["service_sector"].upper().strip()
                        args["service_sector"] = sector if sector in VALID_SECTORS else "UNKNOWN"
                    job.update(args)
                    break

        # Merge with partial metadata (prefer Gemini's extraction over partial)
        if partial_metadata:
            for key, value in partial_metadata.items():
                if key in job and (not job[key] or job[key] == "UNKNOWN") and value:
                    job[key] = value

        is_complete, missing_fields = check_completeness(job)
        logger.info(f"Job completeness: {is_complete}, missing: {missing_fields}")

        return {"job": job, "isComplete": is_complete, "missingFields": missing_fields}

    except Exception as e:
        logger.error(f"Error during offline Gemini processing: {e}")
        raise


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
              try:
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
              except asyncio.CancelledError:
                logger.info("receive_from_gemini task cancelled.")
              except Exception as e:
                # ConnectionClosedOK (code 1000) is expected on normal session end
                if "1000" in str(e):
                    logger.info("Gemini session closed normally.")
                else:
                    logger.error(f"receive_from_gemini error: {e}")

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
