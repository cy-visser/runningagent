# AI Running Coach

An AI Running Coach and Exercise Physiologist built using the Google ADK framework. The coach integrates directly with **TrainingPeaks** (to fetch workouts, physiological metrics, and calendar notes), **Open-Meteo** (for hourly weather correlation), and **Google Cloud Firestore** (for session state persistence, per-runner KMS-encrypted credentials, and a structured training log).

In production, the **Vertex AI Agent Runtime** engine is served through the **Cloud Run Web App** (`webapp/`) behind **Cloud Run Identity-Aware Proxy (IAP)** with interactive fitness charts, profile & goal-plan editing, and self-service TrainingPeaks onboarding.

---

## Features
*   **Cloud Run Web App (`webapp/`)**: React + FastAPI web application behind Direct IAP backed by Vertex AI Agent Runtime.
*   **Feature-Sliced Codebase**: Clear vertical slices (`features/<feature>/`) mapping each skill (`SKILL.md`) to its tool (`*_tool.py`), private helpers (`helpers/`), shared domain modules (`shared/`), and external integrations (`integrations/`), enforced by `tests/test_structure.py`.
*   **Per-Runner KMS Credential Isolation**: Each runner links their own TrainingPeaks cookie in the Web App, encrypted with **Cloud KMS** (`AAD = b"users/{runner_id}"`) in `users/{runner_id}/private/trainingpeaks`.
*   **Multi-Agent Orchestration (`coach/`)**: Deterministic email-based routing between onboarding (profile & goal-plan creation) and coaching.
*   **Interactive Visual Reports**: Structured `checkin_report_data`, `trend_report_data`, and `audit_report_data` session state payloads render 90-day PMC charts, Sunset CTL progress rings, race-day projections, plan-audit calendars, and 6-month load-capacity ladders alongside coaching prose.
*   **Hourly Weather & Travel Context**: Correlates run splits with exact-hour Open-Meteo weather and scans calendar notes for travel.
*   **Training Log & 6-Month Trend Analysis**: Stores deterministic workout records in `users/{id}/training_log` for long-horizon efficiency, decoupling, and weekly volume durability analysis.

---

## Local Development

### 1. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate

pip install ./tp_mcp-2.0.0-py3-none-any.whl
pip install $(grep -v 'tp_mcp.*\.whl' requirements.txt)
```

### 2. Configure Environment Variables & Credentials
Authenticate Application Default Credentials so local runs can access Firestore and decrypt your runner's Cloud KMS credential:

```bash
gcloud auth application-default login
```

Copy `.env.example` to `.env` in `running_coach/` and fill it in (never put `TP_AUTH_COOKIE` in `.env`). It also holds
the models (`COACH_MODEL`, `COACH_THINKING_LEVEL`, `COACH_FALLBACK_MODEL`, `ONBOARDING_MODEL`); `agents-cli deploy`
passes `.env` to the Agent Runtime.

```bash
cp .env.example .env
```

### 3. Run Locally
- **ADK Developer UI**:
  ```bash
  adk web
  ```
- **Cloud Run Web App UI** (demo mode or full local stack): see [`webapp/README.md`](webapp/README.md).

---

## Testing

Behavioural feature tests and architectural structure checks cover the agent (`tests/`), the web backend (`webapp/backend/tests/`), and the React frontend (`webapp/frontend/src/`), requiring no live network access:

```bash
# Agent behavioural + structure tests (10 tests)
python -m pytest tests/ -q

# Web backend tests (4 tests)
(cd webapp/backend && python -m pytest tests/ -q)

# Web frontend tests (5 co-located tests) + production bundle check
cd webapp/frontend && npm test -- --run && npm run build
```

Behavioural eval sets in `evals/` exercise the full agent with live credentials:

```bash
# ADK 2.x: the eval set id must not contain a path, so run from evals/ ("n" answers the telemetry prompt)
cd evals && echo n | adk eval .. comprehensive_coach_evals.evalset.json --config_file_path eval_config.json
```

---

## Production Deployment Guide

Infrastructure is managed via **Terraform (IaC)**, per-runner TrainingPeaks credentials are encrypted with **Cloud KMS**, and deployments are driven by `./deploy.sh`.

### Prerequisites
Install `agents-cli` (`google-agents-cli`), `gcloud`, `jq`, and `curl`:
```bash
uv tool install google-agents-cli==1.8.0
```

### Phase 1: Provision Infrastructure (Terraform)
```bash
cd terraform
terraform init
terraform apply
```
*Provisions:*
*   **APIs**: Vertex AI, Cloud Run, Cloud Build, Artifact Registry, IAP, Cloud KMS, Firestore, Cloud Trace, Cloud Logging.
*   **Service Accounts**:
    *   `running-coach-agent@...` (Agent Runtime — `roles/cloudkms.cryptoKeyDecrypter`, Firestore, Vertex AI, Trace/Logs).
    *   `running-coach-web@...` (Cloud Run Web App — `roles/cloudkms.cryptoKeyEncrypter`, Firestore, `aiplatform.user`).
*   **Cloud KMS**: Keyring `running-coach` and symmetric key `tp-cookie` (90-day rotation).
*   **Firestore Indexes & TTL**: `training_log` date index, `users.email` index, and `workout_analyses` TTL policy.
*   **Traces Bucket**: `gs://traces_runningagent` for GenAI prompt/response completion logs.

### Phase 2: Deploy Agent Runtime & Cloud Run Web App
```bash
cd ..
chmod +x deploy.sh

# Dry-run preflight check:
./deploy.sh --dry-run

# Deploy Agent Runtime + Cloud Run Web App (behind IAP):
./deploy.sh

# Models come from .env. Rollback without a code change: set COACH_MODEL=gemini-3.8-flash and
# COACH_THINKING_LEVEL=HIGH in .env, then ./deploy.sh again.
```

Grant IAM users access to the Cloud Run Web App via IAP:
```bash
gcloud iap web add-iam-policy-binding \
  --project=YOUR_PROJECT_ID \
  --resource-type=cloud-run \
  --service=running-coach-web \
  --region=europe-west4 \
  --member="user:you@yourdomain.com" \
  --role="roles/iap.httpsResourceAccessor"
```

---

## Monitoring & Telemetry (Production)

*   **Cloud Trace**: End-to-end waterfall latency spans across Gemini, TrainingPeaks MCP, and Open-Meteo.
*   **Prompt & Response Completion Logs**: Uploaded as JSONL to `gs://traces_runningagent/completions/` while keeping message content out of Cloud Trace/Logging (`NO_CONTENT`).
*   **Cloud Monitoring**: Track `aiplatform.googleapis.com/prediction/token_count` grouped by `model_id`.
