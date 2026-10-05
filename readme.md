# AI Running Coach

An AI Running Coach and Exercise Physiologist built using the Google ADK framework. The coach integrates directly with **TrainingPeaks** (to fetch workouts, physiological metrics, and calendar notes), **Open-Meteo** (for hourly weather correlation), and **Google Cloud Firestore** (for session state persistence and historical check-in reports).

When deployed, the agent integrates seamlessly with **Gemini Enterprise** to deliver interactive coaching guidance in chat.

---

## Features
*   **Multi-Agent Orchestration**: Dynamically routes between onboarding (profile creation) and coaching.
*   **Consolidated Data Pulling**: Fetches workouts, sleep, HRV, RHR, and calendar notes.
*   **Hourly Weather Correlation**: Fetches the weather at the *exact hour* of your runs and compares it to the daily peak, explaining the physiological impact.
*   **AI Travel Detection**: Automatically scans calendar notes and workouts for travel and incorporates travel context into the report.
*   **Long-Term Goal Progress**: Anchors weekly feedback in your ultimate goal (e.g., the NYC Marathon) and declares if you are `ON TRACK`.
*   **Interactive Historical Saving**: Offers to save your check-in reports to Firestore, storing them as structured JSON under a `weeknumber-year` subcollection (e.g., `27-2026`).

---

## Local Development

### 1. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate

# The wheel path inside requirements.txt is relative to the deployment container
# layout (/app/agents/running_coach), so install it explicitly first, then install
# the remaining dependencies.
pip install ./tp_mcp-2.0.0-py3-none-any.whl
pip install $(grep -v 'tp_mcp.*\.whl' requirements.txt)
```

### 2. Configure Environment Variables & Credentials
Both local runs and deployed instances read the TrainingPeaks cookie from **Secret Manager** (`tp-auth-cookie`). Authenticate Application Default Credentials once so local runs can access Secret Manager and Firestore:

```bash
gcloud auth application-default login
```

Create a `.env` file in the project root containing the configuration parameters (never put `TP_AUTH_COOKIE` in `.env`):

```env
# Enable Vertex AI GenAI SDK mode
GOOGLE_GENAI_USE_VERTEXAI=1

# Google Cloud Deployment project details
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
FIRESTORE_PROJECT_ID=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=eu

# Firestore database name for the agent (defaults to running-coach)
FIRESTORE_DATABASE=running-coach

# PYTHONPATH injection needed specifically for container deployment startup
PYTHONPATH=/app/agents/running_coach
```

### 3. Run the Local Web Server
To open the interactive ADK Web UI and chat with the coach locally:
```bash
adk web
```
Open your browser and navigate to `http://127.0.0.1:8000`.

---

## Testing

Unit tests cover the pure helper layer (`utils/` and the extracted `tools.py` helpers). They
require no network access, GCP credentials, or TrainingPeaks cookie:

```bash
python -m pytest tests/ -q
```

The behavioural eval sets in `evals/` exercise the full agent and **do** require live
credentials:

```bash
adk eval . evals/comprehensive_coach_evals.evalset.json --config_file_path evals/eval_config.json
```

---

## Production Deployment Guide

We follow production best practices: managing infrastructure via **Terraform (IaC)**, storing sensitive credentials in **GCP Secret Manager**, and deploying/publishing with **`agents-cli`**.

### Prerequisites
Install `agents-cli` (`google-agents-cli`), `gcloud`, `jq`, and `curl`:
```bash
uv tool install google-agents-cli==1.8.0
```

### Phase 1: Provision Infrastructure (Terraform)
Navigate to the `terraform/` directory and run Terraform to enable APIs, create the service account, grant IAM roles, provision the secret container, and manage the prompt/response traces bucket:

```bash
cd terraform
terraform init
terraform apply
```
*Review the plan and type `yes` to approve. This will provision:*
*   **APIs**: Vertex AI, Discovery Engine (Gemini Enterprise), Secret Manager, Firestore, Cloud Trace, Cloud Logging.
*   **Service Account**: `running-coach-agent@your_project_id.iam.gserviceaccount.com`.
*   **IAM Roles**: Vertex AI User, Firestore User, Trace Agent, Logs Writer, Secret Accessor, Storage Object User on `gs://traces_runningagent`, and the Vertex AI Service Agent bindings.
*   **Secret**: A secure container named `tp-auth-cookie`.
*   **Traces Bucket**: `gs://traces_runningagent` for GenAI prompt and response completion logs.

### Phase 2: Deploy the Agent & Register in Gemini Enterprise
Return to the project root and run `deploy.sh`. The script:
1. Uploads a new TrainingPeaks cookie version to Secret Manager if `--tp-cookie` is passed (otherwise verifies an active version exists).
2. Ensures a Gemini Enterprise app named **Running Coach** exists (creating it if needed).
3. Deploys the container image to Vertex AI Agent Runtime via `agents-cli deploy` with prompt/response logging to `gs://traces_runningagent/completions`.
4. Registers or updates the agent in the **Running Coach** Gemini Enterprise app via `agents-cli publish gemini-enterprise`.

```bash
cd ..
chmod +x deploy.sh

# Validate preflight, app lookup, and deploy config without making changes:
./deploy.sh --dry-run

# First deployment (or rotating the TrainingPeaks cookie):
./deploy.sh --tp-cookie 'YOUR_ACTUAL_TP_COOKIE_HERE'

# Subsequent deployments (reuses secret in Secret Manager):
./deploy.sh
```

---

## Monitoring & Telemetry (Production)

Once deployed, the agent is instrumented with OpenTelemetry (`--otel_to_cloud`), allowing you to monitor performance, latencies, prompts/responses, and costs in the **Google Cloud Console**:

### 1. Request Traces & Bottlenecks (Cloud Trace)
*   Go to **Cloud Trace** -> **Trace Explorer**.
*   View end-to-end waterfall latency charts for every check-in session, showing how long the LLM, TrainingPeaks API, and weather API took.

### 2. Prompt & Response Completion Logs (Cloud Storage)
*   Every model invocation uploads its prompt inputs, system instructions, tool definitions, and model responses as JSONL files under `gs://traces_runningagent/completions/`.
*   Message content is kept out of Cloud Trace and Cloud Logging (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT`); trace spans and log events reference the uploaded GCS objects.

### 3. Token Usage & Cost Tracking (Cloud Monitoring)
To monitor your token consumption and set up budget alerts:
*   Go to **Monitoring** -> **Metrics Explorer**.
*   Select the metric: `aiplatform.googleapis.com/prediction/token_count`.
*   Group by `model_id` to track and compare token usage.
*   Set up an **Alerting Policy** to notify you if token consumption spikes, protecting you against billing surprises.

### 4. Live Logs (Cloud Logging)
*   Go to **Logging** -> **Logs Explorer**.
*   Search for logs associated with the `running-coach-agent` service account to view real-time execution logs structured by session ID.

