#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

# Refuse to run if TP_AUTH_COOKIE is present in .env (secrets belong in Secret Manager).
if [ -f .env ] && grep -q -E '^[[:space:]]*TP_AUTH_COOKIE=' .env; then
    echo "Error: TP_AUTH_COOKIE must not be present in .env."
    echo "Remove TP_AUTH_COOKIE from .env; both local and deployed runs read from Secret Manager."
    exit 1
fi

# Load .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^[[:space:]]*#' .env | grep -v '^[[:space:]]*$' | xargs)
fi

if [ -z "${GOOGLE_CLOUD_PROJECT:-}" ]; then
    echo "Error: GOOGLE_CLOUD_PROJECT environment variable or config in .env is required."
    exit 1
fi

if [ -z "${GOOGLE_CLOUD_LOCATION:-}" ]; then
    echo "Error: GOOGLE_CLOUD_LOCATION environment variable or config in .env is required."
    exit 1
fi

for bin in agents-cli gcloud curl jq; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "Error: Required tool '$bin' is not installed or not on PATH."
        if [ "$bin" = "agents-cli" ]; then
            echo "Install it once with: uv tool install google-agents-cli==1.8.0"
        fi
        exit 1
    fi
done

PROJECT_ID="$GOOGLE_CLOUD_PROJECT"
REGION="${DEPLOY_REGION:-europe-west4}"
IDENTITY="running-coach-agent@${PROJECT_ID}.iam.gserviceaccount.com"
SESSION_URI="firestore://${PROJECT_ID}"
SECRET_NAME="${TP_COOKIE_SECRET_ID:-tp-auth-cookie}"
TRACES_BUCKET="${TRACES_BUCKET:-traces_runningagent}"
GE_LOCATION="${GE_LOCATION:-global}"
GE_APP_ID="${GE_APP_ID:-running-coach}"
GE_APP_DISPLAY_NAME="Running Coach"
AGENT_DISPLAY_NAME="Running Coach"
AGENT_DESCRIPTION="Your running coach which helps you progressing your running fitness."
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

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
if [ -z "$PROJECT_NUMBER" ]; then
    echo "Error: Could not resolve project number for project '${PROJECT_ID}'."
    exit 1
fi

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

if [ "$GE_LOCATION" = "global" ]; then
    DE_BASE_URL="https://discoveryengine.googleapis.com"
else
    DE_BASE_URL="https://${GE_LOCATION}-discoveryengine.googleapis.com"
fi

# Looks up an existing Gemini Enterprise app with displayName == GE_APP_DISPLAY_NAME.
# Prints matching resource names (one per line).
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

# Ensures the Gemini Enterprise app exists and sets GE_APP_NAME to its full resource name.
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
    "TP_COOKIE_SECRET_ID=${SECRET_NAME}"
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
echo " Deploying Running Coach Agent (Vertex AI Agent Runtime + Gemini Enterprise)"
echo "======================================================================="
echo "Project:       ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "Region:        ${REGION}"
echo "Identity:      ${IDENTITY}"
echo "GE Location:   ${GE_LOCATION}"
echo "Traces Bucket: gs://${TRACES_BUCKET}/completions"
echo "======================================================================="

# 1. Upload/Update the cookie in Secret Manager (if a new value was provided)
if [ "$DRY_RUN" = true ]; then
    if [ -n "$TP_COOKIE" ]; then
        echo "[DRY RUN] Would upload new TrainingPeaks cookie to Secret Manager secret '${SECRET_NAME}'."
    else
        echo "[DRY RUN] Using existing '${SECRET_NAME}' secret from Secret Manager."
    fi
    ensure_ge_app
    agents-cli deploy \
        --project "${PROJECT_ID}" \
        --region "${REGION}" \
        --service-name "${AGENT_DISPLAY_NAME}" \
        --service-account "${IDENTITY}" \
        --update-env-vars "${RUNTIME_ENV_CSV}" \
        --dry-run
    echo "[DRY RUN] Would register/update '${AGENT_DISPLAY_NAME}' in Gemini Enterprise app '${GE_APP_NAME}'."
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

# 2. Ensure the "Running Coach" Gemini Enterprise app exists
ensure_ge_app

# 3. Deploy to Vertex AI Agent Runtime with agents-cli
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

# 4. Register or update the agent in the Gemini Enterprise app
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

echo "======================================================================="
echo "Deployment & Gemini Enterprise registration completed successfully!"
echo "  Agent Runtime:         ${AGENT_RUNTIME_ID}"
echo "  Gemini Enterprise App: ${GE_APP_NAME}"
echo "======================================================================="
