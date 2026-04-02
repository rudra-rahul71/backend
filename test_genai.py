import os
import time
from google import genai
from google.genai import types

gemini_api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=gemini_api_key)

try:
    with open("dummy.wav", "wb") as f:
        f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
            
    print("Uploading file...")
    uploaded_file = client.files.upload(path="dummy.wav")
    while uploaded_file.state == "PROCESSING":
        time.sleep(1)
        uploaded_file = client.files.get(name=uploaded_file.name)
        
    print(f"File uploaded. URI: {uploaded_file.uri}. Testing simplest prompt...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(file_uri=uploaded_file.uri, mime_type="audio/wav"),
                    types.Part.from_text("Describe this audio."),
                ]
            )
        ]
    )
    print("Simplest test SUCCESS!")
    
    print("Testing with system instruction...")
    response2 = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(file_uri=uploaded_file.uri, mime_type="audio/wav"),
                    types.Part.from_text("Describe this audio."),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            system_instruction=types.Content(parts=[types.Part.from_text("You are an assistant.")])
        )
    )
    print("System instruction test SUCCESS!")
    
except Exception as e:
    import traceback
    traceback.print_exc()

