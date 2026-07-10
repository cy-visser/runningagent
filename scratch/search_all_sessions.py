from google.cloud import firestore

db = firestore.Client(project="firestore-cyvisser", database="running-coach")
users_ref = db.collection("adk-session").document("running_coach").collection("users")

for user_doc in users_ref.list_documents():
    sessions_ref = users_ref.document(user_doc.id).collection("sessions")
    for session_doc in sessions_ref.list_documents():
        events_ref = sessions_ref.document(session_doc.id).collection("events")
        events = list(events_ref.stream())
        for doc in events:
            data = doc.to_dict()
            event_data = data.get("event_data", {})
            content = event_data.get("content") or {}
            parts = content.get("parts") or []
            text = ""
            for p in parts:
                if isinstance(p, dict) and 'text' in p:
                    text += p['text']
            if "sunday" in text.lower():
                print(f"Match found in User: {user_doc.id}, Session: {session_doc.id}, Event: {doc.id}")
                print(f"Text: {text[:300]}")
