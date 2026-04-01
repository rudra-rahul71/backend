from google.genai import types

t = types.LiveConnectConfig(
    tools=[{
        "function_declarations": [{
            "name": "update_job_details",
            "description": "Updates the job details...",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "homeowner_name": {"type": "STRING"}
                }
            }
        }]
    }]
)
print("SUCCESS:", t.tools[0])
