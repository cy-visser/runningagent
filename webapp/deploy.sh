#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -f ../.env ]; then
    export $(grep -v '^[[:space:]]*#' ../.env | grep -v '^[[:space:]]*$' | xargs)
fi

if [ -z "${GOOGLE_CLOUD_PROJECT:-}" ]; then
    echo "Error: GOOGLE_CLOUD_PROJECT is required (set in environment or ../.env)." >&2
    exit 1
fi

for bin in gcloud jq; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "Error: Required tool '$bin' is not installed or not on PATH." >&2
        exit 1
    fi
done

PROJECT_ID="$GOOGLE_CLOUD_PROJECT"
REGION="${DEPLOY_REGION:-europe-west4}"
WEB_SERVICE_NAME="${WEB_SERVICE_NAME:-running-coach-web}"
WEB_SA="${WEB_SA_EMAIL:-running-coach-web@${PROJECT_ID}.iam.gserviceaccount.com}"
FIRESTORE_DB="${FIRESTORE_DATABASE:-running-coach}"
KMS_KEY_RING="${KMS_KEY_RING:-running-coach}"
KMS_KEY_NAME="${TP_COOKIE_KMS_KEY_NAME:-tp-cookie}"
KMS_KEY="${TP_COOKIE_KMS_KEY:-projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KMS_KEY_RING}/cryptoKeys/${KMS_KEY_NAME}}"
DRY_RUN=false
AGENT_RUNTIME_ID="${AGENT_RUNTIME_RESOURCE:-}"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            ;;
        --agent-runtime-id)
            AGENT_RUNTIME_ID="$2"
            shift
            ;;
        --agent-runtime-id=*)
            AGENT_RUNTIME_ID="${1#*=}"
            ;;
        *)
            echo "Unknown parameter: $1" >&2
            echo "Usage: ./deploy.sh [--dry-run] [--agent-runtime-id RESOURCE_NAME]" >&2
            exit 1
            ;;
    esac
    shift
done

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" --quiet)
if [ -z "$PROJECT_NUMBER" ]; then
    echo "Error: Could not resolve project number for '${PROJECT_ID}'." >&2
    exit 1
fi

if [ -z "$AGENT_RUNTIME_ID" ] && [ -f ../deployment_metadata.json ]; then
    AGENT_RUNTIME_ID=$(jq -r '.remote_agent_runtime_id // empty' ../deployment_metadata.json)
fi

if [ -z "$AGENT_RUNTIME_ID" ]; then
    echo "Error: AGENT_RUNTIME_RESOURCE not set and ../deployment_metadata.json has no remote_agent_runtime_id." >&2
    exit 1
fi

IAP_AUDIENCE="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/${WEB_SERVICE_NAME}"
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"

WEB_ENV_VARS=(
    "AUTH_MODE=iap"
    "IAP_AUDIENCE=${IAP_AUDIENCE}"
    "AGENT_RUNTIME_RESOURCE=${AGENT_RUNTIME_ID}"
    "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
    "FIRESTORE_PROJECT_ID=${PROJECT_ID}"
    "FIRESTORE_DATABASE=${FIRESTORE_DB}"
    "TP_COOKIE_KMS_KEY=${KMS_KEY}"
)
WEB_ENV_CSV=$(IFS=,; echo "${WEB_ENV_VARS[*]}")

echo "======================================================================="
echo " Deploying Running Coach Web App (Cloud Run + Direct IAP)"
echo "======================================================================="
echo "Project:        ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "Region:         ${REGION}"
echo "Cloud Run Svc:  ${WEB_SERVICE_NAME}"
echo "Service Acct:   ${WEB_SA}"
echo "IAP Audience:   ${IAP_AUDIENCE}"
echo "Agent Runtime:  ${AGENT_RUNTIME_ID}"
echo "KMS Key:        ${KMS_KEY}"
echo "======================================================================="

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would ensure IAP service identity (${IAP_SA})."
    echo "[DRY RUN] Would run:"
    echo "  gcloud run deploy ${WEB_SERVICE_NAME} \\"
    echo "    --source . \\"
    echo "    --project ${PROJECT_ID} \\"
    echo "    --region ${REGION} \\"
    echo "    --service-account ${WEB_SA} \\"
    echo "    --no-allow-unauthenticated \\"
    echo "    --iap \\"
    echo "    --timeout 900 \\"
    echo "    --memory 1Gi \\"
    echo "    --cpu 1 \\"
    echo "    --min-instances 0 \\"
    echo "    --max-instances 3 \\"
    echo "    --set-env-vars \"${WEB_ENV_CSV}\""
    echo "[DRY RUN] Would bind roles/run.invoker for serviceAccount:${IAP_SA} on ${WEB_SERVICE_NAME}."
    exit 0
fi

echo "Ensuring IAP service identity exists..."
gcloud beta services identity create \
    --service=iap.googleapis.com \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null 2>&1 || true

echo "Building & deploying Cloud Run service '${WEB_SERVICE_NAME}'..."
gcloud run deploy "${WEB_SERVICE_NAME}" \
    --source . \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --service-account "${WEB_SA}" \
    --no-allow-unauthenticated \
    --iap \
    --timeout 900 \
    --memory 1Gi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 3 \
    --set-env-vars "${WEB_ENV_CSV}" \
    --quiet

echo "Ensuring IAP service agent has roles/run.invoker on '${WEB_SERVICE_NAME}'..."
gcloud run services add-iam-policy-binding "${WEB_SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --member="serviceAccount:${IAP_SA}" \
    --role="roles/run.invoker" \
    --quiet >/dev/null

SERVICE_URL=$(gcloud run services describe "${WEB_SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --format="value(status.url)" \
    --quiet)

echo "======================================================================="
echo "Cloud Run Web App deployed successfully!"
echo "  Web App URL: ${SERVICE_URL}"
echo ""
echo "To grant an IAM user or group access through IAP:"
echo "  gcloud iap web add-iam-policy-binding \\"
echo "    --project=${PROJECT_ID} \\"
echo "    --resource-type=cloud-run \\"
echo "    --service=${WEB_SERVICE_NAME} \\"
echo "    --region=${REGION} \\"
echo "    --member='user:cyrille@cyvisser.altostrat.com' \\"
echo "    --role='roles/iap.httpsResourceAccessor'"
echo "======================================================================="
