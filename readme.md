# AI Running Coach

An AI Running Coach and Exercise Physiologist built using the Google ADK framework. The coach integrates directly with **TrainingPeaks** (to fetch workouts, physiological metrics, and calendar notes), **Open-Meteo** (for hourly weather correlation), and **Google Cloud Firestore** (for session state persistence and historical check-in reports).

When deployed, the agent integrates seamlessly with **Gemini Enterprise**, rendering rich, interactive progress reports in the **Canvas UI** and falling back gracefully to chat in local environments.

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
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the project root containing the configuration parameters. Copy the template below and replace placeholder values with your actual configuration:

```env
# Enable Vertex AI GenAI SDK mode
GOOGLE_GENAI_USE_VERTEXAI=1

# Google Cloud Deployment project details
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
FIRESTORE_PROJECT_ID=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=YOUR_LOCATION

# Firestore database name for the agent (defaults to running-coach)
FIRESTORE_DATABASE=running-coach

# PYTHONPATH injection needed specifically for container deployment startup
PYTHONPATH=/app/agents/running_coach

# TrainingPeaks Cookie (Required for local test runs; Secret Manager handles production)
TP_AUTH_COOKIE=YOUR_TRAININGPEAKS_COOKIE_HERE
```

### 3. Run the Local Web Server
To open the interactive ADK Web UI and chat with the coach locally:
```bash
adk web
```
Open your browser and navigate to `http://127.0.0.1:8000`.

---

## Production Deployment Guide

We follow production best practices: managing infrastructure via **Terraform (IaC)** and storing sensitive credentials securely in **GCP Secret Manager** .

### Phase 1: Provision Infrastructure (Terraform)
Navigate to the `terraform/` directory and run Terraform to enable APIs, create the service account, grant IAM roles, and provision the secret container:

```bash
cd terraform
terraform init
terraform apply
```
*Review the plan and type `yes` to approve. This will provision:*
*   **APIs**: Vertex AI, Secret Manager, Firestore, Cloud Trace, Cloud Logging.
*   **Service Account**: `running-coach-agent@your_project_id.iam.gserviceaccount.com`.
*   **IAM Roles**: Vertex AI User, Firestore User, Trace Agent, Logs Writer, Secret Accessor, and the critical Vertex AI Service Agent binding.
*   **Secret**: A secure container named `tp-auth-cookie`.

### Phase 2: Deploy the Agent & Upload the Secret
Return to the project root and run the deployment script, passing your TrainingPeaks cookie. The script will upload the cookie to Secret Manager as a new version and deploy the agent to the Vertex AI Agent Platform (Reasoning Engine):

```bash
cd ..
chmod +x deploy.sh
./deploy.sh --tp-cookie 'YOUR_ACTUAL_TP_COOKIE_HERE'
```

---

## Monitoring & Telemetry (Production)

Once deployed, the agent is fully instrumented with OpenTelemetry (`--otel_to_cloud`), allowing you to monitor performance, latencies, and costs in the **Google Cloud Console**:

### 1. Request Traces & Bottlenecks (Cloud Trace)
*   Go to **Cloud Trace** -> **Trace Explorer**.
*   View end-to-end waterfall latency charts for every check-in session, showing exactly how long the LLM, TrainingPeaks API, and weather API took.

### 2. Token Usage & Cost Tracking (Cloud Monitoring)
To monitor your token consumption and set up budget alerts:
*   Go to **Monitoring** -> **Metrics Explorer**.
*   Select the metric: `aiplatform.googleapis.com/prediction/token_count`.
*   Group by `model_id` to track and compare token usage.
*   Set up an **Alerting Policy** to notify you if token consumption spikes, protecting you against billing surprises.

### 3. Live Logs (Cloud Logging)
*   Go to **Logging** -> **Logs Explorer**.
*   Search for logs associated with the `running-coach-agent` service account to view real-time execution logs (including `DEBUG:` statements) structured by session ID.
