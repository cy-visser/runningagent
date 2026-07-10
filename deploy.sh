#!/bin/bash
set -e

# Load .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "Error: GOOGLE_CLOUD_PROJECT environment variable or config in .env is required."
    exit 1
fi

if [ -z "$GOOGLE_CLOUD_LOCATION" ]; then
    echo "Error: GOOGLE_CLOUD_LOCATION environment variable or config in .env is required."
    exit 1
fi

PROJECT_ID="$GOOGLE_CLOUD_PROJECT"
REGION="europe-west4"
IDENTITY="running-coach-agent@${PROJECT_ID}.iam.gserviceaccount.com"
SESSION_URI="firestore://${PROJECT_ID}"

# Parse parameters
TP_COOKIE=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --tp-cookie) TP_COOKIE="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$TP_COOKIE" ]; then
    echo "Error: --tp-cookie parameter is required."
    echo "Usage: ./deploy.sh --tp-cookie \"V001...\""
    exit 1
fi

echo "======================================================================="
echo " Deploying Running Coach Agent to Vertex AI Agent Engine"
echo "======================================================================="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Identity: ${IDENTITY}"
echo "======================================================================="

# 1. Upload/Update the cookie in Secret Manager
echo "Uploading TrainingPeaks cookie to Secret Manager..."
echo -n "$TP_COOKIE" | gcloud secrets versions add tp-auth-cookie \
  --data-file=- \
  --project="${PROJECT_ID}"

# 2. Run the ADK deployment
echo "Triggering Vertex AI deployment..."
adk deploy agent_engine \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --display_name "Running Coach" \
  --description "AI Running Coach integrated with TrainingPeaks and Firestore" \
  --session_service_uri "${SESSION_URI}" \
  --otel_to_cloud \
  .

echo "======================================================================="
echo "Deployment completed successfully!"
echo "======================================================================="
