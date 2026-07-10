from google.cloud import firestore

db = firestore.Client(project="firestore-cyvisser", database="running-coach")
doc_ref = db.collection("adk-session").document("running_coach").collection("users").document("user").collection("sessions").document("47987a5c-2ad5-4591-aed1-3a4cf7177ca1")

subcols = list(doc_ref.collections())
print(f"Subcollections: {[sc.id for sc in subcols]}")

for sc in subcols:
    docs = list(sc.list_documents())
    print(f"  Subcollection: {sc.id}, documents: {len(docs)}")
    for d in docs[:5]:
        print(f"    Document: {d.id}")
        print(f"      Data: {str(d.get().to_dict())[:500]}")
