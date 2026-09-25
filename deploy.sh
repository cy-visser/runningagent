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
REGION="${DEPLOY_REGION:-europe-west4}"
IDENTITY="running-coach-agent@${PROJECT_ID}.iam.gserviceaccount.com"
SESSION_URI="firestore://${PROJECT_ID}"
SECRET_NAME="${TP_COOKIE_SECRET_ID:-tp-auth-cookie}"
DRY_RUN=false

# Parse parameters
TP_COOKIE=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --tp-cookie)
            if [[ "$#" -gt 1 && ! "$2" =~ ^-- ]]; then
                TP_COOKIE="$2"
                shift
            else
                TP_COOKIE=""
            fi
            ;;
        --tp-cookie=*)
            TP_COOKIE="${1#*=}"
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$TP_COOKIE" ]; then
    echo "No TrainingPeaks cookie provided. Checking Secret Manager for existing '${SECRET_NAME}'..."
    if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo "Error: Secret '${SECRET_NAME}' does not exist in Secret Manager for project ${PROJECT_ID}."
        echo "Please provide a TrainingPeaks cookie to initialize the secret."
        echo "Usage: ./deploy.sh --tp-cookie \"V001...\""
        exit 1
    fi
    if ! gcloud secrets versions describe latest --secret="${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo "Error: Secret '${SECRET_NAME}' exists in Secret Manager but has no active versions."
        echo "Please provide a TrainingPeaks cookie."
        echo "Usage: ./deploy.sh --tp-cookie \"V001...\""
        exit 1
    fi
    echo "Found existing active secret '${SECRET_NAME}' in Secret Manager. Continuing..."
fi

echo "======================================================================="
echo " Deploying Running Coach Agent to Vertex AI Agent Engine"
echo "======================================================================="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Identity: ${IDENTITY}"
echo "======================================================================="

# 1. Upload/Update the cookie in Secret Manager (if a new value was provided)
if [ "$DRY_RUN" = true ]; then
    if [ -n "$TP_COOKIE" ]; then
        echo "[DRY RUN] Would upload new TrainingPeaks cookie to Secret Manager secret '${SECRET_NAME}'."
    else
        echo "[DRY RUN] Using existing '${SECRET_NAME}' secret from Secret Manager."
    fi
    echo "[DRY RUN] Validation passed. Skipping ADK deployment."
    exit 0
fi

if [ -n "$TP_COOKIE" ]; then
    echo "Uploading new TrainingPeaks cookie to Secret Manager..."
    echo -n "$TP_COOKIE" | gcloud secrets versions add "${SECRET_NAME}" \
      --data-file=- \
      --project="${PROJECT_ID}"
else
    echo "Using existing '${SECRET_NAME}' secret from Secret Manager."
fi

# 2. Build the Agent Engine env file WITHOUT the TrainingPeaks cookie. Without
#    --env_file, `adk deploy` would copy every .env variable (including the
#    cookie) into the Agent Engine environment. The cookie is read from Secret
#    Manager at runtime instead (services/secrets.py).
DEPLOY_ENV=$(mktemp)
trap 'rm -f "$DEPLOY_ENV"' EXIT
if [ -f .env ]; then
    grep -v -E '^(TP_AUTH_COOKIE|TP_COOKIE_SECRET_ID)=' .env > "$DEPLOY_ENV" || true
fi
echo "TP_COOKIE_SECRET_ID=${SECRET_NAME}" >> "$DEPLOY_ENV"

# 3. Run the agent under the dedicated service account for this project.
printf '{\n  "service_account": "%s"\n}\n' "${IDENTITY}" > .agent_engine_config.json

# 4. Run the ADK deployment
echo "Triggering Vertex AI deployment..."
adk deploy agent_engine \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --display_name "Running Coach" \
  --description "AI Running Coach integrated with TrainingPeaks and Firestore" \
  --session_service_uri "${SESSION_URI}" \
  --env_file "${DEPLOY_ENV}" \
  --otel_to_cloud \
  .

echo "======================================================================="
echo "Deployment completed successfully!"
echo "======================================================================="
