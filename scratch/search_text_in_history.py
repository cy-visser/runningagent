from google.cloud import firestore

db = firestore.Client(project="firestore-cyvisser", database="running-coach")
events_ref = db.collection("adk-session").document("running_coach").collection("users").document("user").collection("sessions").document("47987a5c-2ad5-4591-aed1-3a4cf7177ca1").collection("events")

events = list(events_ref.stream())
sorted_events = sorted(events, key=lambda x: x.get("timestamp") or 0)

for idx, doc in enumerate(sorted_events):
    data = doc.to_dict()
    event_data = data.get("event_data", {})
    author = event_data.get("author") or data.get("author")
    content = event_data.get("content") or {}
    
    parts = content.get("parts") or []
    text = ""
    for p in parts:
        if isinstance(p, dict) and 'text' in p:
            text += p['text']
        elif isinstance(p, dict) and 'function_call' in p:
            text += f"\n[Called Tool: {p['function_call']['name']}]"
        elif isinstance(p, dict) and 'function_response' in p:
            text += f"\n[Response: {str(p['function_response'].get('response'))[:100]}]"
            
    if not text and isinstance(content, str):
        text = content
        
    lower_text = text.lower()
    if any(q in lower_text for q in ["yesterday", "july 1", "july 2", "july 5", "sunday"]):
        print(f"\n[{idx}] {data.get('timestamp')} | Author: {author} | Role: {content.get('role') if isinstance(content, dict) else None}")
        print(text.strip()[:400])
