import google.auth
import google.auth.transport.requests
import requests
import json
import uuid
import sys

project = "firestore-cyvisser"
location = "europe-west4"
engine_id = "681459714709520384"

# Generate a unique session ID for this CLI run
session_id = f"cli-session-{uuid.uuid4().hex[:8]}"

# Authenticate
print("Authenticating with Google Cloud...")
credentials, project_id = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
auth_req = google.auth.transport.requests.Request()
credentials.refresh(auth_req)
token = credentials.token

url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{location}/reasoningEngines/{engine_id}:streamQuery"

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print(f"Session started! ID: {session_id}")
print("You can start chatting with your running coach (type 'exit' to quit).\n")

while True:
    try:
        user_input = input("You: ")
        if user_input.strip().lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
        if not user_input.strip():
            continue

        stream_run_request = {
            "message": {
                "role": "user",
                "parts": [{"text": user_input}]
            },
            "user_id": "cli-user",
            "session_id": session_id
        }

        payload = {
            "class_method": "streaming_agent_run_with_events",
            "input": {
                "request_json": json.dumps(stream_run_request)
            }
        }

        sys.stdout.write("Coach: ")
        sys.stdout.flush()

        response = requests.post(url, json=payload, headers=headers, stream=True)
        if response.status_code != 200:
            print(f"\nError: {response.status_code}")
            print(response.text)
            continue

        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                try:
                    chunk = json.loads(decoded_line)
                    for event in chunk.get("events", []):
                        if event.get("author") in ["model", "coaching_agent"] and "content" in event:
                            parts = event["content"].get("parts", [])
                            for part in parts:
                                if "text" in part:
                                    sys.stdout.write(part["text"])
                                    sys.stdout.flush()
                except Exception:
                    pass
        print("\n")

    except KeyboardInterrupt:
        print("\nGoodbye!")
        break
    except Exception as e:
        print(f"\nError occurred: {e}")
