import asyncio
import os
import logging
import json
import base64
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

async def test():
    api_key = os.environ.get('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"]
    )
    try:
        async with client.aio.live.connect(model='gemini-3.1-flash-live-preview', config=config) as session:
            print('Connected to Gemini Live API')
            
            # Create dummy PCM data
            pcm_bytes = b'\x00' * 8192
            data_b64 = base64.b64encode(pcm_bytes).decode('utf-8')
            
            # TEST 1: The old way (deprecated, should fail)
            # msg = {"realtime_input": {"media_chunks": [{"mime_type": "audio/pcm;rate=16000", "data": data_b64}]}}
            
            # TEST 2: realtime_input.audio
            msg = {"realtime_input": {"audio": {"mimeType": "audio/pcm;rate=16000", "data": data_b64}}}
            
            # TEST 3: client_content
            # msg = {"client_content": {"turns": [{"role": "user", "parts": [{"inlineData": {"mimeType": "audio/pcm;rate=16000", "data": data_b64}}]}]}}
            
            print('Sending:', msg)
            await session._ws.send(json.dumps(msg))
            
            # Wait for response
            print('Waiting for response...')
            response = await session._receive()
            print('Response:', response)
            
    except Exception as e:
        print(f'ERROR: {e}')

if __name__ == '__main__':
    asyncio.run(test())
