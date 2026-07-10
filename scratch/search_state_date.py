from google.cloud import firestore

db = firestore.Client(project="firestore-cyvisser", database="running-coach")
events_ref = db.collection("adk-session").document("running_coach").collection("users").document("user").collection("sessions").document("47987a5c-2ad5-4591-aed1-3a4cf7177ca1").collection("events")

events = list(events_ref.stream())
sorted_events = sorted(events, key=lambda x: x.get("timestamp") or 0)

for idx, doc in enumerate(sorted_events):
    data = doc.to_dict()
    event_data = data.get("event_data", {})
    actions = event_data.get("actions", {})
    state_delta = actions.get("state_delta", {})
    if "current_date_str" in state_delta:
        print(f"Event {idx} ({doc.id}): state_delta['current_date_str'] = {state_delta['current_date_str']}")
    
    # Check if we can find current_date_str in system prompt/context msg
    # Let's inspect content or node_info
    author = event_data.get("author")
    if author == "running_coach_workflow":
        print(f"Event {idx} ({doc.id}): workflow action: {actions}")
