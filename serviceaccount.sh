# 1. Create the dedicated Service Account
gcloud iam service-accounts create running-coach-agent \
    --description="Dedicated identity for the AI Running Coach agent" \
    --display-name="Running Coach Agent Identity" \
    --project="firestore-cyvisser"

# 2. Grant roles to the Service Account at the project level
# Vertex AI User: Allows the agent to call Gemini 2.5 Pro and use Vertex AI features
gcloud projects add-iam-policy-binding firestore-cyvisser \
    --member="serviceAccount:running-coach-agent@firestore-cyvisser.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Firestore User: Allows the agent to read/write session state and the geocoding cache
gcloud projects add-iam-policy-binding firestore-cyvisser \
    --member="serviceAccount:running-coach-agent@firestore-cyvisser.iam.gserviceaccount.com" \
    --role="roles/datastore.user"

# Cloud Trace Agent: Allows the agent to send OpenTelemetry spans to Cloud Trace
gcloud projects add-iam-policy-binding firestore-cyvisser \
    --member="serviceAccount:running-coach-agent@firestore-cyvisser.iam.gserviceaccount.com" \
    --role="roles/cloudtrace.agent"

# Logs Writer: Allows the agent to write logs to Cloud Logging
gcloud projects add-iam-policy-binding firestore-cyvisser \
    --member="serviceAccount:running-coach-agent@firestore-cyvisser.iam.gserviceaccount.com" \
    --role="roles/logging.logWriter"

# 3. Grant Service Account User to the Vertex AI Service Agent
# This allows the Vertex AI Reasoning Engine service to "act as" your service account.
# Without this step, the deployment or agent execution will fail with a permission error.
PROJECT_NUMBER=$(gcloud projects describe firestore-cyvisser --format="value(projectNumber)")

gcloud iam service-accounts add-iam-policy-binding \
    running-coach-agent@firestore-cyvisser.iam.gserviceaccount.com \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser" \
    --project="firestore-cyvisser"
