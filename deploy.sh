#!/bin/bash
set -e

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
echo "Project:  firestore-cyvisser"
echo "Region:   europe-west4"
echo "Identity: running-coach-agent@firestore-cyvisser.iam.gserviceaccount.com"
echo "======================================================================="

# 1. Upload/Update the cookie in Secret Manager
echo "Uploading TrainingPeaks cookie to Secret Manager..."
echo -n "$TP_COOKIE" | gcloud secrets versions add tp-auth-cookie \
  --data-file=- \
  --project="firestore-cyvisser"

# 2. Run the ADK deployment
echo "Triggering Vertex AI deployment..."
adk deploy agent_engine \
  --project "firestore-cyvisser" \
  --region "europe-west4" \
  --display_name "Running Coach" \
  --description "AI Running Coach integrated with TrainingPeaks and Firestore" \
  --session_service_uri "firestore://" \
  --otel_to_cloud \
  .

echo "======================================================================="
echo "Deployment completed successfully!"
echo "======================================================================="
