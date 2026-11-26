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

# Refuse to run if DEV_RUNNER_EMAIL is set (local adk web / adk eval only; never deploy to production).
if { [ -f .env ] && grep -q -E '^[[:space:]]*DEV_RUNNER_EMAIL=' .env; } || [ -n "${DEV_RUNNER_EMAIL:-}" ]; then
    echo "Error: DEV_RUNNER_EMAIL is for local 'adk web' / 'adk eval' only and must not be set in .env or during deploy." >&2
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

for bin in agents-cli gcloud jq; do
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
SESSION_URI="firestore://"
KMS_KEY_RING="${KMS_KEY_RING:-running-coach}"
KMS_KEY_NAME="${TP_COOKIE_KMS_KEY_NAME:-tp-cookie}"
KMS_KEY="${TP_COOKIE_KMS_KEY:-projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KMS_KEY_RING}/cryptoKeys/${KMS_KEY_NAME}}"
WEB_SERVICE_NAME="${WEB_SERVICE_NAME:-running-coach-web}"
TRACES_BUCKET="${TRACES_BUCKET:-traces_runningagent}"
AGENT_DISPLAY_NAME="Running Coach"
DRY_RUN=false

usage() {
    cat <<EOF
Usage: ./deploy.sh [--dry-run]

Deploys the Running Coach ADK agent to Vertex AI Agent Runtime and the Cloud Run Web App (IAP).

Options:
  --dry-run   Validate preflight and print planned deployment actions without mutating resources
EOF
}

while [[ "$#" -gt 0 ]]; do
    case $1 in
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

# Preflight: ensure the pre-built tp_mcp wheel matches trainingpeaks-mcp/src and requirements.txt.
TP_MCP_VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' trainingpeaks-mcp/pyproject.toml | head -n 1)
TP_MCP_WHEEL="tp_mcp-${TP_MCP_VERSION}-py3-none-any.whl"
if [ -z "$TP_MCP_VERSION" ] || [ ! -f "$TP_MCP_WHEEL" ]; then
    echo "Error: Missing ${TP_MCP_WHEEL} for trainingpeaks-mcp ${TP_MCP_VERSION}." >&2
    echo "Rebuild it with: (cd trainingpeaks-mcp && uv build --wheel --out-dir ..)" >&2
    exit 1
fi
if ! grep -q "${TP_MCP_WHEEL}" requirements.txt; then
    echo "Error: requirements.txt does not reference ${TP_MCP_WHEEL}." >&2
    exit 1
fi
if ! python3 - "$TP_MCP_WHEEL" <<'PY'
import pathlib, sys, zipfile
whl, src = pathlib.Path(sys.argv[1]), pathlib.Path("trainingpeaks-mcp/src")
with zipfile.ZipFile(whl) as zf:
    whl_py = {n: zf.read(n) for n in zf.namelist() if n.startswith("tp_mcp/") and n.endswith(".py")}
src_py = {p.relative_to(src).as_posix(): p.read_bytes() for p in src.rglob("*.py")}
sys.exit(0 if whl_py == src_py else 1)
PY
then
    echo "Error: ${TP_MCP_WHEEL} does not match files in trainingpeaks-mcp/src/." >&2
    echo "Bump the version and rebuild it with: (cd trainingpeaks-mcp && uv build --wheel --out-dir ..)" >&2
    exit 1
fi

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
    # Record every run. Agent Runtime's front end forwards a rate-limited traceparent (often
    # sampled=0, e.g. a run started right after its session is created); the default
    # parentbased_always_on sampler would then silently drop the whole run.
    "OTEL_TRACES_SAMPLER=always_on"
)
RUNTIME_ENV_CSV=$(IFS=,; echo "${RUNTIME_ENV_VARS[*]}")

echo "======================================================================="
echo " Deploying Running Coach (Agent Runtime + Cloud Run Web App)"
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

    bash ./webapp/deploy.sh --dry-run --agent-runtime-id "${EXISTING_RUNTIME_ID}"
    exit 0
fi

# 1. Deploy the ADK agent to Vertex AI Agent Runtime
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

# 2. Deploy the Cloud Run Web App
bash ./webapp/deploy.sh --agent-runtime-id "${AGENT_RUNTIME_ID}"

echo "======================================================================="
echo "Deployment completed successfully!"
echo "  Agent Runtime: ${AGENT_RUNTIME_ID}"
echo "  Cloud Run Web Service: ${WEB_SERVICE_NAME} (${REGION})"
echo "======================================================================="
