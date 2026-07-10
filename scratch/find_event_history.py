from google.cloud import firestore

db = firestore.Client(project="firestore-cyvisser", database="running-coach")
events_ref = db.collection("adk-session").document("running_coach").collection("users").document("user").collection("sessions").document("47987a5c-2ad5-4591-aed1-3a4cf7177ca1").collection("events")

events = list(events_ref.stream())
sorted_events = sorted(events, key=lambda x: x.get("timestamp") or 0)

print(f"Total events: {len(sorted_events)}")
for idx in range(max(0, len(sorted_events) - 15), len(sorted_events)):
    doc = sorted_events[idx]
    data = doc.to_dict()
    event_data = data.get("event_data", {})
    author = event_data.get("author") or data.get("author")
    content = event_data.get("content") or {}
    print(f"\n[{idx}] ID: {doc.id} | Timestamp: {data.get('timestamp')} | Author: {author}")
    if isinstance(content, dict):
        role = content.get("role")
        parts = content.get("parts") or []
        print(f"  Role: {role}")
        for p in parts:
            if isinstance(p, dict):
                if 'text' in p:
                    print(f"  Text: {p['text']}")
                elif 'function_call' in p:
                    print(f"  Function Call: {p['function_call']}")
                elif 'function_response' in p:
                    print(f"  Function Response: {p['function_response']}")
                else:
                    print(f"  Part: {p}")
            else:
                print(f"  Part: {p}")
    else:
        print(f"  Content: {content}")
    if event_data.get("tool_calls"):
        print(f"  Tool Calls: {event_data.get('tool_calls')}")
    if event_data.get("output"):
        print(f"  Output: {event_data.get('output')}")
