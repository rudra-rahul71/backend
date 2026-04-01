import asyncio
import os
import logging
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test():
    api_key = os.environ.get('GEMINI_API_KEY')
    print(f'API Key present: {bool(api_key)}')
    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"]
    )
    try:
        print('Attempting to connect...')
        async with client.aio.live.connect(model='gemini-3.1-flash-live-preview', config=config) as session:
            print('SUCCESS - Connected to Gemini Live API')
    except Exception as e:
        print(f'ERROR: {e}')

if __name__ == '__main__':
    asyncio.run(test())
