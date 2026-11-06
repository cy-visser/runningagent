#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

# Refuse to run if a raw TP_AUTH_COOKIE is present in .env.
if [ -f .env ] && grep -q -E '^[[:space:]]*TP_AUTH_COOKIE=' .env; then
    echo "Error: TP_AUTH_COOKIE must not be present in .env." >&2
    echo "TrainingPeaks cookies are stored per-runner in Firestore encrypted with Cloud KMS via the Web App UI." >&2
    exit 1
fi

if [ -f .env ]; then
    export $(grep -v '^[[:space:]]*#' .env | grep -v '^[[:space:]]*$' | xargs)
fi

if [ -z "${GOOGLE_CLOUD_PROJECT:-}" ]; then
    echo "Error: GOOGLE_CLOUD_PROJECT environment variable or config in .env is required." >&2
    exit 1
fi

if [ -z "${GOOGLE_CLOUD_LOCATION:-}" ]; then
    echo "Error: GOOGLE_CLOUD_LOCATION environment variable or config in .env is required." >&2
    exit 1
fi

for bin in agents-cli gcloud curl jq; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "Error: Required tool '$bin' is not installed or not on PATH." >&2
        if [ "$bin" = "agents-cli" ]; then
            echo "Install it once with: uv tool install google-agents-cli==1.8.0" >&2
        fi
        exit 1
    fi
done

PROJECT_ID="$GOOGLE_CLOUD_PROJECT"
REGION="${DEPLOY_REGION:-europe-west4}"
IDENTITY="running-coach-agent@${PROJECT_ID}.iam.gserviceaccount.com"
SESSION_URI="firestore://${PROJECT_ID}"
KMS_KEY_RING="${KMS_KEY_RING:-running-coach}"
KMS_KEY_NAME="${TP_COOKIE_KMS_KEY_NAME:-tp-cookie}"
KMS_KEY="${TP_COOKIE_KMS_KEY:-projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KMS_KEY_RING}/cryptoKeys/${KMS_KEY_NAME}}"
WEB_SERVICE_NAME="${WEB_SERVICE_NAME:-running-coach-web}"
TRACES_BUCKET="${TRACES_BUCKET:-traces_runningagent}"
GE_LOCATION="${GE_LOCATION:-global}"
GE_APP_ID="${GE_APP_ID:-running-coach}"
GE_APP_DISPLAY_NAME="Running Coach"
AGENT_DISPLAY_NAME="Running Coach"
AGENT_DESCRIPTION="Your running coach which helps you progressing your running fitness."
TARGET="web"
DRY_RUN=false

usage() {
    cat <<EOF
Usage: ./deploy.sh [--target ge|web|both] [--dry-run]

Options:
  --target ge|web|both   Front-end target(s) to deploy after updating Agent Runtime (default: web)
                           ge   -> Deploy Agent Runtime + register in Gemini Enterprise
                           web  -> Deploy Agent Runtime + deploy Cloud Run Web App (IAP)
                           both -> Deploy Agent Runtime + both Gemini Enterprise & Cloud Run Web App
  --dry-run              Validate preflight and print planned deployment actions without mutating resources
EOF
}

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --target)
            if [[ "$#" -lt 2 ]]; then
                echo "Error: --target requires a value (ge, web, or both)." >&2
                usage >&2
                exit 1
            fi
            TARGET="$2"
            shift
            ;;
        --target=*)
            TARGET="${1#*=}"
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown parameter: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

case "$TARGET" in
    ge|web|both) ;;
    *)
        echo "Error: Invalid --target '${TARGET}'. Expected 'ge', 'web', or 'both'." >&2
        exit 1
        ;;
esac

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" --quiet)
if [ -z "$PROJECT_NUMBER" ]; then
    echo "Error: Could not resolve project number for project '${PROJECT_ID}'." >&2
    exit 1
fi

WEB_APP_URL="${WEB_APP_URL:-https://${WEB_SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app}"

# Preflight: verify the Cloud KMS key for per-runner TrainingPeaks cookies exists.
if ! gcloud kms keys describe "${KMS_KEY_NAME}" \
    --keyring="${KMS_KEY_RING}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null 2>&1; then
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Note: KMS key '${KMS_KEY}' does not exist yet (run 'cd terraform && terraform apply' before live deploy)."
    else
        echo "Error: Cloud KMS key '${KMS_KEY}' not found in project '${PROJECT_ID}'." >&2
        echo "Provision infrastructure first with: cd terraform && terraform apply" >&2
        exit 1
    fi
fi

if [ "$GE_LOCATION" = "global" ]; then
    DE_BASE_URL="https://discoveryengine.googleapis.com"
else
    DE_BASE_URL="https://${GE_LOCATION}-discoveryengine.googleapis.com"
fi

find_ge_apps() {
    local token page_token="" url resp
    token=$(gcloud auth print-access-token)
    while :; do
        url="${DE_BASE_URL}/v1/projects/${PROJECT_NUMBER}/locations/${GE_LOCATION}/collections/default_collection/engines?pageSize=100"
        if [ -n "$page_token" ]; then
            url="${url}&pageToken=${page_token}"
        fi
        resp=$(curl -sS --fail-with-body \
            -H "Authorization: Bearer ${token}" \
            -H "X-Goog-User-Project: ${PROJECT_ID}" \
            "$url")
        echo "$resp" | jq -r --arg name "$GE_APP_DISPLAY_NAME" \
            '.engines[]? | select(.displayName == $name) | .name'
        page_token=$(echo "$resp" | jq -r '.nextPageToken // empty')
        if [ -z "$page_token" ]; then
            break
        fi
    done
}

ensure_ge_app() {
    local matches count token create_url payload resp op_name op_resp done_flag err_msg
    matches=$(find_ge_apps)
    if [ -z "$matches" ]; then
        count=0
    else
        count=$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d ' ')
    fi

    if [ "$count" -gt 1 ]; then
        echo "Error: Found multiple Gemini Enterprise apps named '${GE_APP_DISPLAY_NAME}' in '${GE_LOCATION}':" >&2
        printf '%s\n' "$matches" >&2
        exit 1
    fi

    if [ "$count" -eq 1 ]; then
        GE_APP_NAME=$(printf '%s\n' "$matches" | head -n 1)
        echo "Found existing Gemini Enterprise app: ${GE_APP_NAME}"
        return 0
    fi

    if [ "$DRY_RUN" = true ]; then
        GE_APP_NAME="projects/${PROJECT_NUMBER}/locations/${GE_LOCATION}/collections/default_collection/engines/${GE_APP_ID}"
        echo "[DRY RUN] Gemini Enterprise app '${GE_APP_DISPLAY_NAME}' not found in '${GE_LOCATION}'."
        echo "[DRY RUN] Would create app: ${GE_APP_NAME}"
        return 0
    fi

    echo "Creating Gemini Enterprise app '${GE_APP_DISPLAY_NAME}' (${GE_APP_ID}) in '${GE_LOCATION}'..."
    token=$(gcloud auth print-access-token)
    create_url="${DE_BASE_URL}/v1/projects/${PROJECT_NUMBER}/locations/${GE_LOCATION}/collections/default_collection/engines?engineId=${GE_APP_ID}"
    payload=$(jq -n \
        --arg display_name "$GE_APP_DISPLAY_NAME" \
        '{
            displayName: $display_name,
            solutionType: "SOLUTION_TYPE_SEARCH",
            industryVertical: "GENERIC",
            appType: "APP_TYPE_INTRANET",
            searchEngineConfig: {
                searchTier: "SEARCH_TIER_ENTERPRISE",
                searchAddOns: ["SEARCH_ADD_ON_LLM"]
            }
        }')
    resp=$(curl -sS --fail-with-body -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "X-Goog-User-Project: ${PROJECT_ID}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$create_url")

    op_name=$(echo "$resp" | jq -r '.name // empty')
    if [ -z "$op_name" ]; then
        echo "Error: Unexpected response when creating Gemini Enterprise app:" >&2
        echo "$resp" >&2
        exit 1
    fi

    for _ in $(seq 1 60); do
        done_flag=$(echo "$resp" | jq -r '.done // false')
        if [ "$done_flag" = "true" ]; then
            err_msg=$(echo "$resp" | jq -r '.error.message // empty')
            if [ -n "$err_msg" ]; then
                echo "Error creating Gemini Enterprise app: ${err_msg}" >&2
                exit 1
            fi
            break
        fi
        sleep 3
        token=$(gcloud auth print-access-token)
        op_resp=$(curl -sS --fail-with-body \
            -H "Authorization: Bearer ${token}" \
            -H "X-Goog-User-Project: ${PROJECT_ID}" \
            "${DE_BASE_URL}/v1/${op_name}")
        resp="$op_resp"
    done

    GE_APP_NAME="projects/${PROJECT_NUMBER}/locations/${GE_LOCATION}/collections/default_collection/engines/${GE_APP_ID}"
    echo "Created Gemini Enterprise app: ${GE_APP_NAME}"
}

GIT_SHA=$(git describe --always --dirty 2>/dev/null || echo "local")
RUNTIME_ENV_VARS=(
    "SESSION_SERVICE_URI=${SESSION_URI}"
    "TP_COOKIE_KMS_KEY=${KMS_KEY}"
    "WEB_APP_URL=${WEB_APP_URL}"
    "AGENT_VERSION=${GIT_SHA}"
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true"
    "OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental"
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT"
    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false"
    "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK=upload"
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT=jsonl"
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH=gs://${TRACES_BUCKET}/completions"
)
RUNTIME_ENV_CSV=$(IFS=,; echo "${RUNTIME_ENV_VARS[*]}")

echo "======================================================================="
echo " Deploying Running Coach (Target: ${TARGET})"
echo "======================================================================="
echo "Project:       ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "Region:        ${REGION}"
echo "Identity:      ${IDENTITY}"
echo "KMS Key:       ${KMS_KEY}"
echo "Web App URL:   ${WEB_APP_URL}"
echo "Traces Bucket: gs://${TRACES_BUCKET}/completions"
echo "======================================================================="

if [ "$DRY_RUN" = true ]; then
    agents-cli deploy \
        --project "${PROJECT_ID}" \
        --region "${REGION}" \
        --service-name "${AGENT_DISPLAY_NAME}" \
        --service-account "${IDENTITY}" \
        --update-env-vars "${RUNTIME_ENV_CSV}" \
        --dry-run

    EXISTING_RUNTIME_ID=""
    if [ -f deployment_metadata.json ]; then
        EXISTING_RUNTIME_ID=$(jq -r '.remote_agent_runtime_id // empty' deployment_metadata.json)
    fi
    EXISTING_RUNTIME_ID="${EXISTING_RUNTIME_ID:-projects/${PROJECT_NUMBER}/locations/${REGION}/reasoningEngines/PENDING}"

    if [[ "$TARGET" == "ge" || "$TARGET" == "both" ]]; then
        ensure_ge_app
        echo "[DRY RUN] Would register/update '${AGENT_DISPLAY_NAME}' (${EXISTING_RUNTIME_ID}) in Gemini Enterprise app '${GE_APP_NAME}'."
    fi

    if [[ "$TARGET" == "web" || "$TARGET" == "both" ]]; then
        bash ./webapp/deploy.sh --dry-run --agent-runtime-id "${EXISTING_RUNTIME_ID}"
    fi
    exit 0
fi

# 1. Always deploy the shared ADK agent to Vertex AI Agent Runtime
echo "Deploying agent to Vertex AI Agent Runtime via agents-cli..."
agents-cli deploy \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --service-name "${AGENT_DISPLAY_NAME}" \
    --service-account "${IDENTITY}" \
    --update-env-vars "${RUNTIME_ENV_CSV}"

AGENT_RUNTIME_ID=$(jq -r '.remote_agent_runtime_id // empty' deployment_metadata.json)
if [ -z "$AGENT_RUNTIME_ID" ]; then
    echo "Error: Could not read remote_agent_runtime_id from deployment_metadata.json." >&2
    exit 1
fi

# 2. Optionally publish/update Gemini Enterprise registration
if [[ "$TARGET" == "ge" || "$TARGET" == "both" ]]; then
    ensure_ge_app
    echo "Registering/updating '${AGENT_DISPLAY_NAME}' in Gemini Enterprise app '${GE_APP_NAME}'..."
    agents-cli publish gemini-enterprise \
        --registration-type adk \
        --gemini-enterprise-app-id "${GE_APP_NAME}" \
        --agent-runtime-id "${AGENT_RUNTIME_ID}" \
        --display-name "${AGENT_DISPLAY_NAME}" \
        --description "${AGENT_DESCRIPTION}" \
        --tool-description "${AGENT_DESCRIPTION}" \
        --project-id "${PROJECT_ID}" \
        --project-number "${PROJECT_NUMBER}"
fi

# 3. Optionally deploy the Cloud Run Web App
if [[ "$TARGET" == "web" || "$TARGET" == "both" ]]; then
    bash ./webapp/deploy.sh --agent-runtime-id "${AGENT_RUNTIME_ID}"
fi

echo "======================================================================="
echo "Deployment completed successfully! (Target: ${TARGET})"
echo "  Agent Runtime: ${AGENT_RUNTIME_ID}"
if [[ "$TARGET" == "ge" || "$TARGET" == "both" ]]; then
    echo "  Gemini Enterprise App: ${GE_APP_NAME}"
fi
if [[ "$TARGET" == "web" || "$TARGET" == "both" ]]; then
    echo "  Cloud Run Web Service: ${WEB_SERVICE_NAME} (${REGION})"
fi
echo "======================================================================="
