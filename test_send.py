from google.genai import types
import json
from google.genai.live import _parse_input_to_msg

msg = _parse_input_to_msg({"mime_type": "audio/pcm;rate=16000", "data": b"rawbytes"}, False)
print("OUTPUT:", msg)
